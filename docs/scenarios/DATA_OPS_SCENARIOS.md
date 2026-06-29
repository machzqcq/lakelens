# Data Management & Platform Ops — Scenarios & Questions

A field guide for the **admin-side** surfaces of the app:

- **Data Management** — extract groups, per-table lookback knobs, full vs incremental loads, ingest from parquet, demo seed, soft / hard delete, restore, engine switch, lineage rollup transform.
- **Database Explorer** — read-only Postgres browser for the operational warehouse.
- **Spark SQL Editor** — admin-only SQL surface over the Spark engine (only when engine is `spark`).
- **Users & Roles** — RBAC management, per-user feature flags, filter scoping.
- **View-mode toggle** — top-right `Real` ↔ `Demo` switch per user.
- **Notifications bell** — top-right background-job ticker.

This catalog is grouped by the **operational role** that owns each task.

---

## 1. Which app pages back these scenarios

| App page (sidebar path) | What it does | Backed by |
|---|---|---|
| **Data Management** | Trigger extract from Databricks (per-group, per-table lookback days), ingest from parquet, seed demo data, soft / hard delete (Real or Demo), restore, transform-lineage, materialize Postgres → Spark, monitor live progress with Cancel, swap engine (DuckDB ↔ Spark JDBC views / materialized). | `/api/admin/extract`, `/api/admin/ingest-parquet`, `/api/admin/seed-demo`, `/api/admin/clear-data`, `/api/admin/extract-query-intel`, `/api/admin/transform-lineage`, `/api/admin/materialize-postgres-to-spark`, `/api/admin/engine`, `/api/data-ops/{soft-delete,hard-delete,restore,incremental-load,progress,jobs}` |
| **Database Explorer** | Read-only Postgres browser; list objects, run SELECTs against the operational warehouse, see columns and row counts. | `/api/admin/db/objects`, `/api/admin/db/query` |
| **Spark SQL Editor** | Admin-only Spark SQL surface; lists temp views over Postgres, runs ad-hoc queries on the Spark engine (when active). | `/api/spark-sql/session`, `/api/spark-sql/tables`, `/api/spark-sql/query` |
| **Users** | Create / patch / delete users, assign / unassign roles, see OAuth providers, activation, email-verification. | `/api/admin/users` |
| **Roles** | Create / patch / delete roles; configure row-level filters (per-workspace, per-cloud, etc.) and feature flags. | `/api/admin/roles`, `/api/admin/filter-dimensions`, `/api/admin/feature-registry` |
| **View-mode toggle (top-right)** | Per-user switch — Real ↔ Demo. All dashboards, the chatbot, and the Spark SQL editor see only the partition matching the user's mode. | `/api/data-ops/me/view-mode` |
| **Notifications bell (top-right)** | Background-job ticker — running extract / ingest / delete operations with a Cancel button. | `/api/data-ops/jobs` |

---

## 2. Why this surface is essential

Without the Data Management surface, the dashboards have nothing to
show. It is the **operational backbone** that:

- **Brings data in** — extract from `system.*` Databricks tables, ingest from parquet, seed demo.
- **Cleans data out** — soft (set `deleted_at`) and hard (`DELETE FROM`) delete, scoped by view mode.
- **Keeps data isolated** — `data_origin` partition + `deleted_at` filter, so demo and real never bleed.
- **Selects the engine** — DuckDB (default) vs Spark via JDBC views vs Spark via materialized tables.
- **Provides escape hatches** — Database Explorer for Postgres-level reads, Spark SQL Editor for Spark-level reads, both surfaced as forensic / dev tools.
- **Governs access** — RBAC with per-role row filters and per-role feature flags.

---

## 3. How to read the scenarios

> **Q.** The question or operational task.
> *App page:* where to do it. *Needs:* parameters / prerequisites.
> *Why it matters:* what the outcome unblocks.

---

## 4. Platform Admin (day-1 setup)

### 4.1 First boot

**Q.** I just spun up the stack. There's no data — what should I do first?
*App page:* Data Management → click **Seed Demo** (the first option, default).
*Needs:* nothing — the demo parquet ships with the app.
*Why it matters:* the demo seed gives every dashboard immediate, realistic data so the user can explore before configuring Databricks credentials.

### 4.2 Connect to real Databricks

