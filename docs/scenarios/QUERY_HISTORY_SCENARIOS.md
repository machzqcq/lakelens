# Query History — Enterprise Scenarios & Questions

A field guide to what every department in a large enterprise can learn from
`system.query.history`. Each scenario lists the **question**, the **role**
asking it, and the **columns / joins** needed so an agentic system on top
of this table knows where to look.

The catalog is grouped by role so a business user can jump straight to
"Executive", a platform engineer to "IT / Platform", and so on. A final
section lists cross-cutting questions that involve multiple roles
collaborating on the same query.

---

## 0. Which app pages back these scenarios

| App page (sidebar path) | What it answers | Backed by |
|---|---|---|
| **Query Profiler → Overview** | KPI strip (statements, distinct users, success rate, p50/p95 duration, cache-hit rate, serverless share, AI / dashboard / job / notebook query counts), last-extract metadata. | `qi_statements`, `qi_statement_*` derived tables |
| **Query Profiler → Platform / IT Admin** | Expensive queries, full scans, spill leaders, error trends, error categories, capacity / queueing, cache effectiveness. | `qi_statements`, `qi_statement_errors` |
| **Query Profiler → Catalog Usage** | Top referenced tables, top referenced columns, partitioning candidates, zombie tables. | `qi_statement_tables`, `qi_statement_columns` |
| **Query Profiler → FinOps** | Tag coverage, failed-query cost, source-app attribution, project / keyword fuzzy-search. | `qi_statements`, `qi_statement_tags` |
| **Query Profiler → Executive** | Adoption trend (distinct users / dashboards / jobs / notebooks / Genie spaces, monthly), executive serverless share, reliability KPI (success-rate, p95-duration, queue-p95). All three charts share a date-range + grain picker. | `qi_statements`, `qi_statement_sources` |
| **Query Profiler → Data Engineering** | Job failure rates, slowest pipelines, compile-heavy queries. | `qi_statements` × `qi_statement_sources.job_*`/`pipeline_*` |
| **Query Profiler → BI / Analytics** | Slowest dashboards, BI-vendor footprint, `SELECT *` dashboards. | `qi_statements` × `qi_statement_sources.dashboard_id` |
| **Query Profiler → Data Science** | Notebook activity (users × notebook count × dbus), Genie adoption (daily). | `qi_statements` × `qi_statement_sources.notebook_id`, `assistant_events` |
| **Query Profiler → Security & Governance** | Permission denied, off-hours PII reads, bulk export, grant / revoke, driver versions, delegated execution (`executed_as`). | `qi_statements`, `qi_statement_errors`, `qi_statement_tables` |
| **Query Profiler → Developer Experience** | User footprint, tool mix (DBSQL / NOTEBOOK / JOB / GENIE / API), syntax-error leaders. | `qi_statements`, `qi_statement_errors` |
| **Query Profiler → Cross-cutting** | SQL feature mix (join / cte / window / array / json / struct / explode), hour-of-day pattern, duplicate-query fingerprints, statement-type mix. | `qi_statements` |

Endpoints live under `/api/query-intel/*` — see `backend/routers/query_intel.py`.

---

## 1. Why this table is a goldmine

`query_history` is the only place where every interaction with the
Databricks lakehouse is recorded with full attribution and resource
accounting. It is simultaneously:

- A **billing-attribution ledger** (who ran what, for how long, on which compute)
- A **performance log** (latency, spill, shuffle, cache hits, files pruned)
- A **governance trail** (who tried to access what, what was denied)
- A **product analytics stream** for the data platform itself (dashboard
  use, notebook use, BI-tool use, Genie / AI use)

When flattened (statement_text parsed, query_tags exploded, query_source
expanded into job_id / dashboard_id / notebook_id / pipeline_id / sql_query_id /
genie_space_id / alert_id, and JOINed with `clusters`, `warehouses`,
`jobs`, `workspaces`, `list_prices` and `billing_usage`), it answers
~90% of the questions any role in the org could possibly ask about the
data platform.

---

## 2. Column cheat sheet

A condensed map of what each column is good for. Full descriptions live
in `consolidated_metadata_with_descriptions.xlsx`.

