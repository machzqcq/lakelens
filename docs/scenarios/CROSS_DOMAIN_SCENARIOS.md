# Cross-Domain Scenarios — Questions that Span Multiple Datasets

The other six scenario docs in this folder each cover **one** dataset
(billing, query history, meta, lineage, audit, node-pool). This doc
catalogues the questions that **only have good answers when you join
two or more of them together** — the executive's "what does this thing
really cost", the steward's "is this PII propagating where it
shouldn't", the FinOps lead's "blast radius of deprecating this table".

These are the questions where dashboards alone fall short and the
chatbot's multi-table reasoning is most valuable.

---

## 1. The five datasets and how they cross

The app's operational warehouse holds 6+ data families. The joins
below name the standard bridge column:

```
billing_usage    ↔  qi_statements         via (cluster_id|warehouse_id, time-window)
billing_usage    ↔  clusters / warehouses via cluster_id / warehouse_id
billing_usage    ↔  jobs                  via job_id
billing_usage    ↔  node_timeline         via (cluster_id, time-window)

qi_statements    ↔  qi_statement_tables   via statement_id
qi_statements    ↔  audit_events          via user_email / time-window / object
qi_statements    ↔  databricks_meta       via table_full_name (parsed from statement_text)
qi_statements    ↔  lineage_table_edges   via entity_id (job_id / dashboard_id)
qi_statement_tables ↔ databricks_meta     via (catalog, database, table_name)
qi_statement_tables ↔ lineage_table_edges via 3-part name

audit_events     ↔  assistant_events      via user_email / event_time
audit_events     ↔  lineage_table_edges   via entity_id

databricks_meta  ↔  lineage_table_edges   via 3-part name
databricks_meta  ↔  lineage_column_edges  via (3-part name, col_name)

node_timeline    ↔  clusters              via cluster_id
warehouse_events ↔  warehouses            via warehouse_id
instance_events  ↔  clusters              via cluster_id
```

---

## 2. How to read the scenarios

Each cross-domain scenario states the **owning role**, the **datasets
involved**, and the **app surfaces** it touches. SQL skeletons are
provided where the join is non-obvious.

---

## 3. The "Project Greenlight" review *(billing × query × meta × lineage)*

**Role:** Executive / FinOps / Product Owner.
**Q.** Given a project keyword `<X>`, return: total cost YTD, top 5 contributors, top 5 tables, top 5 dashboards, failure rate, distinct users, AI / Genie adoption %.
*Datasets:* `billing_usage`, `qi_statements`, `query_tags`, `jobs`, `databricks_meta`, `lineage_table_edges`, `assistant_events`.
*App surface:* Query Profiler → FinOps → Project / Keyword Search (returns spend + statement count + per-workspace breakdown). For deeper attribution use the Chatbot with the question above.

```sql
-- Skeleton — replace <X> with the keyword
WITH matched AS (
  SELECT s.statement_id, s.user_email, s.usage_usd, s.execution_status,
         s.workspace_id, s.statement_type, s.dashboard_id, s.job_id
  FROM qi_statements s
  LEFT JOIN qi_statement_tables t USING (statement_id)
  WHERE s.data_origin = current_setting('app.view_mode')
    AND s.deleted_at IS NULL
    AND (
        s.statement_text ILIKE '%' || '<X>' || '%'
     OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(s.query_tags) v WHERE v ILIKE '%' || '<X>' || '%')
     OR t.table_full_name ILIKE '%' || '<X>' || '%'
    )
)
SELECT COUNT(*) AS statement_count,
       COUNT(DISTINCT user_email) AS distinct_users,
       SUM(usage_usd) AS total_cost,
       AVG(CASE WHEN execution_status='FAILED' THEN 1.0 ELSE 0 END) AS failure_rate
FROM matched;
```

*Why it matters:* the headline executive question. Every cost-review
meeting opens with "tell me about Project X". The keyword fan-out is
deliberately fuzzy to catch tag, table, and job-name signals together.

---

## 4. The "TCO of an analyst" *(billing × query × audit × assistant)*

