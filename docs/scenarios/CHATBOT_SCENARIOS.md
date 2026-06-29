# Chatbot — Natural-Language Scenarios & Questions

A field guide to what every role can ask the **Chatbot** (sidebar →
Chatbot) — the natural-language Q&A surface that compiles user
questions into schema-aware SQL, executes it against the warehouse,
renders results as a table or chart, and offers CSV / XLSX export.

The chatbot is **complementary** to the structured dashboards: when a
question doesn't fit any preset visualization, ask it in plain English.

---

## 1. Which app page backs these scenarios

| App page (sidebar path) | What it answers | Backed by |
|---|---|---|
| **Chatbot** | NL question → generated SQL (with optional explain) → executed result table → CSV / XLSX download. Pick provider (OpenAI / Anthropic / Google) and model. View the system prompt + raw LLM response for forensic / prompt-engineering inspection. | The full operational warehouse: `billing_usage`, `list_prices`, `clusters`, `warehouses`, `jobs`, `databricks_meta`, `qi_*`, `audit_events`, `assistant_events`, `lineage_*`, `node_timeline`, `warehouse_events`, `instance_events`, `node_types`, `instance_pools`. |

Endpoints live under `/api/chat/*` — see `backend/routers/chat.py`.
The engine layer (DuckDB by default, optional Spark via the engine
switch) is documented in `docs/technical/QUERY_ENGINE.md`.

---

## 2. Why the chatbot is a goldmine

The structured dashboards are great for **known questions** with
**known shapes**. The chatbot covers everything else:

- **Long-tail** — questions a one-off project needs that don't justify a dashboard
- **Conversational** — follow-ups that refine without re-clicking filters
- **Cross-table** — questions that span billing × query × meta × lineage in a way the UI doesn't pre-join
- **Exploratory** — "give me the top 10 X grouped by Y filtered to Z" without learning the schema first
- **Export-driven** — the answer is a CSV / XLSX an analyst will further work on
- **Onboarding aid** — a new hire can poke around without learning the table names yet

The chatbot is schema-aware (it sees Postgres `information_schema` plus
the consolidated metadata `xlsx` with column descriptions), so it can
write valid SQL against the actual tables in the operational store.

---

## 3. How to read the scenarios

> **Q.** A natural-language prompt — paste it into the chatbot input as-is.
> *Behind the scenes:* the tables / joins / filters the LLM has to choose.
> *Why it matters:* what the answer changes.

Some scenarios include the **generated SQL skeleton** — useful when you
want to copy-edit the LLM output or pre-seed an "explain" prompt.

---

## 4. Executive / Data Office

**Q.** "How much did we spend on Databricks last month, broken down by workspace?"
*Behind the scenes:* `billing_usage` filtered by month, grouped by `workspace_id`, joined to workspace meta for friendly names.
*Why it matters:* the most common board-deck slide pulled on-demand.

**Q.** "What's our serverless share of total DBUs this quarter, monthly?"
*Behind the scenes:* derive `is_serverless` from SKU pattern; sum DBUs; group by month.

**Q.** "Which BI tool has the largest footprint by query count and by cost?"
*Behind the scenes:* `qi_statements.client_application` × billing via `compute.warehouse_id` join.

**Q.** "Top 5 jobs by spend last month, plus their failure rate."
*Behind the scenes:* billing × `qi_statements` joined by `job_id`, with success/failure aggregates.

---

## 5. FinOps / Cost Engineering

**Q.** "Show me cost by cost-center tag for the last 90 days. Flag anything > $5,000."
*Behind the scenes:* `usage_metadata` / `custom_tags` open-JSON expansion; rollup; threshold flag.

**Q.** "Which warehouses had average queue time > 3 seconds last week?"
*Behind the scenes:* `qi_statements.waiting_at_capacity_duration_ms` aggregated per warehouse, average > 3000ms.

**Q.** "Cost of FAILED + CANCELED queries last month — by workspace."
*Behind the scenes:* `qi_statements.execution_status IN ('FAILED','CANCELED')` joined billing by compute_id.

**Q.** "What was the daily cost of model serving in May vs April?"
*Behind the scenes:* `billing_usage` filtered to `billing_origin_product='MODEL_SERVING'`, MoM compare.

---

## 6. Platform / IT / SRE

**Q.** "Which clusters had average CPU below 20% AND average memory below 50% over the last week?"
*Behind the scenes:* `node_timeline` aggregated; threshold filter; rank by cost (joined billing).