| Bucket | Columns | Lets you answer |
|---|---|---|
| **Identity** | `account_id`, `workspace_id`, `executed_by`, `executed_by_user_id`, `executed_as`, `executed_as_user_id`, `session_id` | Who ran this, under whose identity, in which workspace |
| **Compute** | `compute.type` (`WAREHOUSE` vs `SERVERLESS_COMPUTE`), `compute.warehouse_id`, `compute.cluster_id` | Which engine ran it; lets you join to `warehouses` / `clusters` / `billing_usage` to attach cost |
| **What ran** | `statement_id`, `statement_text`, `statement_type` (SELECT/MERGE/CREATE/DESCRIBE/…), `cache_origin_statement_id`, `query_parameters` (parameterized values), `query_tags` (project/team/env labels) | The actual workload; tables, columns, joins, predicates after parsing |
| **Outcome** | `execution_status` (FINISHED / FAILED / CANCELED), `error_message` | Success/failure, error patterns |
| **Source / trigger** | `query_source.job_info.{job_id, job_run_id, job_task_run_id}`, `query_source.pipeline_info.{pipeline_id, update_id}`, `query_source.notebook_id`, `query_source.dashboard_id`, `query_source.alert_id`, `query_source.sql_query_id`, `query_source.genie_space_id` | What entity in the platform triggered the query — gives you natural roll-ups by dashboard, job, pipeline, notebook, alert, AI-Genie session |
| **Client** | `client_application` (Databricks SQL Editor / Notebooks / Jobs / PowerBI / Tableau / SAS / CData / JDBC / ODBC / SQL Connector versions), `client_driver` (exact driver + version) | Who connects how — drives connector security patching, BI footprint, vendor mix |
| **Latency breakdown** | `total_duration_ms`, `waiting_for_compute_duration_ms`, `waiting_at_capacity_duration_ms`, `compilation_duration_ms`, `execution_duration_ms`, `total_task_duration_ms`, `result_fetch_duration_ms` | End-to-end SLA, queueing, planning, raw execution, client fetch — diagnose where time is spent |
| **I/O — read side** | `read_partitions`, `read_files`, `pruned_files`, `read_rows`, `read_bytes`, `pruned_files_bytes`, `read_files_bytes`, `read_io_cache_percent`, `from_result_cache` | Partition-pruning effectiveness, file-skipping, scan size, cache effectiveness |
| **I/O — write & shuffle** | `produced_rows`, `written_rows`, `written_files`, `written_bytes`, `shuffle_read_bytes`, `spilled_local_bytes` | Write throughput, shuffle volume, memory pressure |
| **Time** | `start_time`, `end_time`, `update_time` | Business-hours vs off-hours, time-series rollups |

---

## 3. How to read the scenarios

Each scenario has the form:

> **Q.** The question, phrased the way the persona would ask it.
> *Needs:* columns / joins required.
> *Why it matters:* what the answer changes.

For complex scenarios, an example SQL skeleton is included so the
agentic system has a known-good template to imitate.

---

## 4. IT / Platform / Lakehouse Admin

The person on-call when "the platform is slow." Cares about reliability,
capacity, hot-spots, and bad SQL patterns.

### 4.1 Hot-spots and bad-actor queries

**Q.** What are the 50 most expensive queries in the last 7 days, and who wrote them?
*Needs:* `executed_by`, `statement_text`, `total_duration_ms`, `read_bytes`, `shuffle_read_bytes`, `spilled_local_bytes`, `compute.warehouse_id` → `warehouses.warehouse_name`.
*Why it matters:* Pareto rule — 1% of queries usually drive 50%+ of cost.

**Q.** Show me queries that scanned more than 100 GB but returned fewer than 1,000 rows.
*Needs:* `read_bytes`, `produced_rows`, `statement_text`.
*Why it matters:* Classic missing-WHERE-clause or full-table-scan smell — a coachable conversation with the author.

**Q.** Which users have the highest spill-to-disk volume this month, and what queries spilled?
*Needs:* `spilled_local_bytes`, `executed_by`, `statement_text`, `start_time`.
*Why it matters:* Spills mean undersized warehouses or pathological joins.

