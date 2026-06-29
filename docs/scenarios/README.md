# Scenarios — business questions the app answers

Catalogues of the concrete business / operational questions each
derived dataset is designed to answer. Use these to find the dashboard
or endpoint that addresses a specific need, or as a checklist when
adding a new persona / scenario.

Each doc is **persona-first**: it describes *what to ask the platform*
rather than *how the underlying tables are shaped* (that lives in the
per-feature deep-dives under `../features_grouped/` and in
[`../DATA_DICTIONARY.md`](../DATA_DICTIONARY.md)). Useful when
onboarding a new audience or planning a roadmap of dashboards.

---

## Per-dataset catalogues

| Doc | Backing dataset(s) | App surface | What it answers |
|---|---|---|---|
| [`BILLING_SCENARIOS.md`](BILLING_SCENARIOS.md) | `billing_usage`, `list_prices`, `clusters`, `warehouses`, `jobs` | **Billing Explorer** (Overview, Cost Explorer, User Footprint, Trends & Forecast, Compute Resources, SKU & Billing Origin, Advanced Analytics) | Cost attribution, chargeback, rightsizing, anomaly detection, forecast, serverless share, concentration, per-cloud / per-workspace breakdowns. |
| [`QUERY_HISTORY_SCENARIOS.md`](QUERY_HISTORY_SCENARIOS.md) | `qi_*` family (parsed `system.query.history`) | **Query Profiler** (Overview + 10 per-department dashboards) | Expensive queries, full-scans, spill, error trends, capacity / queueing, cache effectiveness, catalog usage, FinOps attribution, executive adoption, data-eng job health, BI / dashboard latency, data-science / Genie adoption, security access patterns, developer experience, cross-cutting SQL-feature mix. |
| [`DBX_META_SCENARIOS.md`](DBX_META_SCENARIOS.md) | `databricks_meta` (Unity Catalog snapshot) | **Meta Explorer → Overview** | Catalog footprint, table-type distribution, schema density, wide-tables, PII heuristics, ownership concentration, documentation coverage, key reuse, drift detection. |
| [`LINEAGE_SCENARIOS.md`](LINEAGE_SCENARIOS.md) | `lineage_table_edges`, `lineage_column_edges` (rolled-up `system.access.{table,column}_lineage`) | **Meta Explorer → Lineage — Tables** and **— Columns** | Fan-in / fan-out, orphans, terminal tables, entity-type mix, dependency-blast radius, sensitive-data propagation, column-level provenance. |
| [`AUDIT_SCENARIOS.md`](AUDIT_SCENARIOS.md) | `audit_events` (`system.access.audit`), `assistant_events` | **Meta Explorer → Audit** | Login forensics, permission denials, grant/revoke trails, SP activity, account-level admin actions, AI / Genie adoption, AI quality proxy, audit retention. |
| [`NODE_POOL_SCENARIOS.md`](NODE_POOL_SCENARIOS.md) | `node_timeline`, `warehouse_events`, `instance_events`, `node_types`, `instance_pools` | **Meta Explorer → Node Pool** | Cluster CPU / memory utilization, memory pressure, preemption rate, cold-start latency, autoscale efficiency, pool sizing, hardware-mix inventory. |
| [`CHATBOT_SCENARIOS.md`](CHATBOT_SCENARIOS.md) | Whole warehouse via NL → SQL | **Chatbot** | Natural-language Q&A across every table, with schema-aware SQL generation, optional explain mode, CSV / XLSX export. Conversational refinement; cross-table reasoning. |
| [`DATA_OPS_SCENARIOS.md`](DATA_OPS_SCENARIOS.md) | All operational state | **Data Management**, **Database Explorer**, **Spark SQL Editor**, **Users**, **Roles**, view-mode toggle, notifications bell | Extract / ingest / seed / soft-delete / hard-delete / restore, engine switch (DuckDB ↔ Spark JDBC ↔ Spark materialized), Postgres browsing, Spark ad-hoc SQL, RBAC, per-role feature flags and filters, demo / real isolation. |

## Cross-cutting

| Doc | What it answers |
|---|---|
| [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) | Questions that **only have good answers when you join two or more datasets**. The "Project Greenlight" review, the TCO of an analyst, PII propagation × spend, deprecation blast radius, cost-per-business-outcome, phantom-workspace cost, AI adoption funnel, vendor migration leverage. The chatbot is often the best interface for these. |

---

## Coverage map — app page ↔ scenario doc

| App page (sidebar path) | Primary scenario doc | Also relevant |
|---|---|---|
| Dashboard (landing) | — | — |
| Billing Explorer (Overview, Cost Explorer, User Footprint, Trends, Compute, SKU & Billing Origin, Analytics) | [`BILLING_SCENARIOS.md`](BILLING_SCENARIOS.md) | [`NODE_POOL_SCENARIOS.md`](NODE_POOL_SCENARIOS.md) (utilization side), [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) |
| Query Profiler (Overview + 10 sub-pages) | [`QUERY_HISTORY_SCENARIOS.md`](QUERY_HISTORY_SCENARIOS.md) | [`BILLING_SCENARIOS.md`](BILLING_SCENARIOS.md), [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) |
| Meta Explorer → Overview | [`DBX_META_SCENARIOS.md`](DBX_META_SCENARIOS.md) | [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) |
| Meta Explorer → Lineage (Tables & Columns) | [`LINEAGE_SCENARIOS.md`](LINEAGE_SCENARIOS.md) | [`DBX_META_SCENARIOS.md`](DBX_META_SCENARIOS.md), [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) |
| Meta Explorer → Audit | [`AUDIT_SCENARIOS.md`](AUDIT_SCENARIOS.md) | [`QUERY_HISTORY_SCENARIOS.md`](QUERY_HISTORY_SCENARIOS.md) §11, [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) |
| Meta Explorer → Node Pool | [`NODE_POOL_SCENARIOS.md`](NODE_POOL_SCENARIOS.md) | [`BILLING_SCENARIOS.md`](BILLING_SCENARIOS.md), [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) |
| Chatbot | [`CHATBOT_SCENARIOS.md`](CHATBOT_SCENARIOS.md) | every other doc — the chatbot is the universal interface |
| Data Management, Database Explorer, Spark SQL Editor, Users, Roles | [`DATA_OPS_SCENARIOS.md`](DATA_OPS_SCENARIOS.md) | — |

---

## How to add a new scenario

1. Identify the **role / persona** asking the question and which **dataset(s)** the answer requires.
2. Slot it into the right doc (per-dataset, or cross-domain if it spans ≥2 datasets).
3. Phrase it the way the persona would say it out loud — **never** in SQL or table-name jargon.
4. Name the **app page** that should answer it. If no page does today, that's a roadmap signal — file it.
5. List the **minimum columns + joins** required. For cross-domain scenarios, state the **bridge column** explicitly.
6. Include an **example SQL skeleton** only when filtering or joining is non-obvious (e.g. forgetting `usage_unit='DBU'` or `from_result_cache=False`).

---

## See also

- [`../USER_GUIDE.md`](../USER_GUIDE.md) — end-user walkthrough of every page
- [`../DATA_DICTIONARY.md`](../DATA_DICTIONARY.md) — column-level reference for every table
- [`../features_grouped/`](../features_grouped/) — per-feature technical deep dives (Audit, Compute, Lineage)
- [`../technical/`](../technical/) — architecture, engine, security, deployment
- [`../DATA_QUALITY.md`](../DATA_QUALITY.md) — comparative analysis of 8 DQ frameworks this app overlays