**Q.** How do I switch from Demo to Real with my Databricks workspace?
*App page:* (Backend env) set `DATABRICKS_HOST` / `DATABRICKS_TOKEN`. Restart. Then Data Management → **Extract from Databricks** → pick groups + lookback days.
*Needs:* `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, account with read on `system.*` schemas.
*Why it matters:* the moment the app starts producing org-specific insight.

### 4.3 First real extract — what to pick?

**Q.** Which extract groups should I run first?
*Recommended order:* `billing` + `compute` (small, gives KPIs) → `meta` (catalog snapshot) → `query_history` (large, gives Query Profiler) → `lineage` (depends on UC) → `audit` (small) → `node_pool` (large, infra utilization).
*Lookback defaults:* audit = 3 days, table_lineage = 14, column_lineage = 7, node_timeline = 3, warehouse_events = 30, instance_events = 14, assistant_events = 30.
*Why it matters:* the per-table lookback knobs let you start small and expand once you've confirmed the integration works.

---

## 5. Daily Operations

### 5.1 Refresh data

**Q.** I want to refresh today's data from Databricks.
*App page:* Data Management → choose **Incremental** mode → click Extract.
*Needs:* recent extract exists; pick the groups you want refreshed.

### 5.2 Watch a long-running extract

**Q.** How do I know if it's done?
*App page:* Notifications bell (top-right) shows live progress; Data Management shows per-table progress cards.
*Needs:* nothing — the polling is automatic.

### 5.3 Cancel a stuck job

**Q.** The extract is taking too long; can I cancel?
*App page:* Click the **X** next to the running progress card (Data Management) or the notifications-bell job.
*Behind the scenes:* sets `cancel_requested=true`; the extractor checks this flag between table-level batches and exits cleanly with HTTP 499.

### 5.4 Recover from a partial failure

**Q.** One table in the extract failed — what's the state?
*App page:* Data Management → progress card shows the table that failed with its error message; other tables in the same group continued and ingested. Re-run the failed group with the same lookback to retry.
*Why it matters:* per-table progress prevents an all-or-nothing failure model.

---

## 6. Demo / Real Isolation

### 6.1 Switch view mode

**Q.** I want to show the app to a customer without exposing our real data.
*App page:* top-right → Demo. All dashboards, chatbot, Spark SQL editor scope to `data_origin='demo'`.
*Needs:* demo parquet must be loaded (Seed Demo or one ships by default).

### 6.2 Re-seed demo

**Q.** The demo data is showing customer catalog names that shouldn't be there.
*App page:* Data Management → Clear Data (Demo only) → Seed Demo again.
*Behind the scenes:* the simulator scrubs catalog/schema/table/column names with substring substitution; if older parquet leaked through, hard-delete clears it.

### 6.3 Refresh demo without losing real

**Q.** Re-seed demo without touching real data.
*App page:* Data Management → make sure view-mode is Demo → Hard Delete (Demo) → Seed Demo.
*Why it matters:* the soft/hard delete operations are explicitly scoped to the current view mode partition; toggling first is the safety net.

### 6.4 Refresh real without losing demo

**Q.** I want a fresh real extract; keep the demo I configured for our sales deck.
*App page:* Toggle view-mode to Real → Hard Delete (Real) → Extract (Real).

---

## 7. Engine Switching

### 7.1 Switch to Spark JDBC views

**Q.** I want to use Spark as the query engine but keep data in Postgres.
*App page:* Data Management → Engine: select Spark → mode: JDBC views.
*Behind the scenes:* Spark builds TEMP VIEWs over Postgres via JDBC; queries flow Spark → JDBC → Postgres.
*Why it matters:* unlock Spark SQL syntax (window analytics, ARRAY/MAP, EXPLODE) without bulk-copying data. View-mode filter is baked into the JDBC `dbtable` query.

### 7.2 Switch to Spark materialized

**Q.** I want Spark to own the data (faster, but uses Spark warehouse).
*App page:* Data Management → Engine: Spark → mode: Materialized → click **Materialize Postgres → Spark**.
*Needs:* Spark Connect endpoint reachable; warehouse-dir writable.
*Why it matters:* highest performance for Spark-heavy questions; requires periodic re-materialize when Postgres changes.

### 7.3 Revert to DuckDB

**Q.** Spark Connect is down; I just want the app to keep working.
*App page:* Engine → DuckDB. (DuckDB attaches Postgres directly — no Spark dependency.)
*Why it matters:* the safe fallback. Most dashboards and the chatbot are DuckDB-fine.

---

## 8. RBAC / Access Management

### 8.1 Create a workspace-scoped role

**Q.** Give the FinOps team read-only access to only the prod workspace.
*App page:* Roles → Create → Filters: `{workspace_id: ["1111…"]}`, Features: `["ui.billing_explorer", "ui.query_profiler"]`.
*Behind the scenes:* every dashboard query has `WHERE workspace_id IN (...)` injected from the user's role filters.

### 8.2 Hide an entire surface from a role

**Q.** Hide the Chatbot from a "reader" role.
*App page:* Roles → Reader → Features: drop `ui.chatbot`.
*Behind the scenes:* sidebar entry hides; direct URL hit redirects to Dashboard.

### 8.3 Assign / unassign role to a user

**Q.** Add Alice to FinOps.
*App page:* Users → Alice → assign FinOps role.

### 8.4 Deactivate a user

**Q.** Disable Bob without deleting his audit trail.
*App page:* Users → Bob → toggle `is_active=false`.

---

## 9. Diagnostics / Forensics

### 9.1 Database Explorer

**Q.** Is there any data in `billing_usage` at all?
*App page:* Database Explorer → click `billing_usage` → see row count + a sample.

**Q.** Are there demo rows leaking into real view-mode?
*App page:* Database Explorer → run `SELECT data_origin, COUNT(*) FROM billing_usage GROUP BY 1;`. (View-mode toggle does NOT scope the Explorer — it shows raw Postgres state.)

### 9.2 Spark SQL Editor

**Q.** I want to test a window analytics query.
*App page:* Spark SQL Editor → run `WITH d AS (...) SELECT ... OVER (PARTITION BY ...) ...`.
*Needs:* engine == Spark; Spark Connect reachable.
*Behind the scenes:* TEMP VIEWs include `WHERE data_origin = '<mode>'` baked in, so the editor scopes to your current view mode.

### 9.3 Reset state

**Q.** Something's broken; I want to start over.
*Sequence:* Hard Delete (Real) → Hard Delete (Demo) → Seed Demo → restart browser.

---

## 10. Capacity / Performance

### 10.1 How big is the extract?

**Q.** How many rows per table after a full extract?
*App page:* Data Management → table-counts card.
*Why it matters:* `node_timeline` and `qi_statements` are the big ones; if they're an order of magnitude bigger than expected, your lookback window may be too generous.

### 10.2 Storage footprint

**Q.** How much disk is the operational warehouse using?
*App page:* (Not in UI yet — query Postgres directly.) `SELECT pg_total_relation_size('billing_usage')` etc.

### 10.3 Materialization runtime

**Q.** How long does `materialize-postgres-to-spark` take on a real extract?
*App page:* Notifications bell shows duration after completion.

---

## 11. Audit / Compliance

### 11.1 Who triggered the last extract?

**Q.** Who clicked Extract on Wednesday?
*App page:* Notifications bell → job history; cross-ref with the app's own audit trail (if enabled).

### 11.2 Demo-data certification

**Q.** Confirm there's no real catalog name in any demo row.
*App page:* Spark SQL Editor (or Database Explorer) → grep for `repassist|<known customer name>` across `data_origin='demo'` rows.

---

## 12. Cross-cutting

### 12.1 Extract → Transform → Surface flow

The data lifecycle in the app:

```
Databricks system.*  →  /api/admin/extract  →  parquet (data/*.parquet)
                                              ↓ ingest
                                       Postgres operational store
                                              ↓
                                  Query Engine (DuckDB | Spark)
                                              ↓
                                          Dashboards
```

For demo data:

```
data/demo_*.parquet  →  /api/admin/seed-demo  →  Postgres (data_origin='demo')
                                                ↓
                                       view-mode toggle filters
                                                ↓
                                            Dashboards
```

### 12.2 Lineage transform

`/api/admin/transform-lineage` is a **second-pass aggregation** that turns
raw `system.access.{table,column}_lineage` events into the rolled-up
`lineage_table_edges` / `lineage_column_edges` tables that the Meta
Explorer renders. Run it after extracting lineage groups.

---

## 13. Limitations & gotchas

- **Database Explorer is NOT scoped by view-mode** — it shows raw Postgres rows from every partition. Use the `data_origin` column to filter manually.
- **Spark SQL Editor IS scoped by view-mode** — temp views bake in `WHERE data_origin='<mode>'`.
- **Hard delete is irreversible** — there's no undelete; only re-ingest restores rows.
- **Soft delete is reversible** — `Restore` flips `deleted_at=NULL` for the chosen partition.
- **Engine switch is per-process, not per-user** — toggling affects every user in the deployment.
- **Cancel works between table-level batches** — a single long table extract can take a minute or two to honor the flag.
- **Feature flags affect direct URL hits** — disabled features 302 → Dashboard, not 404 (intentional, avoids leaking that the feature exists).
- **`AUTO_EXTRACT` env var is inert in this app** — the boot path no longer auto-extracts; first-time users start in Demo and run an explicit extract for Real.

---

## 14. How to add a new data-ops scenario

1. Identify whether it's **read** (Database Explorer / Spark SQL editor / a structured dashboard) or **write** (Data Management).
2. If write, decide whether it deserves a dedicated `/api/data-ops/*` endpoint or fits an existing one with a parameter.
3. If it's a recurring task, file a request to put it in the Data Management UI rather than asking users to hit endpoints directly.
4. Note the **safety story** — does it need view-mode scoping? a confirm dialog? a soft-then-hard delete sequence?

---

## See also

- `docs/USER_GUIDE.md` — end-user walkthrough of every page
- `docs/technical/QUERY_ENGINE.md` — engine switch details
- `docs/technical/SECURITY.md` — RBAC + filter scoping deep-dive
- `docs/features_grouped/AUDIT.md` — the audit ingestion side
- `deploy/PRODUCTION_CHECKLIST.md` — production deployment checklist