**Q.** What queries failed because of `INSUFFICIENT_PERMISSIONS` and who needs access?
*Needs:* `error_message LIKE '%INSUFFICIENT_PERMISSIONS%'`, `executed_by`, `statement_text`.
*Why it matters:* Recurring permission errors are a Unity Catalog hygiene backlog.

**Q.** What error patterns are growing week over week?
*Needs:* `error_message` (cluster on patterns: `OUT_OF_MEMORY`, `TASK_NOT_SERIALIZABLE`, `PARSE_SYNTAX_ERROR`, …), `start_time`, `execution_status='FAILED'`.

### 4.2 Catalog usage — by table, column, user

**Q.** Which tables are read the most across the platform, by user, by workspace?
*Needs:* parsed `statement_text` → table list; `executed_by`, `workspace_id`, `read_bytes`.
*Why it matters:* Tells you where to invest in optimization, partitioning, materialized views, and where to retire unused tables.

**Q.** Which columns are most frequently referenced in WHERE / JOIN / GROUP BY?
*Needs:* parsed `statement_text` → predicate columns.
*Why it matters:* Drives partitioning, clustering, Z-ORDER, and statistics decisions.

**Q.** Which tables would benefit most from partitioning or liquid clustering, and why?
*Needs:* `read_files`, `pruned_files`, `read_files_bytes`, `pruned_files_bytes`, statement_text → predicate columns. Compute `pruned / (read + pruned)` per table — low ratio = scanning too much.

**Q.** Which tables are NEVER read but are still being written to?
*Needs:* parsed `statement_text` (INSERT/MERGE/REPLACE write side vs SELECT read side).
*Why it matters:* Zombie tables → storage spend with no business value.

**Q.** Top 20 (table, column) pairs by query frequency.
*Needs:* parsed statement_text.

### 4.3 Capacity planning

**Q.** When do warehouses spend the most time queueing (`waiting_at_capacity_duration_ms > 0`), and which warehouse?
*Needs:* `waiting_at_capacity_duration_ms`, `compute.warehouse_id` → `warehouses.warehouse_name`, `start_time` (hour-of-day rollup).
*Why it matters:* Signal to upsize, add scaling clusters, or shift scheduled jobs.

**Q.** Cold-start latency: median `waiting_for_compute_duration_ms` for the first query of each session.
*Needs:* `waiting_for_compute_duration_ms`, `session_id`, `start_time` (first-query-per-session).
*Why it matters:* If users wait 30s+ before their first query runs, they hate the platform.

**Q.** Serverless vs Pro vs Classic warehouse — average duration and cost per query type.
*Needs:* `compute.warehouse_id` → `warehouses.warehouse_type`, `total_duration_ms`, JOIN to `billing_usage` for $.

### 4.4 Result cache effectiveness

**Q.** What % of dashboard queries hit the result cache? Per dashboard.
*Needs:* `from_result_cache`, `query_source.dashboard_id`.
*Why it matters:* Cold cache = wasted spend on repeated identical queries.

**Q.** Which dashboards would benefit from longer cache TTL?
*Needs:* `from_result_cache`, `query_source.dashboard_id`, `cache_origin_statement_id`, time between identical statements.

### 4.5 Notebook & ad-hoc patterns

**Q.** Which notebooks generate the most failed queries, and what's the typical error?
*Needs:* `query_source.notebook_id`, `execution_status='FAILED'`, `error_message`.

**Q.** Notebooks with the most expensive DESCRIBE / SHOW pattern (catalog-crawling).
*Needs:* `statement_type IN ('DESCRIBE','SHOW')`, `query_source.notebook_id`. Catalog Explorer and bots can issue 100s of DESCRIBEs per minute.

---

## 5. FinOps / Cost Engineering

Owns cloud spend, chargeback, and rightsizing. Lives in `usage_usd` joined
to query history.

### 5.1 Attribution & chargeback

**Q.** Cost per (project tag, environment) over the last quarter.
*Needs:* `query_tags` (flattened), JOIN to `billing_usage` via `compute.warehouse_id` / `cluster_id` + time window.
*Why it matters:* Untagged spend can't be charged back. This identifies the gap.

**Q.** What % of total spend is on queries that have no `query_tags` at all?
*Needs:* `query_tags IS NULL OR query_tags = {}`, joined cost.
*Why it matters:* The "untagged tax" — pushes a policy of mandatory tagging.