**Role:** FinOps / People Analytics.
**Q.** For analyst U, sum: queries they ran (cost), dashboards they author (refresh cost), notebooks they own (query cost), Genie asks they triggered. What does U really cost the platform?
*Datasets:* `billing_usage`, `qi_statements`, `audit_events` (ownership), `assistant_events`.
*App surface:* User Footprint → enter `run_as` → SKUs / clusters / warehouses / total cost. The dashboard handles the direct-run side; cross-reference dashboards-the-user-authors via Chatbot.

*Why it matters:* converts "headcount cost" into "actual platform cost"
— often differs by 10× between an SQL-Editor user and a notebook power
user who owns refresh schedules.

---

## 5. PII propagation × spend *(meta × lineage × billing × audit)*

**Role:** Privacy / Compliance / DPO.
**Q.** For each table flagged as PII (heuristic on `databricks_meta.col_name`), find: where it flows downstream (lineage), how much was spent querying it (billing × qi), which users accessed it, any `INSUFFICIENT_PERMISSIONS` denials (audit).
*Datasets:* `databricks_meta`, `lineage_table_edges`, `lineage_column_edges`, `billing_usage`, `qi_statement_tables`, `audit_events`.
*App surface:* combined — Meta Explorer + Lineage Columns + Query Profiler → Security + Audit. The chatbot can stitch them in one prompt.

```sql
-- Skeleton — Step 1: find PII tables from column names
WITH pii_tables AS (
  SELECT DISTINCT catalog || '.' || database || '.' || table_name AS table_full_name
  FROM databricks_meta
  WHERE deleted_at IS NULL
    AND col_name ~* '(ssn|dob|birth|email|phone|credit_card|mrn|patient|diagnosis)'
), downstream AS (   -- Step 2: lineage fan-out
  SELECT pii.table_full_name AS pii_source,
         l.target_table_full_name AS downstream
  FROM pii_tables pii
  JOIN lineage_table_edges l ON l.source_table_full_name = pii.table_full_name
), pii_query_cost AS (   -- Step 3: spend × access
  SELECT pii.table_full_name, SUM(s.usage_usd) AS cost, COUNT(*) AS reads, COUNT(DISTINCT s.user_email) AS users
  FROM pii_tables pii
  JOIN qi_statement_tables t ON t.table_full_name = pii.table_full_name
  JOIN qi_statements s ON s.statement_id = t.statement_id
  GROUP BY 1
)
SELECT * FROM pii_query_cost ORDER BY cost DESC;
```

*Why it matters:* the privacy review's one-page summary. Without this
join, "PII reviews" are catalog-only — you don't see what it costs to
query or who actually accesses it.

---

## 6. Deprecation blast radius *(meta × lineage × query × billing)*

**Role:** Data Eng / Stewardship.
**Q.** If we deprecate table T tomorrow, who breaks and how much downstream cost will be at risk?
*Datasets:* `lineage_table_edges`, `qi_statement_tables`, `qi_statements`, `billing_usage`.
*App surface:* Meta Explorer → Lineage Tables → search T → fan-out graph → click entities; combine with Query Profiler.

```sql
-- All downstream entities, plus reads from T in the last 30 days
SELECT l.entity_type, l.entity_id, COUNT(*) AS edge_count
FROM lineage_table_edges l
WHERE l.source_table_full_name = 'acme_data_lake.curated.<T>'
GROUP BY 1,2
ORDER BY edge_count DESC;
```

*Why it matters:* deprecating a table without checking the lineage is
how mid-week dashboards break. The lineage rollup answers "everything
that touched this" in one query.

---

## 7. Cost per business outcome *(lineage × billing × query)*

**Role:** Data Product Owner / FinOps.
**Q.** For dashboard D (or job J), what's the *total upstream cost* — sum the spend of every job / pipeline that produces tables D reads?
*Datasets:* `lineage_table_edges`, `qi_statements`, `billing_usage`.
*App surface:* (composite — not a single dashboard yet) — Lineage Tables to identify upstream entities, then Query Profiler / Cost Explorer to sum their cost.

*Why it matters:* converts "dashboard cost" (just the refresh DBUs)
into the *real* cost of the data product (refresh + every upstream
mart + every staging step). Often 5-20× the obvious number.

---

## 8. Failed-query blast radius *(query × lineage × billing)*