**Q.** "List the 10 most-frequent errors from `qi_statements` last week. Group by error category."
*Behind the scenes:* `error_message` LIKE pattern matching → categorize → top 10.

**Q.** "Which Databricks services had the worst error rate yesterday?"
*Behind the scenes:* `audit_events` grouped by `service_name`, 4xx+5xx count / total.

---

## 7. Data Engineering

**Q.** "For job `pipeline-prod-nightly`, what's its p95 duration this week vs last?"
*Behind the scenes:* `qi_statements` ⨯ `jobs` on `job_id`, percentile per week.

**Q.** "Which DLT pipelines wrote more than 10 GB last night?"
*Behind the scenes:* `qi_statements.written_bytes > 10e9` filtered to `pipeline_id IS NOT NULL`, last night window.

**Q.** "Latest 20 failed jobs and their error messages."
*Behind the scenes:* `qi_statements.execution_status='FAILED' AND job_id IS NOT NULL`, latest 20.

---

## 8. Catalog / Data Stewardship

**Q.** "Which tables have NO `table_comment`? Limit to the top 50 most-queried."
*Behind the scenes:* `databricks_meta` ⨯ `qi_statement_tables` rollup; filter `table_comment IS NULL`; sort by query count.

**Q.** "Find all columns named like `ssn`, `dob`, `email`, `phone` — group by catalog."
*Behind the scenes:* `databricks_meta.col_name` regex match.

**Q.** "Which schemas have more than 500 tables?"
*Behind the scenes:* `databricks_meta` grouped by `(catalog, database)`, count distinct tables.

---

## 9. BI / Analytics

**Q.** "Top 10 slowest dashboards by p95 latency this month."
*Behind the scenes:* `qi_statements.dashboard_id IS NOT NULL` percentiles per dashboard.

**Q.** "Which dashboards haven't been viewed in 60+ days?"
*Behind the scenes:* `MAX(start_time)` per dashboard_id; filter < 60 days ago.

**Q.** "Per BI vendor (Power BI / Tableau / Looker / native DBSQL) — distinct dashboards, query count, total DBUs."
*Behind the scenes:* `qi_statements.client_application` rollup.

---

## 10. Security / Governance

**Q.** "Who got `INSUFFICIENT_PERMISSIONS` errors against tables in `acme_data_lake.curated` last week?"
*Behind the scenes:* `qi_statements.execution_status='FAILED'` AND error pattern AND table-name LIKE.

**Q.** "Did any service principal action change Unity Catalog permissions yesterday?"
*Behind the scenes:* `audit_events.action_name LIKE '%grant%' OR LIKE '%revoke%'`, filtered to SP identity heuristic.

**Q.** "Off-hours SELECT * queries against PII tables in the last 30 days."
*Behind the scenes:* PII heuristic on table list; statement_text LIKE 'SELECT * %' AND off-hours `start_time`.

---

## 11. Data Science / ML

**Q.** "Which feature tables (names like `feature_*` or `train_*`) are queried by the most jobs?"
*Behind the scenes:* `qi_statement_tables` filter on name pattern; count distinct `job_id`.

**Q.** "Genie adoption per workspace over the last 90 days — monthly."
*Behind the scenes:* `assistant_events` (assistant_type='Genie') grouped by month × workspace.

**Q.** "Top 25 notebooks by total DBUs last month."
*Behind the scenes:* `qi_statements.notebook_id` × `usage_usd` rollup.

---

## 12. Lineage / Provenance

**Q.** "What tables feed into the `gold.exec_dashboard_kpi` table?"
*Behind the scenes:* `lineage_table_edges` reverse-traversal with `target_table_full_name='acme_data_lake.gold.exec_dashboard_kpi'`.

**Q.** "If we deprecate `staging.customer_raw`, which jobs and dashboards break?"
*Behind the scenes:* `lineage_table_edges.source_table_full_name='…staging.customer_raw'`, list downstream entities by type.

---

## 13. Cross-cutting / one-shot exploration

**Q.** "Tell me about Project Greenlight" (a fuzzy keyword — could be a job name, dashboard name, tag, or table prefix.)
*Behind the scenes:* multi-LIKE fan-out across `qi_statements.statement_text`, `jobs.name`, dashboards-via-meta, query-tags JSON; aggregate cost + counts + per-workspace breakdown.
*Why it matters:* the executive's "what is this thing costing us" question, answered from one prompt.