**Q.** Cost per dashboard for the top 100 most-viewed dashboards.
*Needs:* `query_source.dashboard_id` → external lookup, joined `billing_usage`.

**Q.** Cost per Databricks Job (`job_id`) and per task — which jobs are runaway?
*Needs:* `query_source.job_info.job_id`, `job_info.job_run_id`, joined to `billing_usage` and `jobs.name`.

**Q.** Cost of FAILED queries this month — dollars that produced zero business value.
*Needs:* `execution_status='FAILED'`, JOIN to cost.
*Why it matters:* Often 5–15% of spend. Tells you where retries / circuit-breakers are needed.

**Q.** Cost of result_cache=False queries that have an obvious cacheable identical predecessor.
*Needs:* `cache_origin_statement_id`, `from_result_cache=False` on subsequent identical statement_text.

### 5.2 Rightsizing & elasticity

**Q.** What warehouses are over-provisioned? (Low % time at >50% utilization, low spill.)
*Needs:* per-warehouse aggregates of `total_task_duration_ms`, `spilled_local_bytes`, `waiting_at_capacity_duration_ms`, joined warehouse size.

**Q.** What warehouses are under-provisioned? (High wait time, high spill.)
*Needs:* mirror of above.

**Q.** What's the marginal cost of moving X workload from Pro warehouse to Serverless? (Or vice versa.)
*Needs:* `compute.type`, `total_duration_ms`, joined `list_prices` for both options.

### 5.3 Project / executive attribution

**Q.** Given the project name "<X>" (a keyword for an LLM to search), what is total cost YTD, QTD, MTD? YoY delta?
*Needs:* fuzzy match across `query_tags`, `statement_text` (e.g. table names containing project), `query_source.job_info.job_id` → `jobs.name`, `query_source.dashboard_id` → dashboard name, joined cost. Time bucketing on `start_time`.
*Why it matters:* The headline question for any cost review with executives.

**Q.** Top 10 cost centers / departments by spend this quarter.
*Needs:* `query_tags.cost_center` or `query_tags.team` (org-specific tag conventions), joined cost.

---

## 6. Executive Leadership

Looks at trends, ROI, and risk indicators. Needs the same data
FinOps has, but rolled up to 2–3 numbers per slide.

**Q.** Total platform cost MoM, QoQ, YoY — broken down by Business Unit.
*Needs:* `query_tags.bu` (or workspace-to-BU mapping table), joined cost, `start_time` aggregation.

**Q.** Adoption: how many distinct users, dashboards, jobs, notebooks ran a query this month? Trend vs last 12 months.
*Needs:* distinct counts of `executed_by`, `query_source.dashboard_id`, `query_source.job_info.job_id`, `query_source.notebook_id`, grouped by month(`start_time`).

**Q.** What share of the platform is now Serverless vs classic compute? Cost share, query share, latency comparison.
*Needs:* `compute.type` aggregates + cost.

**Q.** What's our "AI adoption" trend? (Genie / AI/BI queries.)
*Needs:* `query_source.genie_space_id IS NOT NULL` over time.
*Why it matters:* This is what every board deck asks about right now.

**Q.** Reliability KPI: query success rate over time, by workspace, by tier.
*Needs:* `execution_status`, time bucketing.

**Q.** Performance KPI: p50 / p95 / p99 dashboard query latency, monthly.
*Needs:* percentiles on `total_duration_ms` filtered by `query_source.dashboard_id IS NOT NULL`.

---

## 7. Data Engineering

Owns pipelines, jobs, DLT, and the ETL backbone.

### 7.1 Pipeline / Job health

**Q.** Which jobs have the highest failure rate this month?
*Needs:* `query_source.job_info.job_id`, `execution_status`, grouped over `start_time`.

**Q.** Which task within a multi-task job is the bottleneck?
*Needs:* `query_source.job_info.job_id` + `job_task_run_id`, `total_duration_ms`.

**Q.** Which DLT pipelines run longer than expected? Detect drift.
*Needs:* `query_source.pipeline_info.pipeline_id`, `start_time`, `total_duration_ms`. Compare each `update_id` to rolling median.

