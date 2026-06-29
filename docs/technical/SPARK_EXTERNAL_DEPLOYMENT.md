# External Spark / Databricks integration

The app ships with a self-contained Spark stack (`spark-master`,
`spark-worker`, `spark-connect`) bundled into `docker-compose.yml`
under the **`local-spark`** profile. That stack is convenient for
development but production deployments almost always want the app to
point at an **externally-managed Spark Connect endpoint** — a
self-managed Spark cluster, a managed Spark Connect service, or a
Databricks workspace.

This doc covers:

1. [App-side configuration](#1--app-side-configuration) — env vars to
   set on the backend container.
2. [External-Spark-side setup](#2--external-spark-side-setup) — what
   the Spark cluster needs in order to register the app's
   Postgres-resident tables as JDBC temp views (or materialise them as
   Delta tables).
3. [Databricks-specific notes](#3--databricks-specific-notes) — PAT
   auth, secret-scope storage, JDBC driver provisioning.
4. [Verification + troubleshooting](#4--verification--troubleshooting)
   — how to confirm end-to-end works.

---

## 1 · App-side configuration

The bundled Spark stack starts only when you explicitly request the
profile:

```bash
# Default — no Spark containers, app runs DuckDB engine OR talks to
# external Spark.
docker compose up

# Dev convenience — also starts the bundled spark-master + worker + connect.
docker compose --profile local-spark up
```

Point the backend at external Spark by setting these env vars in
`.env` (read by the backend container at startup; see
`backend/spark_session.py:_build_remote`):

| Variable | Required? | Purpose |
|---|---|---|
| `SPARK_CONNECT_URL` | recommended | Full Spark Connect URI override. Wins over the host/port pair. Example: `sc://spark.acme.example.com:443/;use_ssl=true;token=ABC123`. |
| `SPARK_CONNECT_HOST` | required if URL not set | Hostname of the external Spark Connect endpoint. |
| `SPARK_CONNECT_PORT` | optional | gRPC port. Defaults to `15002`. |
| `SPARK_CONNECT_TOKEN` | optional | Bearer token for authenticated Spark Connect endpoints (Databricks, secured self-managed). Forwarded as a gRPC metadata header. |
| `SPARK_CONNECT_USE_SSL` | optional | `true` to negotiate TLS for the gRPC connection. Required when terminating SSL at the Spark side or in front of it. |

For the JDBC reads that Spark performs **back** against the app's
Postgres (so it can expose `billing_usage` / `qi_*` / lineage etc. as
temp views or Delta-shadow views), there are five more vars:

| Variable | Default | Purpose |
|---|---|---|
| `SPARK_PG_HOST` | `db` (the docker service name) | Postgres host **from Spark's network perspective**. Set to a hostname Spark executors can resolve — usually a private DNS name, occasionally a public DNS name if Postgres is exposed. |
| `SPARK_PG_PORT` | `5432` | Postgres port from Spark's perspective. |
| `SPARK_PG_DB` | `DB_NAME` | Database name. |
| `SPARK_PG_USER` | `DB_USER` | Postgres user Spark connects as. **Best practice**: provision a read-only role with `SELECT` on `billing_usage`, `clusters`, `warehouses`, `jobs`, `workspaces`, `query_history`, `databricks_meta`, `table_lineage`, `column_lineage`, `lineage_rollups`, `audit_events`, `assistant_events`, `node_timeline`, `warehouse_events`, `node_types`, `instance_events`, `instance_pools`, and the `qi_*` family. |
| `SPARK_PG_PASS` | `DB_PASS` | Postgres password. Surface via your secret manager — never inline in compose files. |
| `SPARK_PG_SSL` | `false` | `true` to append `?sslmode=require` to the JDBC URL. Recommended whenever Spark and Postgres are on different networks. |

The backend's own Postgres credentials (`DB_HOST` / `DB_PORT` /
`DB_USER` / `DB_PASS`) stay separate — the app talks to Postgres via
asyncpg over the docker network, while Spark talks over JDBC from
elsewhere.

### Example: external Spark on a private VPC

```env
# .env
SPARK_CONNECT_HOST=spark-connect.internal.acme.example
SPARK_CONNECT_PORT=15002
# No TLS — internal VPC. No token — internal mTLS or network ACL.

SPARK_PG_HOST=billing-db.internal.acme.example
SPARK_PG_PORT=5432
SPARK_PG_USER=spark_reader
SPARK_PG_PASS=...     # via secret manager
SPARK_PG_SSL=true
```

### Example: Databricks workspace

```env
# .env
SPARK_CONNECT_URL=sc://adb-1234567890.azuredatabricks.net:443/;use_ssl=true;token=dapi-***-***
# (Postgres host must be reachable FROM Databricks. Typically a
# VPC-peered / Private Link-attached DB hostname.)
SPARK_PG_HOST=billing-db.private.acme.example
SPARK_PG_PORT=5432
SPARK_PG_USER=spark_reader
SPARK_PG_PASS=...
SPARK_PG_SSL=true
```

---

## 2 · External-Spark-side setup

The app drives Spark via Spark Connect — it sends `.read.format("jdbc")
… .createOrReplaceTempView(...)` calls and SQL queries to the endpoint.
For those to succeed, the external Spark must satisfy three preconditions:

### 2a · Postgres JDBC driver available on the classpath

Spark workers/executors need `org.postgresql:postgresql` on the classpath
to open the JDBC connection. Three ways to provision it:

1. **`--packages` at Spark Connect server startup** (what the bundled
   compose does):
   ```
   spark-submit … --packages org.postgresql:postgresql:42.7.4 …
   ```
2. **Pre-baked into the Spark image / installation** by dropping the
   JAR into `$SPARK_HOME/jars/`.
3. **Per-application via `spark.jars.packages`** in `spark-defaults.conf`.

Pin to **42.7.4** or newer (matches the version the bundled stack uses
and is known to work with Postgres 16).

### 2b · Delta Lake (only if you plan to use `spark_mode='materialized'`)

The "Materialize Postgres → Spark" button copies Postgres tables into
the Spark catalog as managed Delta tables. That requires Delta Lake
JARs + the Delta SQL extension:

```
spark-submit \
  --packages io.delta:delta-spark_2.13:4.1.0,org.postgresql:postgresql:42.7.4 \
  --conf spark.sql.extensions=io.delta.sql.DeltaSparkSessionExtension \
  --conf spark.sql.catalog.spark_catalog=org.apache.spark.sql.delta.catalog.DeltaCatalog \
  --conf spark.sql.warehouse.dir=/path/to/spark-warehouse \
  …
```

Skip this if you're staying in `spark_mode='jdbc_views'` — the app
won't write anything to Spark in that mode, only register temp views.

### 2c · Network reachability

Spark executors must be able to open TCP to `SPARK_PG_HOST:SPARK_PG_PORT`.
Common failure modes:

- **Databricks** — without VPC peering / Private Link, Databricks
  workers can't reach a Postgres in your private VPC. Either expose
  Postgres over the public internet (recommend strict pg_hba + SSL +
  IP allowlist) or wire up Private Link.
- **Kubernetes-hosted Spark** — make sure the Spark namespace's
  `NetworkPolicy` allows egress to the Postgres CIDR / service.
- **Self-managed cluster behind a corporate firewall** — open the
  Postgres port from the Spark subnet.

### 2d · Spark driver/executor heap sizing

The JDBC reads materialise into the driver heap before the temp view
is registered. On large tables (`table_lineage` can run to 8M+ rows on
real accounts), the default 1 GB heap will OOM. Set at server startup:

```
--driver-memory 2g
--conf spark.executor.memory=3g
```

The app sets `pushDownPredicate / pushDownLimit / pushDownOffset /
pushDownAggregate` on every JDBC read, so most analytical queries
push the heavy work down to Postgres — but `SELECT *` on a large
table will still pull everything across.

### 2e · Spark version

The app pins `pyspark[connect] 4.1.1` in the backend image. The
external Spark Connect server should be **4.1.x or newer** to avoid
protocol mismatches. Spark 3.5.x Connect won't speak the same gRPC
schema.

---

## 3 · Databricks-specific notes

If your "external Spark" is a Databricks workspace, two extra
considerations:

### 3a · Personal Access Token (PAT)

Databricks Spark Connect uses PAT authentication. Generate a token
in **User Settings → Developer → Access tokens**, then surface it via
`SPARK_CONNECT_TOKEN` (or inline as `;token=dapi-…` in
`SPARK_CONNECT_URL`).

**Never** commit the token. Use docker compose's `env_file:` to load
from a `.env` that's `.gitignore`d, or wire to your secret manager
(AWS Secrets Manager / Azure Key Vault / GCP Secret Manager / HashiCorp
Vault) via an init container.

### 3b · Postgres JDBC driver on the cluster

Install the Postgres JDBC driver on the Databricks cluster:

1. **Compute → your cluster → Libraries → Install new → Maven**
2. Coordinates: `org.postgresql:postgresql:42.7.4`
3. Restart the cluster.

Or attach as a **cluster init script** if you provision clusters via
Terraform / IaC.

### 3c · Workspace catalog vs `spark_catalog`

The app's materialised-Delta mode writes to `spark_catalog.default`.
On Databricks Unity Catalog workspaces, `spark_catalog` is read-only
by default — writes go to the workspace's primary catalog. Either:

- **Stay in `jdbc_views` mode** (recommended for Databricks) so the
  app only registers temp views and never writes Delta tables.
- Set the workspace's session catalog to a UC catalog the app can
  write to, and re-test with the Materialize button.

The temp-view registration in `jdbc_views` mode works identically
against Databricks — Spark Connect doesn't care that the catalog is
UC-flavoured.

---

## 4 · Verification + troubleshooting

After setting the env vars and restarting the backend:

1. **In the UI: Admin → Data Management → Query Engine** — switch to
   "Spark". Hit any Query Profiler page (e.g. Overview). If you see
   numbers, you're connected. If you see a **503** with a gRPC error
   in the body, the Spark Connect endpoint is unreachable.

2. **Backend logs** — look for the connect line. The token (if set)
   is redacted automatically:
   ```
   [spark] connecting to sc://spark.acme.example.com:443/;use_ssl=true;token=*** ...
   ```

3. **JDBC temp-view registration logs** — on the first request to a
   Spark-engine endpoint, you'll see one line per table:
   ```
   [spark] base+qi JDBC views registered for view_mode=real: billing_usage, list_prices, clusters, …
   ```
   If you see **`[spark] failed to register <table> via JDBC: …`**,
   that's the JDBC driver / network / credential path failing.
   Common causes:
   - `ClassNotFoundException: org.postgresql.Driver` → JDBC driver not
     on Spark's classpath (see §2a).
   - `connection refused` / `host unreachable` → network reachability
     from Spark to Postgres (see §2c).
   - `password authentication failed` → `SPARK_PG_USER` /
     `SPARK_PG_PASS` mismatch with the actual role.

4. **End-to-end smoke test** — open Spark SQL Editor (Admin →
   `/spark-sql`), confirm the table list shows all 23 Postgres-resident
   tables marked **`temp`**, run `SELECT COUNT(*) FROM billing_usage`.
   Should return non-zero if data is loaded.

5. **Switching back to DuckDB** is instant and risk-free if Spark
   misbehaves: Admin → Data Management → Query Engine → DuckDB. The
   app stops talking to Spark immediately. All dashboards keep working
   because DuckDB reads from Postgres directly.

---

## See also

- [`QUERY_ENGINE.md`](QUERY_ENGINE.md) — DuckDB vs Spark engine rationale + sub-mode behavioural differences.
- [`SPARK_STACK.md`](SPARK_STACK.md) — Deployment layout of the bundled Spark services (master/worker/connect/Ivy cache/Delta JARs).
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — Where Spark sits in the overall system diagram.