**Role:** SRE / Data Eng.
**Q.** A frequently-failing query — who downstream depends on its output? What's the daily cost being wasted on the retries?
*Datasets:* `qi_statements` (failed), `lineage_table_edges` (downstream of the target table), `billing_usage`.
*App surface:* Query Profiler → Platform → Error Trends + Lineage Tables.

---

## 9. Node-pool utilization × spend *(node-pool × billing)*

**Role:** FinOps / Capacity.
**Q.** For each cluster, divide last week's billing $ by mean CPU utilization to compute $/utilization-point. Sort.
*Datasets:* `node_timeline`, `billing_usage`, `clusters`.
*App surface:* (composite — Compute Resources for billing per cluster + Node Pool → Utilization for the load average).

```sql
WITH util AS (
  SELECT cluster_id, AVG(cpu_user_percent + cpu_system_percent) AS active_cpu
  FROM node_timeline
  WHERE sample_time >= CURRENT_DATE - INTERVAL '7 days' AND deleted_at IS NULL
  GROUP BY 1
), cost AS (
  SELECT cluster_id, SUM(usage_usd) AS cost
  FROM billing_usage
  WHERE usage_date >= CURRENT_DATE - INTERVAL '7 days' AND deleted_at IS NULL
  GROUP BY 1
)
SELECT u.cluster_id, u.active_cpu, c.cost,
       c.cost / NULLIF(u.active_cpu, 0) AS cost_per_cpu_pt
FROM util u JOIN cost c USING (cluster_id)
ORDER BY cost_per_cpu_pt DESC LIMIT 25;
```

*Why it matters:* the high-cost-per-utilization clusters are the rightsizing list. A cluster paying $400/day and averaging 15% CPU is the most obvious waste.

---

## 10. Audit × lineage — who triggered the sensitive flow

**Role:** Security / Privacy.
**Q.** A pipeline wrote into a PII-flagged table last night. Who launched the job?
*Datasets:* `lineage_table_edges` (find the entity_id that wrote), `audit_events` (find the human who launched that entity), `databricks_meta` (confirm PII flag).
*App surface:* Lineage Tables to find the entity → Audit search by entity_id / user / time → confirm the human.

---

## 11. AI adoption funnel *(assistant × query × audit)*

**Role:** Executive / AI lead.
**Q.** For Genie / AI Assistant, build the funnel: prompts → SQL generated → SQL executed → result used (copied / refined).
*Datasets:* `assistant_events`, `qi_statements`, `audit_events`.
*App surface:* Meta Explorer → Audit (assistant strip) + Query Profiler → Data Science → Genie Adoption + Executive → Adoption Trend.

*Why it matters:* the only first-party way to measure "is the AI assistant useful" — going from "they asked it something" all the way to "the generated SQL ran on the warehouse and the result moved into a dashboard / notebook."

---

## 12. Phantom-workspace cost *(billing × audit × meta)*

**Role:** Platform Admin.
**Q.** Is there workspace cost that has no audit activity and no catalog activity?
*Datasets:* `billing_usage`, `audit_events`, `databricks_meta`.
*App surface:* (composite — query via chatbot or Database Explorer).

```sql
-- Workspaces with billing rows in the last 30 days but no audit rows
WITH b AS (
  SELECT workspace_id, SUM(usage_usd) AS cost
  FROM billing_usage
  WHERE usage_date >= CURRENT_DATE - INTERVAL '30 days' AND deleted_at IS NULL
  GROUP BY 1
), a AS (
  SELECT DISTINCT workspace_id FROM audit_events
  WHERE event_time >= CURRENT_DATE - INTERVAL '30 days' AND deleted_at IS NULL
)
SELECT b.workspace_id, b.cost FROM b LEFT JOIN a USING (workspace_id) WHERE a.workspace_id IS NULL;
```

*Why it matters:* deletion candidates with strong evidence. Usually points to an orphaned scheduled job or a forgotten demo.

---

## 13. Cost-per-business-decision *(lineage × billing × audit-assistant)*

**Role:** Data Product Owner.
**Q.** Per executive dashboard, compute: # distinct viewers, # weekly refreshes, $ per refresh, average freshness lag, # Genie-related questions referencing the same tables. Aggregate into a cost-per-decision proxy.
*Datasets:* `lineage_table_edges`, `qi_statements` (dashboard refreshes), `assistant_events`, `billing_usage`.
*App surface:* composite.