**Q.** When does a pipeline produce an unexpected row-count delta (`produced_rows` outlier)?
*Needs:* `produced_rows` over time per pipeline_id — anomaly detection.

**Q.** Backfill detector: spike in `written_rows` and `written_bytes` for a specific table relative to typical daily volume.
*Needs:* parsed `statement_text` (target table), `written_rows`, `written_bytes`, `start_time`.

### 7.2 SLA & latency budgets

**Q.** Which jobs missed their internal SLA (e.g. > 60 min) this month, and what's the long-pole task?
*Needs:* `query_source.job_info.job_id`, `total_duration_ms` aggregated per run.

**Q.** How much of a slow job's time is waiting for compute vs actual execution?
*Needs:* `waiting_for_compute_duration_ms` vs `execution_duration_ms` vs `total_task_duration_ms`.

### 7.3 Code quality

**Q.** Identify pipelines doing repeated identical queries that could be folded into a single batch.
*Needs:* clustering identical `statement_text` per pipeline_id / run.

**Q.** Pipelines where `compilation_duration_ms` > 25% of total — too much planning overhead, likely huge dynamic SQL.
*Needs:* `compilation_duration_ms`, `total_duration_ms`.

---

## 8. Analytics Engineering / dbt-style teams

The team that owns the modelling layer (silver / gold).

**Q.** Which models (MERGE / REPLACE statements against a target table) are the slowest?
*Needs:* `statement_type IN ('MERGE','REPLACE','INSERT')`, parsed target table, `total_duration_ms`.

**Q.** What's the read-to-build ratio for each gold table? (How often is it queried vs how often it's rebuilt?)
*Needs:* parsed `statement_text` for SELECT vs MERGE/REPLACE on the same table.
*Why it matters:* High build / low read = candidate for retirement or for moving to materialized view.

**Q.** Incremental vs full-refresh ratio per model. Flag models that always do full refresh and are growing.
*Needs:* `read_bytes` trend per model run; correlate with `written_bytes`.

**Q.** Test coverage proxy: which models have at least one downstream `DESCRIBE` / row-count check in the same day they were rebuilt?
*Needs:* statement_text patterns.

**Q.** Slowest-growing tables (rolling `written_bytes` per day).
*Needs:* `written_bytes`, parsed target table, `start_time`.

---

## 9. BI / Analytics

Owns dashboards, scheduled reports, and BI tooling (PowerBI, Tableau, SQL Dashboard).

**Q.** Slowest dashboards by p95 query latency — these are the ones executives wait on.
*Needs:* `query_source.dashboard_id`, percentiles on `total_duration_ms`.

**Q.** Dashboards with no views in 60+ days. (Candidate for retirement.)
*Needs:* `query_source.dashboard_id`, `max(start_time)` per dashboard.

**Q.** Which dashboards still hit `Databricks SQL Dashboard` (legacy) vs AI/BI Dashboards?
*Needs:* `client_application` mix per `query_source.dashboard_id`.

**Q.** Per BI tool footprint: PowerBI vs Tableau vs SQL Editor vs Notebook — query count, cost, p95 latency.
*Needs:* `client_application` rollup.

**Q.** Tableau LiveConnect vs Extract — which models are running ad-hoc heavy SELECTs vs daily refreshes?
*Needs:* `client_application='Tableau'`, frequency analysis per target table.

**Q.** Dashboards whose underlying SQL has `SELECT *` — code-review backlog.
*Needs:* parsed `statement_text`.

**Q.** Alerts (`query_source.alert_id`) that fire frequently and may be noisy.
*Needs:* `alert_id`, count per time window.

---

## 10. Data Science / ML

Notebooks-heavy workflow. Cares about iteration loop time.

**Q.** Per-notebook iteration velocity: median time between consecutive queries in the same `session_id`.
*Needs:* `session_id`, `start_time` deltas, `query_source.notebook_id`.

**Q.** Notebooks whose median query latency went up significantly month-over-month — DS productivity regression signal.
*Needs:* `query_source.notebook_id`, `total_duration_ms`, monthly aggregates.

**Q.** Feature store / training queries: which tables are read for ML (heuristic on table name pattern, e.g. `feature_*`, `train_*`).
*Needs:* parsed `statement_text`.