**Q.** "What does an analyst named `alice@acme.example.com` really cost — including her dashboards' refresh costs and her notebooks' query costs?"
*Behind the scenes:* `billing_usage WHERE run_as=...` + dashboards she authors + notebooks she owns × `qi_statements`.

**Q.** "Show me the most expensive query each day this week, with the SQL text."
*Behind the scenes:* per-day `qi_statements` row with `MAX(usage_usd)`, including `statement_text`.

---

## 14. Conversational refinement

The chatbot supports **follow-up turns** that refer to the previous
result. Effective patterns:

- "Same query, but only Power BI."
- "Now group by month instead of week."
- "Now show me the bottom 10 instead of the top 10."
- "Filter to the last 30 days."
- "Add the warehouse name as a column."
- "Export this to XLSX."
- "Explain this SQL line by line."

The bot is good at **schema-faithful refinement**; it's weaker at very
imaginative joins ("can you check if there's a correlation between X
and Y") where you may be better off asking for the raw SQL and editing
it in the Spark SQL Editor.

---

## 15. Provider / model trade-offs

The chatbot supports OpenAI, Anthropic, and Google as providers. From
the user-facing surface:

| Trait | Where the difference shows |
|---|---|
| **Schema coverage** | Larger context-window models (Opus, GPT-4o, Gemini 2.5 Pro) can hold more of the schema in one prompt — useful for cross-table queries. |
| **SQL precision** | Anthropic Sonnet/Opus often produce cleaner Postgres-compatible SQL; OpenAI is competitive; Gemini sometimes confuses Postgres ↔ Spark SQL dialect. |
| **Speed** | Haiku / Gemini Flash / GPT-4o-mini are fast enough for live conversation; the bigger siblings are noticeably slower but worth it for complex queries. |
| **Explain mode** | All three are good at explaining a returned SQL block. Anthropic tends to be the most line-by-line; OpenAI the most narrative; Gemini the briefest. |

When unsure, start with **Sonnet** or **GPT-4o** — both consistently
produce executable SQL for the question shapes above.

---

## 16. When NOT to use the chatbot

- **Production reporting** — for repeatable monthly / quarterly numbers, build a structured dashboard once. The chatbot is for ad-hoc.
- **Long-running migrations / DML** — the bot won't run DML by default and shouldn't; use the Spark SQL Editor (admin) for that.
- **Streaming or real-time** — the warehouse is batch-loaded.
- **Sensitive prompt content** — your prompt is sent to the provider you select. For confidential text, use the **mock** provider (local) or the structured dashboards.
- **Multi-row write operations** — the chatbot is read-only by design.

---

## 17. Limitations & gotchas

- **The LLM may hallucinate columns** that don't exist. The bot's SQL-validation step catches most of these and returns an error rather than running invalid SQL — but the failure message is the LLM's first guess, not always the root cause.
- **Demo / Real isolation is enforced server-side** — the bot sees only the rows visible under your current view-mode. Toggle Demo / Real at the top-right before asking if you intend to query a different partition.
- **Dialect drift** — the warehouse is Postgres-backed by default; Spark SQL syntax (`EXPLODE`, `MAP`, `STRUCT`) only works when the engine is switched to Spark. The bot is told which engine is active but occasionally gets the dialect wrong on edge cases.
- **Result size is capped** — the conversation pane caps at ~1000 rows; for larger pulls, use the Download CSV / XLSX button.
- **No memory across sessions** — each prompt is a fresh conversation; refer to earlier turns explicitly ("the previous query but …").
- **Cost** — every prompt is a paid LLM call against the provider you selected; structured dashboards are free.

---

## 18. How to add a new chatbot scenario

When a question keeps coming up:

1. Note the **role** asking it and the **natural phrasing**.
2. Decide if it deserves a **structured dashboard** instead — if it's a routine pull, dashboards are cheaper and faster.
3. If it stays in the bot, consider whether the schema's column descriptions in `consolidated_metadata_with_descriptions.xlsx` need a clarification so the LLM picks the right column.
4. Add the prompt to this doc as a known-good example for new users.

---

## See also

- `docs/technical/QUERY_ENGINE.md` — engine layer (DuckDB ↔ Spark) the chatbot runs against
- [`DBX_META_SCENARIOS.md`](DBX_META_SCENARIOS.md) — structured Meta Explorer questions the chatbot reuses
- [`QUERY_HISTORY_SCENARIOS.md`](QUERY_HISTORY_SCENARIOS.md) — structured Query Profiler questions the chatbot can also answer in NL
- [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) — cross-table questions the chatbot handles best