---

## 14. "Hidden TCO" of a BI vendor *(query × billing × audit)*

**Role:** Procurement.
**Q.** For Tableau (or Power BI), compute: % of total platform DBUs, # distinct users, # dashboards, # daily refreshes, total cost. What's the leverage if we migrate it?
*Datasets:* `qi_statements.client_application`, `billing_usage` (via compute attribution), `audit_events` (driver / version compliance).
*App surface:* Query Profiler → BI → Vendor Footprint + Cost Explorer.

---

## 15. Compliance: PII × cost × denials

**Role:** Compliance / Privacy.
**Q.** For tables flagged PII, monthly: how much was spent querying them, by whom, how many denials, how many off-hours human accesses?
*Datasets:* `databricks_meta` (PII flag), `qi_statement_tables` + `qi_statements`, `billing_usage`, `audit_events` (denials, off-hours).
*App surface:* composite — Meta Explorer + Query Profiler → Security + Audit. The chatbot is the easiest path.

---

## 16. Per-data-product health card

**Role:** Data Product Owner.
**Q.** Render a one-page card for each "data product" (a set of tables) showing: distinct consumers (MAC), top 5 consumers, freshness lag, cost trend, undocumented column %, lineage fan-out count, error count.
*Datasets:* almost all — billing × query × meta × lineage × audit.
*App surface:* (roadmap — no single page renders this yet; use chatbot for ad-hoc).

---

## 17. Migration readiness across surfaces *(query × lineage × meta)*

**Role:** Data Eng / Architect.
**Q.** If I rename `catalog_v1` to `catalog_v2`, which queries reference it, which dashboards, which jobs, which downstream tables?
*Datasets:* `qi_statements` (text grep), `qi_statement_tables`, `lineage_table_edges`, `databricks_meta`.
*App surface:* composite.

---

## 18. Limitations & gotchas the agent should know

- **`statement_text` is truncated** for huge queries — text-grep cross-joins may undercount.
- **Compute attribution between billing and qi is time-window-based** — billing aggregates daily; qi has start/end timestamps. Joining requires window overlap, not exact timestamps.
- **`data_origin` filter must be applied to every side** — joining `qi_statements (demo)` to `billing_usage (real)` will return nothing or worse, mislead.
- **Lineage is best-effort** — `direct_edges` is authoritative; `indirect_edges` is inferred and should be flagged as such in compliance answers.
- **`databricks_meta` is daily** — joins to second-grain tables (qi, audit) need `meta.as_of <= qi.start_time` or accept a 1-day lag.
- **`run_as` vs `user_email` vs `user_identity_email`** — three different columns across the three datasets. Map carefully:
  - `billing_usage.run_as` = effective identity at billing time
  - `qi_statements.user_email` = `executed_by` (the requester)
  - `qi_statements.executed_as` = the principal whose privileges were checked
  - `audit_events.user_identity_email` = whoever called the API
- **OAuth-on-behalf-of and dashboard-run-as-owner** mean `run_as ≠ user` is common; investigate before assuming.

---

## 19. How to add a new cross-domain scenario

1. Identify the **two or more datasets** involved.
2. State the **bridge column** (cluster_id / warehouse_id / job_id / time-window / 3-part name / entity_id / user_email).
3. List the **app pages** that each contribute; if no single page renders the answer, mark it as a chatbot-best-suited scenario.
4. If the join recurs, file a UX request — a built-in dashboard is cheaper to run than the chatbot for repeated questions.

---

## See also

Per-dataset scenario catalogues:

- [`BILLING_SCENARIOS.md`](BILLING_SCENARIOS.md)
- [`QUERY_HISTORY_SCENARIOS.md`](QUERY_HISTORY_SCENARIOS.md)
- [`DBX_META_SCENARIOS.md`](DBX_META_SCENARIOS.md)
- [`LINEAGE_SCENARIOS.md`](LINEAGE_SCENARIOS.md)
- [`AUDIT_SCENARIOS.md`](AUDIT_SCENARIOS.md)
- [`NODE_POOL_SCENARIOS.md`](NODE_POOL_SCENARIOS.md)
- [`CHATBOT_SCENARIOS.md`](CHATBOT_SCENARIOS.md) — recommended interface for most cross-domain questions