**Q.** Genie / AI-Assist adoption per team — how many distinct users used a Genie space this month?
*Needs:* `query_source.genie_space_id`, `executed_by`.

**Q.** Cost of AI-assist queries vs hand-written queries — premium worth paying?
*Needs:* `genie_space_id IS NOT NULL` vs IS NULL, joined cost.

---

## 11. Security / Governance / Compliance

Owns Unity Catalog policy, audit response, and PII handling.

### 11.1 Access patterns & policy violations

**Q.** Permission-denied trail: who got denied access to what, when?
*Needs:* `error_message LIKE '%INSUFFICIENT_PERMISSIONS%'`, `executed_by`, parsed `statement_text` (target object).

**Q.** Service principal vs human user activity — when does `executed_as != executed_by` (delegation / on-behalf-of)?
*Needs:* `executed_by_user_id`, `executed_as_user_id`. Useful for OAuth flow audit.

**Q.** Off-hours human access to sensitive tables (PII).
*Needs:* `start_time` outside business hours, `executed_by` flagged as human (not SP), parsed `statement_text` containing flagged tables.

**Q.** Bulk-export detection — single user reading > N rows / bytes in a session.
*Needs:* `read_rows` or `read_bytes` aggregated per `executed_by` + `session_id`.

**Q.** GRANT / REVOKE storms — who changed permissions and when?
*Needs:* `statement_type='GRANT'` (and revoke patterns), `executed_by`, `statement_text`.

**Q.** Cross-workspace data movement — same user querying multiple workspaces in the same hour.
*Needs:* `workspace_id` distinct count per `executed_by` per time bucket.

### 11.2 Connector / driver compliance

**Q.** Are any clients using outdated SQL connector / driver versions with known CVEs?
*Needs:* `client_driver` versions, joined to a vulnerability allowlist.

**Q.** Anonymous / `unknown` client_application connections — should be locked down?
*Needs:* `client_application IN ('unknown', NULL, '')`.

### 11.3 Insider-threat / anomaly

**Q.** Users whose query volume is > 5σ above their personal 30-day baseline.
*Needs:* per-user rolling baseline of query count, bytes read.

**Q.** Users running `SELECT *` against PII tables more than usual.
*Needs:* parsed statement_text, target-table flag list.

### 11.4 SQL injection / unsafe patterns

**Q.** Find statements that look like dynamically-built SQL with un-parameterized literals near auth-relevant tables.
*Needs:* parsed `statement_text`, comparison with `query_parameters` (if non-null → parameterized; if null and risky pattern → flag).

---

## 12. Application / Service Owners

Each team that owns a backend service that issues SQL to the lakehouse.

**Q.** Per-application error rate — does my service generate more failed queries than the median?
*Needs:* `client_application`, `execution_status`.

**Q.** Per-application p95 latency this week vs last week. Regression alarm.
*Needs:* `client_application`, percentile of `total_duration_ms`.

**Q.** What versions of the SQL connector are my apps using? Push for a version-bump.
*Needs:* `client_application`, `client_driver`.

**Q.** Are my connection pools efficient? How many sessions per app, queries per session?
*Needs:* `client_application`, `session_id` counts, queries-per-session histogram.

**Q.** Result-fetch latency outliers — is the slow part on the wire, not the warehouse?
*Needs:* `result_fetch_duration_ms` vs `execution_duration_ms`.

---

## 13. Data Product Owners

Each "data product" (e.g. `customer_360`, `revenue_marts`) needs its own metrics.

**Q.** Monthly Active Consumers (MAC) of the product — unique users reading any of its tables.
*Needs:* parsed `statement_text`, product table list, distinct `executed_by`.

**Q.** Top consuming dashboards, jobs, notebooks for the product.
*Needs:* parsed statement_text + `query_source.*`.

**Q.** Average freshness latency consumers see (time between last write to product table and the next read).
*Needs:* paired MERGE/INSERT vs SELECT on the same table.

**Q.** Cost per active consumer — does this product's value justify its cost?
*Needs:* spend rollup per product / MAC.

**Q.** Adoption growth — new users per week.
*Needs:* first-read date per `executed_by` per product table.

