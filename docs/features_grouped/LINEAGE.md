# Lineage — `system.access.table_lineage` + `column_lineage`

Authoritative Databricks reference:
[`docs.databricks.com/aws/en/admin/system-tables/lineage`](https://docs.databricks.com/aws/en/admin/system-tables/lineage)

This doc covers how the app ingests, stores, and surfaces Databricks' two
lineage system tables.

## Table of contents

- [What the data looks like](#what-the-data-looks-like)
- [Event classification](#event-classification)
- [The two dashboards](#the-two-dashboards)
- [Extraction — chunked, with separate windows](#extraction--chunked-with-separate-windows)
- [The `lineage_rollups` Transform job](#the-lineage_rollups-transform-job)
- [Postgres model](#postgres-model)
- [Common questions](#common-questions)

---

## What the data looks like

Each row in `system.access.table_lineage` is **one directed edge** that a
single Databricks statement contributed: a source table or path on one side,
a target table or path on the other, plus enough metadata to attribute it
back to a job, notebook, DLT pipeline, dashboard, or DBSQL query.

The full set of fields (mirrored 1:1 in our Postgres `table_lineage` model):

| Column | Notes |
|---|---|
| `account_id`, `metastore_id`, `workspace_id` | Owner identifiers. |
| `event_time`, `event_date` | UTC; `event_date` is partitioned upstream — we filter on it for chunking. |
| `record_id` | Per-row unique ID from Databricks. |
| `event_id` | Shared across rows that originated from the same statement (one query → many rows). |
| `source_table_full_name` + split `source_table_catalog` / `source_table_schema` / `source_table_name` | NULL when the read was against a path-style location (then `source_path` carries it). |
| `source_type` | Enum: `TABLE`, `PATH`, `VIEW`, `MATERIALIZED_VIEW`, `METRIC_VIEW`, `STREAMING_TABLE`. |
| `target_table_full_name` + split + `target_type` + `target_path` | Same shape on the write side. |
| `created_by` | User / principal / group / `"System-User"`. |
| `entity_type` | Enum: `NOTEBOOK`, `JOB`, `PIPELINE`, `DASHBOARD_V3`, `DBSQL_DASHBOARD` (deprecated), `DBSQL_QUERY`, or NULL when no Databricks entity (e.g., JDBC). |
| `entity_id`, `entity_run_id` | Stable IDs for grouping. |
| `entity_metadata` | STRUCT in Databricks; we store the JSON. Fields: `job_info{job_id, job_run_id}`, `dlt_pipeline_info{dlt_pipeline_id, dlt_update_id}`, `notebook_id`, `dashboard_id`, `legacy_dashboard_id`, `sql_query_id`, `genie_space_id`, `alert_id`. Multiple fields can be populated. |
| `statement_id` | FK to `system.query.history` for SQL warehouse queries — joinable with the Query Profiler. |
| `direct_access` | `true` = referenced directly by the statement; `false` = surfaced as a transitive dependency by lineage analysis. |

`system.access.column_lineage` adds:

| Column | Notes |
|---|---|
| `source_column_name`, `target_column_name` | Per-column edges. |

**Important Databricks-side caveat for column lineage**: events with no
source (e.g. `INSERT VALUES`) are dropped — they appear in `table_lineage`
as write-only rows but are absent from `column_lineage`. The Column
Lineage dashboard's tile counts therefore are **not** a strict subset of
the Table Lineage counts.

**Retention**: `system.access.*_lineage` keeps a rolling 1-year window.
Longer history is available via Catalog Explorer or the lineage API.

---

## Event classification

The Databricks contract uses source/target nullability to encode operation
type. The Lineage Tables dashboard surfaces this directly:

| source_table_full_name | target_table_full_name | Event class | Examples |
|---|---|---|---|
| NOT NULL | NULL     | `read_only`  | `SELECT * FROM x`, a dashboard read. |
| NULL     | NOT NULL | `write_only` | `INSERT VALUES` into a table. |
| NOT NULL | NOT NULL | `read_write` | The bulk of real lineage — any ETL. |

This is computed server-side in `/api/meta/lineage/stats` and shown as a
breakdown bar at the top of the Table Lineage dashboard.

---

## The two dashboards

`Meta Explorer → Lineage — Tables` and `Lineage — Columns` share the
`system.access.*_lineage` source but have different signal.

### Lineage — Tables (`/meta-explorer/lineage/tables`)

| Widget | What it tells you |
|---|---|
| **KPI tiles** | Total table edges, distinct tables, direct edges, indirect edges, distinct producers (entities). |
| **Event-class breakdown** | read-only vs write-only vs read-write distribution. |
| **By `entity_type`** | Are most edges produced by jobs? notebooks? DLT pipelines? Dashboards? |
| **By `source_type`** | What kind of objects feed downstream — TABLE vs VIEW vs STREAMING_TABLE etc. |
| **Top sources / Top targets / Top producers / Top column edges** | Click any row to re-centre the graph. |
| **Orphan tables** | Present in `databricks_meta` but never referenced in lineage — candidates for deletion. |
| **Terminal tables** | Appear as a target but never as a source — leaf nodes / dead-ends. |
| **`direct_access = true` filter** | Strip the graph to direct references only. |
| **Depth-1 SVG graph** | Centre table with upstream + downstream neighbours; click any neighbour to re-centre. |

### Lineage — Columns (`/meta-explorer/lineage/columns`)

| Widget | What it tells you |
|---|---|
| **KPI tiles** | Column edges, distinct columns, distinct contributing tables, distinct producers. |
| **Most-fanned-out columns** | Source columns whose value reaches the most distinct downstream (table, col) pairs — broadcast points. |
| **Most-depended-on columns** | Target columns with the most distinct upstream columns — fan-in hot spots / "everything ends up in this column". |
| **Tables by column edges** | Ranks data products by how many column-level edges they originate. |
| **Top producers (column-grain)** | Entities producing the most column edges. |
| **Depth-1 SVG graph** | Centre `(table, column)` with upstream + downstream column neighbours. |

Both pages share an SVG-based three-column graph (no external graph
library). Click any neighbour to re-centre. Depth > 1 is achieved by
re-centring, which keeps each request bounded.

---

## Extraction — chunked, with separate windows

Lineage tables are very high-volume on busy accounts — a 2-year
unbounded scan can return tens of millions of rows and OOM the extractor.
The extractor service handles this with three layers of safety:

1. **Off by default in the UI.** The `lineage` checkbox in
   `Admin → Data Management → Extract from Databricks` starts unchecked.
2. **Separate, much shorter windows per table.** When `lineage` is checked,
   the UI exposes two number inputs:
   - `table_lineage_days_back` (default **14**)
   - `column_lineage_days_back` (default **7**, tighter because it's
     typically 3-5× the volume of `table_lineage`)
3. **Weekly-chunked extraction.** `extractor/databricks_extractor.py`
   loops day-range by day-range (7-day chunks for `table_lineage`, 3-day
   chunks for `column_lineage`) and concatenates pandas DataFrames so
   each `.toPandas()` call stays bounded.

Per-table tolerated failure: if `system.access.*_lineage` isn't available
(some accounts don't have the access schema enabled), the extractor
logs a warning and continues — the other groups still succeed.

The flow end-to-end is:

```
Admin > Data Management > Extract from Databricks (lineage checked)
  -> extractor /extract endpoint
  -> _extract_lineage_chunked() per table, per week
  -> table_lineage_<date>.parquet, column_lineage_<date>.parquet
  -> backend ingest reads parquet, writes into `table_lineage` / `column_lineage`
  -> Lineage dashboards now have data for data_origin='real'
```

For demo: `scripts/simulate_demo_data.py` synthesises both tables from
the demo Unity Catalog tree. Topology is biased toward a medallion
bronze → silver → gold flow; the event-class mix is realistic
(~65% read-write, 25% read-only, 10% write-only). Every FQN in the
synthesised lineage resolves against `demo_databricks_meta` so joins
work.

---

## The `lineage_rollups` Transform job

`Admin → Data Management → Transform → Lineage rollups (real / demo)`
rebuilds the `lineage_rollups` cache table — one row per
`(data_origin, full_name)` with `edges_in`, `edges_out`,
`distinct_upstream`, `distinct_downstream`, `distinct_entities`,
`direct_edges`, `indirect_edges`, `last_event`. The current dashboards
read directly from `table_lineage` for accuracy; the rollup is a
forward-looking cache for instant tile rendering as the lineage
partition grows.

The job is idempotent — it wipes the partition for the selected
`data_origin` and rebuilds it from scratch. Progress is visible in the
Transform section's progress card, with phases:

1. Wipe previous `lineage_rollups` partition.
2. Aggregate source-side edges.
3. Aggregate target-side edges.
4. Build N rollup rows.
5. Commit and return summary.

---

## Postgres model

Defined in `backend/models.py`:

| Model | Postgres table | Notes |
|---|---|---|
| `TableLineage` | `table_lineage` | Full mirror of `system.access.table_lineage` plus `data_origin` / `deleted_at` for the data-isolation system. |
| `ColumnLineage` | `column_lineage` | Same with `source_column_name` / `target_column_name`. |
| `LineageRollup` | `lineage_rollups` | Materialised aggregates; rebuilt by the Transform job. |

All three carry `data_origin` (`'real'` or `'demo'`) and `deleted_at`,
participating in the standard data-isolation + soft-delete system —
the user's `viewing_data_mode` selects which partition they see.

---

## Common questions

**Q. The Lineage dashboards show 0 edges.**
- Check view-mode: top-right toggle (`real` vs `demo`).
- For demo: re-run `python scripts/simulate_demo_data.py` (it has to be
  recent enough to include the lineage transforms), then `LOAD →
  Load Demo Data (full)`.
- For real: `Extract from Databricks` with the `lineage` checkbox on,
  *or* `LOAD → Load Real Data (Parquet) (full)` if the lineage parquets
  already exist on disk.

**Q. The Column dashboard shows fewer edges than Table.**
- Expected. `system.access.column_lineage` excludes events with no
  source (e.g. `INSERT VALUES`), so write-only edges visible in
  Table Lineage are absent here.

**Q. What's the difference between `direct_access=true` and `false`?**
- `true`: the source/target was referenced directly by the statement.
- `false`: surfaced as an intermediate dependency by Databricks lineage
  analysis (e.g. a view's underlying table appears as indirect when
  someone queried the view).
- The Tables dashboard has a checkbox to filter on direct only.

**Q. How do I join lineage to a query?**
- Use `statement_id`. SQL warehouse queries are joinable with
  `query_history.statement_id`. The Chatbot and Query Profiler can
  pull both together.

**Q. Can I see lineage older than 1 year?**
- `system.access.*_lineage` is a 1-year rolling window. For longer
  history use Catalog Explorer or the Databricks lineage API — those
  retain indefinitely from 2024-09-01 onward.

**Q. Why is the extractor so picky about the time window?**
- `column_lineage` can be 100M+ rows on a busy account. A naïve
  `.toPandas()` over a wide window OOMs the driver. The chunked
  extraction + tighter default windows are the published-docs-aligned
  workaround.
