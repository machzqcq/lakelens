# Audit — `system.access.audit` + `system.access.assistant_events`

Authoritative Databricks references:
- [`system.access.audit`](https://docs.databricks.com/aws/en/admin/system-tables/audit-logs)
- [`system.access.assistant_events`](https://docs.databricks.com/aws/en/admin/system-tables/assistant)

This doc covers how the app ingests, stores, and surfaces the audit
trail + Databricks Assistant prompt feed.

## Table of contents

- [What the data looks like](#what-the-data-looks-like)
- [The Audit dashboard](#the-audit-dashboard)
- [Extraction — chunked weekly](#extraction--chunked-weekly)
- [Postgres model + Spark exposure](#postgres-model--spark-exposure)
- [Common questions](#common-questions)

---

## What the data looks like

### `audit_events` (mirror of `system.access.audit`)

One row per Databricks audit event. Captures every workspace and
account-level action: logins, table grants, notebook exports, SQL
warehouse start/stops, Unity Catalog ops, cluster lifecycle, MLflow
registrations, DBFS writes — anything the platform emits a signed log
line for.

| Column | Notes |
|---|---|
| `account_id`, `metastore_id`, `workspace_id` | Owner identifiers. `workspace_id='0'` for ACCOUNT_LEVEL events. |
| `version` | Audit schema version (currently `'2.0'`). |
| `event_time`, `event_date` | UTC. `event_date` partitioned upstream; chunked extraction filters on it. |
| `source_ip_address`, `user_agent`, `session_id` | Request provenance. |
| `user_identity` | STRUCT `{email, subjectName}` stored as JSON. |
| `user_identity_email` | Pre-extracted from `user_identity.email` for cheap GROUP BY — joins to `billing_usage.run_as`, `query_history.executed_by`, `qi_statements.executed_by`. |
| `service_name` | Open-ended; common values: `unityCatalog`, `notebook`, `SQL`, `accounts`, `clusters`, `jobs`, `dbfs`, `mlflow`. |
| `action_name` | What happened. Examples per service: `createTable`/`grant` (unityCatalog), `runCommand`/`exportNotebook` (notebook), `executeQuery` (SQL), `login` (accounts), `start`/`terminate` (clusters), `runNow` (jobs). |
| `request_id` | Unique per request. |
| `request_params` | `MAP<STRING, STRING>` stored as JSON. Keys vary by (service, action). |
| `response` | STRUCT `{status_code, error_message, result}` stored as JSON. |
| `response_status_code` | Pre-extracted. 200 = success; 4xx = client error; 5xx = server error. |
| `response_error_message` | Pre-extracted. NULL when status is 2xx. |
| `audit_level` | `ACCOUNT_LEVEL` (workspace-wide events) or `WORKSPACE_LEVEL`. |
| `event_id` | Unique event identifier. |
| `identity_metadata` | STRUCT `{run_by, run_as}` — populated for on-behalf-of actions (service principal impersonation, etc.). |

### `assistant_events` (mirror of `system.access.assistant_events`)

One row per **user-submitted** Databricks Assistant / Genie Code
interaction. The table deliberately excludes autocomplete and safety
checks upstream — so volume is small and the signal is "who actively
prompted the Assistant."

| Column | Notes |
|---|---|
| `event_id`, `account_id`, `workspace_id` | Owner identifiers. |
| `event_time`, `event_date` | UTC. |
| `user_agent` | Origin client — proxy for which Databricks surface (notebook / SQL editor / dashboards) submitted the prompt. |
| `initiated_by` | Email of the user that submitted the prompt. Joinable with `billing_usage.run_as` / `qi_statements.executed_by`. |

---

## The Audit dashboard

`Meta Explorer → Audit` (`/meta-explorer/audit`) renders the data at a
glance:

| Widget | Source |
|---|---|
| **KPI tiles** | Audit events · distinct users · distinct services · distinct (service,action) pairs · error events (`response_status_code ≥ 400`) · Assistant prompts. |
| **By `service_name`** breakdown bar | Where the activity is concentrated (unityCatalog vs notebook vs SQL etc.). |
| **By `audit_level`** breakdown bar | ACCOUNT_LEVEL vs WORKSPACE_LEVEL — quick sanity check that account-tier events are landing. |
| **By status class** breakdown bar | 2xx / 3xx / 4xx / 5xx — error rate at a glance. |
| **Top actions** (`service_name : action_name`) | Click any row to filter the recent-events table to that service. |
| **Top users (audit)** | By total audit events; click → filter the recent table to that user. |
| **Top users (Assistant)** | By total Genie / Assistant prompt count. |
| **Recent events** table | Newest first; per-event time, user, service, action, status code, audit level, workspace, source IP, error. Filters: errors-only, by service, by user. |
| **Search** | Substring across user / service / action / source IP / error message; surfaces `matched_in` per hit. |

---

## Extraction — chunked weekly

The `audit` extraction group covers BOTH `audit_events` and
`assistant_events`. In `Admin → Data Management → Extract from
Databricks`, an "Audit lookback" amber callout exposes a single
two per-table number inputs:

- `audit_events` — default **3 days**. The highest-cardinality
  `system.access.*` table; at 30 days even a small account can OOM the
  Spark Connect driver while collecting Arrow batches. Bump only if
  you need historic event coverage.
- `assistant_events` — default **30 days**. Low-volume by design
  (user-submitted Genie / Assistant prompts only), so a wider window
  is safe.

Even at the conservative defaults:

- Extraction loops by **7-day chunks** (same machinery as
  `table_lineage` extraction) so each `.toPandas()` call stays bounded.
- Pushdown is enabled at the Spark JDBC layer for downstream reads
  (when the chatbot queries them in `jdbc_views` mode).
- The extractor returns a tolerated-fail when the access schema isn't
  enabled on the account — other groups in the same extract still succeed.

Demo: `scripts/simulate_demo_data.py` synthesises `demo_audit_events`
(~25k rows over 30 days, ~8 services × per-service action vocab, 92%
success / 5% 4xx / 3% 5xx mix, ACCOUNT_LEVEL events have
`workspace_id='0'`) and `demo_assistant_events` (~2k rows).

---

## Postgres model + Spark exposure

| Model | Postgres table | Spark surface |
|---|---|---|
| `AuditEvent` | `audit_events` | In `spark_mode=jdbc_views`: JDBC temp view (referenced unqualified, with the `temp` badge in the Spark SQL Editor). In `spark_mode=materialized`: managed Delta table at `spark_catalog.default.audit_events`. |
| `AssistantEvent` | `assistant_events` | Same dual exposure. |

Both carry the standard `data_origin` (`'real'` / `'demo'`) and
`deleted_at` columns; every read endpoint scopes by the caller's
`viewing_data_mode` and `deleted_at IS NULL` — same as every other
domain table. The Materialize action copies both into spark-warehouse
when run.

---

## Chatbot integration

`backend/routers/chat_audit_schema.py` is the inline grounding file the
chatbot uses to ask audit-shaped questions in natural language. It tells
the LLM:

- the open-ended enum hints for `service_name` / `action_name`
- that `response_status_code ≥ 400` is the error filter
- that `audit_level='ACCOUNT_LEVEL'` matches `workspace_id='0'`
- that `user_identity_email` is the cheap GROUP BY column (vs the JSON STRUCT)
- the join keys back to `billing_usage`, `query_history`, `qi_statements`

The system prompt for all three engine modes (DuckDB, Spark+jdbc_views,
Spark+materialized) includes a dedicated audit rule so the LLM emits
the right qualified / unqualified table names.

---

## Common questions

**Q. The Audit dashboard shows 0 events.**
- Check view-mode (top-right toggle). Demo data needs the demo
  partition; real data needs an Extract that included the `audit` group.

**Q. I see only WORKSPACE_LEVEL events; where are the ACCOUNT_LEVEL ones?**
- ACCOUNT_LEVEL events carry `workspace_id='0'`. They're definitely
  ingested; if the "By audit_level" bar is empty, account-tier auditing
  may not be enabled on your Databricks account.

**Q. Which `service_name` should I look at first?**
- `accounts` (logins, token use, user-management) for security forensics;
  `unityCatalog` (grants, table create/drop) for governance reviews;
  `SQL` + `notebook` for usage attribution.

**Q. How is this different from Query Profiler?**
- Query Profiler is per-statement (every SQL the warehouse ran). Audit
  is per-action across the whole platform (logins, grants, exports —
  things SQL alone can't tell you). They join on user email, and
  `audit_events.user_identity_email = qi_statements.executed_by` is a
  useful narrative bridge.