---

## 14. Engineering Productivity / Developer Experience

How happy are the people who use the platform daily?

**Q.** Median time-to-first-query for new employees.
*Needs:* `executed_by`, joined HR onboarding date — proxy: first `start_time` per `executed_by`.

**Q.** Tooling mix per developer — does the org prefer SQL Editor, Notebooks, or external IDEs?
*Needs:* `executed_by` × `client_application`.

**Q.** Frequency of `PARSE_SYNTAX_ERROR` / `UNRESOLVED_COLUMN` errors — pain proxy.
*Needs:* `error_message` patterns.

**Q.** Median session length — proxy for engagement.
*Needs:* `session_id`, `start_time`, `end_time` span.

**Q.** Adoption of parameterized queries vs string-built SQL.
*Needs:* `query_parameters IS NOT NULL` ratio per app / per user.

---

## 15. Audit / Internal Risk

Once-a-year deep-dives and regulator-facing answers.

**Q.** Reconstruct everything a specific user did in a specific window — full audit trail.
*Needs:* `executed_by`, `start_time` range, `statement_text`, `statement_type`, `execution_status`, target objects from parsed text.

**Q.** Privileged access review — list of statements executed as service principal X.
*Needs:* `executed_as`, `executed_as_user_id`.

**Q.** Retention compliance — confirm `statement_text` for queries against regulated tables is preserved per policy.
*Needs:* parsed target table flag list, `statement_text NOT NULL`.

**Q.** Data egress events — queries that wrote outside the lakehouse boundary (e.g. `INSERT OVERWRITE DIRECTORY '<external>'`).
*Needs:* parsed `statement_text` for external-write patterns.

---

## 16. Procurement / Vendor Management

Negotiating with Databricks, Microsoft, AWS, BI vendors.

**Q.** True footprint per BI vendor — query count, distinct users, cost attributable.
*Needs:* `client_application` filter + joined cost.

**Q.** Migration leverage — what would it cost to move all Tableau usage to PowerBI?
*Needs:* `client_application='Tableau'` cost share + dashboards involved.

**Q.** Serverless commitment / DBCU forecast — extrapolate Serverless DBU consumption.
*Needs:* `compute.type='SERVERLESS_COMPUTE'`, joined cost, time-series projection.

---

## 17. Cross-cutting — questions that involve multiple roles

These are the questions that always end with "let me bring in <other team>."

**Q.** **Pipeline cost vs business outcome** — for job X, what dashboards / consumers downstream rely on its output, and what's the total cost-per-business-decision?
*Needs:* `query_source.job_info.job_id` (write side), then read-side `executed_by` / `dashboard_id` against the same target tables. (FinOps + Data Engineering + Product Owners)

**Q.** **Failed-query blast radius** — for a frequently failing query, what dashboards / jobs / users are downstream?
*Needs:* read/write graph from `statement_text`, `execution_status='FAILED'`. (IT + Data Engineering + BI)

**Q.** **Migration readiness** — if we deprecate table T, who breaks?
*Needs:* parsed `statement_text` references to T, `executed_by`, `query_source.*`. (Data Engineering + Governance + Product Owners)

**Q.** **The "Project Greenlight" review** — given a project keyword, return: total cost, top 5 contributors, top 5 tables, top 5 dashboards, failure rate, user count, AI/Genie adoption %.
*Needs:* fuzzy keyword search across `query_tags`, table names in `statement_text`, dashboard names, job names. Roll up cost + counts + percentages. (Executive + FinOps + Product Owners)

**Q.** **The "hidden TCO of an analyst"** — for analyst U, sum: all queries they ran (cost), all dashboards they author (cost of dashboard refreshes), all notebooks they own (cost of all their queries). What does U really cost?
*Needs:* `executed_by`, `query_source.dashboard_id` and `query_source.notebook_id` ownership joins.

**Q.** **Compliance + cost** — for tables flagged as PII, how much is being spent querying them per month, by whom, and how many were access-denied?
*Needs:* PII flag list, parsed statement_text, joined cost, `INSUFFICIENT_PERMISSIONS` count.

---

## 18. Joinable enrichments

