# Node Pool — `system.compute.*`

Authoritative Databricks reference:
- [`system.compute` schema overview](https://docs.databricks.com/aws/en/admin/system-tables/compute)

This doc covers how the app ingests, stores, and surfaces the cluster
utilization timeseries plus the warehouse / instance lifecycle events
and the cloud-SKU reference catalogs.

## Table of contents

- [What the data looks like](#what-the-data-looks-like)
- [The Node Pool dashboard](#the-node-pool-dashboard)
- [Extraction — chunked, days-back-bounded](#extraction--chunked-days-back-bounded)
- [Postgres model + Spark exposure](#postgres-model--spark-exposure)
- [Common questions](#common-questions)

---

## What the data looks like

The `node_pool` extraction group covers five tables, all from the
`system.compute` schema. Two of them are pure reference catalogs
(no date bound) and three are time-bounded telemetry / event streams.

### `node_timeline` (mirror of `system.compute.node_timeline`)

One row per **(instance_id, 1-minute window)**. The highest-cardinality
compute system table — a busy account easily produces tens of millions
of rows per day, so the extractor uses 3-day chunks and the JDBC reader
uses pushdown.

| Column | Notes |
|---|---|
| `account_id`, `workspace_id`, `cluster_id`, `instance_id` | Identifiers. `cluster_id` joins to `clusters` and to `billing_usage.cluster_id`. |
| `start_time`, `end_time`, `event_date` | UTC bounds of the 1-minute sample. `event_date` is pre-extracted `CAST(start_time AS DATE)` for dashboard partition filters. |
| `driver` | True for the cluster driver; False for workers. |
| `node_type` | VM SKU; joins to `node_types.node_type`. |
| `cpu_user_percent`, `cpu_system_percent`, `cpu_wait_percent` | 0–100. |
| `mem_used_percent`, `mem_swap_percent` | 0–100. |
| `network_sent_bytes`, `network_received_bytes` | Bytes during the 1-minute window. |
| `disk_free_bytes_per_mount_point` | Upstream `MAP<STRING, BIGINT>` stored as JSON. Mount path → free bytes. |

### `warehouse_events` (mirror of `system.compute.warehouse_events`)

One row per SQL warehouse state transition.

| Column | Notes |
|---|---|
| `warehouse_id` | Joins to `warehouses.warehouse_id` and `billing_usage.warehouse_id`. |
| `event_type` | `STARTING` / `RUNNING` / `STOPPING` / `STOPPED` / `SCALED_UP` / `SCALED_DOWN`. |
| `cluster_count` | Active backing-cluster count after this event. |
| `event_time`, `event_date` | UTC. |

### `node_types` (mirror of `system.compute.node_types`)

Reference catalog. Small (a few dozen rows per account); full-replaced
on every extract.

| Column | Notes |
|---|---|
| `node_type` | Cloud SKU label (e.g. `i3.xlarge`, `Standard_DS3_v2`). |
| `core_count` | vCPUs — decimal because fractional shares are possible on some serverless tiers. |
| `memory_mb` | Whole MB. |
| `gpu_count` | 0 for non-GPU SKUs. |
| `category` | `General Purpose` / `Memory Optimized` / `Compute Optimized` / `GPU` / `Storage Optimized`. |

### `instance_events` (mirror of `system.compute.node_events`)

> **Naming note.** The Databricks system-table is `node_events`. We
> surface it as `instance_events` throughout the app (parquet, Postgres,
> Spark temp view, chatbot, dashboard) to match the **"instance events"**
> panel name in the Databricks UI. The extractor's SELECT clause does
> the rename — there is no separate `node_events` table downstream.

One row per VM lifecycle event.

| Column | Notes |
|---|---|
| `cluster_id`, `instance_id` | Identifiers for the affected VM. |
| `instance_pool_id` | NULL when the VM was created outside any pool. |
| `event_type` | `NODE_ADD` / `NODE_TERMINATING` / `NODE_TERMINATED` / `SPOT_LOSS` / `RESIZED` / `DRIVER_HEALTHY` etc. |
| `event_time`, `event_date` | UTC. |
| `node_type` | VM SKU. |
| `event_details` | Upstream STRUCT payload stored as JSON. Shape varies by `event_type`. |

### `instance_pools` (mirror of `system.compute.instance_pools`)

Reference catalog of pooled-VM definitions.

| Column | Notes |
|---|---|
| `instance_pool_id` | Pool identifier; joins to `billing_usage.instance_pool_id` and `instance_events.instance_pool_id`. |
| `instance_pool_name` | Display name. |
| `node_type` | VM SKU for the pool. |
| `min_idle_instances`, `max_capacity` | Pool autoscaler bounds. |
| `idle_instance_autotermination_minutes` | How long an idle VM lingers before reclaim. |
| `enable_elastic_disk` | True when the pool's VMs auto-resize their local disk. |
| `preloaded_spark_versions` | Array of DBR versions pre-warmed on pool VMs, stored as JSON. |
| `create_time`, `delete_time`, `change_time` | UTC lifecycle timestamps. |

---

## The Node Pool dashboard

Lives at **Meta Explorer → Node Pool** (`/meta-explorer/node-pool`).

It surfaces:

- One **KPI tile per table** (row counts + last-seen timestamps).
- A counters strip showing distinct clusters / instances / warehouses /
  pools observed in the resident partition.
- Three **breakdown bars**: warehouse `event_type`, instance `event_type`,
  node-type `category`.
- **Cluster utilization** table — top clusters by node_timeline sample
  count with avg / max CPU and memory.
- **Recent warehouse events** and **recent instance events** tables.
- The full **node_types** and **instance_pools** reference catalogs.

The dashboard is view-mode-scoped — every endpoint filters
`data_origin = user.viewing_data_mode` AND `deleted_at IS NULL`, so
toggling REAL ↔ DEMO in the top-right cluster partitions the data
cleanly.

Empty? Extract with the `node_pool` group checked. Defaults: `node_timeline`
**3 days** (per-minute-per-instance — wider windows will OOM the Spark
Connect driver), `warehouse_events` **30 days**, `instance_events`
**14 days**. Or run the demo simulator and switch to demo view-mode.

---

## Extraction — chunked, per-table days-back-bounded

The `node_pool` extraction group covers all five tables. The two
reference catalogs (`node_types`, `instance_pools`) have **no date
bound** — they're one-shot SELECTs, full-replaced on every extract.

The three time-bounded tables each have their **own** lookback knob:

| Table | Window knob | Default | Chunk size | Why |
|---|---|---|---|---|
| `node_timeline`     | `node_timeline_days_back`     | **3 d**  | **3-day chunks** | per-minute × per-instance — by far the biggest. |
| `warehouse_events`  | `warehouse_events_days_back`  | **30 d** | 7-day chunks     | modest event volume. |
| `instance_events`   | `instance_events_days_back`   | **14 d** | 7-day chunks     | modest event volume. |

Each chunk's DataFrame is collected via Arrow and concatenated, mirroring
the audit / lineage chunking strategy. Bumping `node_timeline_days_back`
beyond ~7 days on a real Databricks account is risky on the default
driver heap — the Spark Connect process collects all chunks into Arrow
batches in JVM memory. `warehouse_events` and `instance_events` are
event logs and tolerate much wider windows comfortably.

Pushdown options enabled on the JDBC reader for downstream queries
(`pushDownPredicate`, `pushDownLimit`, `pushDownOffset`,
`pushDownAggregate`, `fetchsize=10000`) keep dashboard queries
bounded even on large partitions.

---

## Postgres model + Spark exposure

All five tables follow the same data-isolation pattern as the rest of
the project: `data_origin` (`'real'` / `'demo'`) + `deleted_at`
soft-delete tombstone. Both columns are indexed.

In **Spark** (`backend/spark_session.py`), all five are appended to
`_BASE_TABLES` so the JDBC temp views (or Delta-shadow views in
`materialized` mode) get registered with the view-mode filter baked
into the `.option("query", ...)` SQL.

The chatbot picks them up from `routers/chat_node_pool_schema.py`,
which mirrors `chat_audit_schema.py` — the LLM sees the time-window
warning on `node_timeline`, the event-type enums on warehouse +
instance events, and the foreign-key topology back to clusters /
warehouses / node_types.

---

## Common questions

**Q: My account doesn't have `system.compute.node_events`. Does the
extract fail?**
The extractor catches and logs the missing-table exception (same
tolerated-fail pattern as lineage/audit). `instance_events` will be
absent from that run's parquet output and from Postgres; everything
else still loads.

**Q: `instance_pools` skipped with `[INSUFFICIENT_PERMISSIONS]`?**
`system.compute.instance_pools` is not granted to all principals by
default. From an account-admin role in Databricks:

```sql
GRANT SELECT ON TABLE system.compute.instance_pools TO `<your-service-principal>`;
```

The extractor's tolerated-fail wrapper logs the skip and carries on,
so the rest of the `node_pool` group still loads. The `instance_pools`
table in Postgres will simply stay empty (or hold its previous demo
partition) until the grant is in place.

**Q: `node_types.category` is always NULL on real data — is that a bug?**
No — the public `system.compute.node_types` schema today is just
`{account_id, node_type, core_count, memory_mb, gpu_count}`. The
`category` column does NOT exist upstream. The extractor SELECTs a
NULL placeholder so the parquet column survives the round-trip; demo
data populates `category` directly. If Databricks adds the column,
swap the placeholder back to a real reference.

**Q: How do I get longer history without OOMing?**
Don't bump `node_timeline_days_back` past ~7 on a real account
(`warehouse_events` / `instance_events` are safer to widen — they're
event logs). Instead, run multiple incremental extracts on overlapping
windows — the upstream `system.compute.*` tables retain at least 365
days, so you can backfill in chunks. For very deep history,
materialize the in-Postgres Delta and query historical Delta
partitions directly via the Spark SQL Editor.

**Q: Why does the dashboard show `instance_events` but the system-table
docs only list `node_events`?**
Naming choice — see the "Naming note" above. The data is one and the
same; the SELECT renames it.