These tables (already in this app's database) flesh out the answers:

| Join from | Join to | Adds |
|---|---|---|
| `compute.warehouse_id` | `warehouses` | Warehouse name, size, type (serverless / pro / classic), creator, change history |
| `compute.cluster_id` | `clusters` | Cluster name, owner, DBR version, autoscale config, node types |
| `query_source.job_info.job_id` | `jobs` | Job name, creator, run_as, deletion status |
| `workspace_id` | `workspaces` | Workspace name, URL, status, create_time |
| `executed_by_user_id` / `executed_as_user_id` | external HR / IdP table | Department, manager, role |
| (compute attribution + time window) | `billing_usage` | Actual $ spent in the bracket the query ran in |
| (compute attribution) | `list_prices` | Per-DBU rate for cost calc |

The agent should also expect future enrichment from:

- A flattened table-references table derived from parsed `statement_text`
  (one row per `(statement_id, catalog, schema, table, column, role)` —
  where `role` is `read` / `write` / `predicate` / `groupby`).
- A flattened `query_tags` table (one row per `(statement_id, tag_key, tag_value)`).
- A flattened `query_parameters` table (one row per `(statement_id,
  parameter_name, parameter_value)`) — the Spark AST in this column
  hides parameter values like `accountname`, `attendanceflag`, etc.,
  which are gold for project attribution.

---

## 19. Limitations & gotchas the agent should know

- **`statement_text` is truncated** at the Databricks SDK boundary for
  very large queries. Counts based on text patterns will undercount the
  longest queries.
- **`compute.cluster_id` is null for warehouse queries** and vice versa —
  always check `compute.type` before joining.
- **`from_result_cache=True` rows have zero `read_bytes` / `read_files`** —
  exclude them from scan-size analyses or you'll bias the answer.
- **`execution_status='CANCELED'` queries still consumed compute** up
  to the cancellation point — include them in cost analyses, exclude
  from latency SLAs.
- **Many `client_application` values are `None` or empty** (~12% of
  rows) — treat as "Unknown" rather than dropping.
- **`query_parameters` is a deeply nested Spark AST.** Flatten it before
  asking parameter-name questions; don't try to grep the raw struct.
- **`query_tags` is an open schema** — the org needs a tagging policy
  (cost_center, project, environment, team) for the FinOps and
  Executive scenarios to work end-to-end.
- **`executed_by` is the principal that originated the request**;
  `executed_as` is the principal whose privileges the engine evaluated
  against. They differ on OAuth-on-behalf-of, dashboards run as owner,
  service-principal delegation. For "who did what" use `executed_by`;
  for "what permissions were checked" use `executed_as`.

---

## 20. How to add a new scenario

When a new question comes up:

1. Identify the **role / persona** asking it — slot it into the right section.
2. Phrase the question the way the persona would say it out loud.
3. List the **minimum columns** required and any **joins**.
4. If the answer needs parsed statement_text or flattened tags /
   parameters, note that explicitly so the agentic system knows to call
   the flattener first.
5. Include an **example SQL skeleton** when the agent might otherwise
   produce something wrong (e.g. forgetting to exclude
   `from_result_cache=True` from scan analyses).

---

## See also

- [`BILLING_SCENARIOS.md`](BILLING_SCENARIOS.md) — cost-side companion (cost per query / dashboard / job)
- [`AUDIT_SCENARIOS.md`](AUDIT_SCENARIOS.md) — access-side companion (control-plane actions, denials)
- [`DBX_META_SCENARIOS.md`](DBX_META_SCENARIOS.md) — catalog-side companion (table inventory, ownership)
- [`LINEAGE_SCENARIOS.md`](LINEAGE_SCENARIOS.md) — provenance companion (who reads / writes what)
- [`NODE_POOL_SCENARIOS.md`](NODE_POOL_SCENARIOS.md) — infra companion (utilization / cold-starts under the queries)
- [`CHATBOT_SCENARIOS.md`](CHATBOT_SCENARIOS.md) — natural-language interface for ad-hoc QH questions
- [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) — qh × billing × meta × lineage × audit joins
- [`../technical/QUERY_PROFILER_TRANSFORMATION.md`](../technical/QUERY_PROFILER_TRANSFORMATION.md) — how `system.query.history` becomes the `qi_*` family
