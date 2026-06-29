# Billing & Cost — Enterprise Scenarios & Questions

A field guide to what every role can learn from the **Billing Explorer**
surface (sidebar → Billing Explorer) — the dollar-and-DBU layer of the
app. The underlying tables are `system.billing.usage`,
`system.billing.list_prices`, and the joined attribution tables
(`clusters`, `warehouses`, `jobs`, `workspaces`).

The catalog is grouped by role so a FinOps analyst can jump straight to
"Cost attribution", an exec to "Trends & KPIs", a platform engineer to
"Rightsizing". A cross-cutting section lists the questions that involve
more than one role.

---

## 1. Which app pages back these scenarios

| App page (sidebar path) | What it answers | Backed by |
|---|---|---|
| **Billing Explorer → Overview** | KPI strip, daily cost / DBU trend, top SKUs, by-cloud / by-origin breakdown, by-workspace breakdown. | `billing_usage`, `list_prices` |
| **Billing Explorer → Cost Explorer** | Multi-dimension drill — pick any of SKU / Workspace / Billing Origin / Usage Type / Cloud and chart it. By-user table. Daily trend filtered. | `billing_usage` |
| **Billing Explorer → User Footprint** | Per-identity rollup — pick a `run_as`, see the SKUs, clusters and warehouses they used, total cost. | `billing_usage`, `clusters`, `warehouses` |
| **Billing Explorer → Trends & Forecast** | Anomaly detection (z-score), 14-day forecast, month-over-month growth %. | `billing_usage` |
| **Billing Explorer → Compute Resources** | Paginated cluster and warehouse browser with hardware specs (vCPU, GB, GPU), filters, per-resource cost panel. | `clusters`, `warehouses`, `node_types`, `billing_usage` |
| **Billing Explorer → SKU & Billing Origin** | Treemap, SKU/origin leaderboards, pivot matrices, concentration, serverless share, drilldown into one (sku, origin) intersection. | `billing_usage` × {sku × origin × workspace × identity} |
| **Billing Explorer → Advanced Analytics** | Cost-anomaly list, MoM growth, cost-breakdown matrix (workspace × billing_origin), utilization summary. | `billing_usage` |

Endpoints live under `/api/billing/*` and `/api/analytics/*` — see
`backend/routers/billing.py` and `backend/routers/analytics.py`.

---

## 2. Why these tables are a goldmine

`billing.usage` is the **single source of truth for cloud spend on
Databricks** — one row per `(workspace_id, sku_name, usage_date,
usage_unit, cluster_id|warehouse_id, run_as, ...)` with a `usage_quantity`
in DBUs and (when joined to `list_prices`) a `usage_usd` cost. It is
simultaneously:

- A **financial ledger** (every billable hour of compute)
- A **chargeback engine** (attribution to workspace, identity, project tag)
- A **capacity log** (which hardware was used, when, for how long)
- A **product mix telemetry** (Jobs vs SQL vs DLT vs Model Serving vs Notebooks)
- A **commitment-tracking dataset** (Serverless DBU consumption vs purchased commit)

Joined with `clusters` and `warehouses` it becomes a **resource ledger**
(who owns this cluster, what DBR version, GPU or no). Joined with `jobs`
it becomes an **automation ledger** (which workflow generated the spend).
Joined with `qi_*` (Query Profiler) it becomes a **cost-per-query**
ledger — see [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md).

---

## 3. Column cheat sheet

| Bucket | Columns | Lets you answer |
|---|---|---|
| **Identity** | `workspace_id`, `account_id`, `run_as`, `cluster_id`, `warehouse_id`, `job_id` | Who / where / on which resource the DBUs were consumed. |
| **Product** | `sku_name`, `billing_origin_product`, `usage_type`, `cloud` | What part of the platform the spend belongs to (Jobs / SQL / DLT / Model Serving / Pipelines / Genie / Notebooks). |
| **Quantity** | `usage_quantity`, `usage_unit` | The raw DBU number. `usage_unit` is usually `DBU` but may be `BYTES_TRANSFERRED` etc. for storage/network charges. |
| **Money** | `usage_usd` (computed = `usage_quantity × list_prices.usd_price` at usage time) | The dollar number, computed at extract time. |
| **Time** | `usage_date`, `usage_start_time`, `usage_end_time`, `ingestion_date` | Daily granularity in `usage_date`; sub-day in the start/end timestamps. |
| **Tags** | `custom_tags`, `usage_metadata` (open JSON) | The org's chargeback dimensions (cost_center, project, team, env, …). Mandatory tagging is a separate FinOps battle. |
| **Isolation** | `data_origin`, `deleted_at` | `'real'` vs `'demo'` partition + soft-delete; the view-mode toggle filters on these. |

> Tip: `usage_usd` is **already computed** at ingest by joining
> `usage_quantity` against the price row valid at `usage_start_time`. You
> don't need to redo the price join in dashboards — it's baked in. Spot-check
> with `SELECT MIN(price_start_time), MAX(price_end_time) FROM list_prices`
> if you suspect drift.

---

## 4. How to read the scenarios

Each scenario is in the form:

> **Q.** The question, phrased the way the persona would ask it.
> *App page:* where to click. *Needs:* columns / joins required.
> *Why it matters:* what the answer changes.

Example SQL skeletons are included when the agent might otherwise get
filtering wrong (e.g. forgetting `usage_unit='DBU'` and over-counting).

---

## 5. Executive Leadership

### 5.1 Total platform cost — the slide-headline number

**Q.** What did we spend on Databricks last month? Last quarter? YoY delta?
*App page:* Billing Explorer → Overview (KPI strip + monthly bars).
*Needs:* `usage_usd`, `usage_date` aggregated by month / quarter / year.
*Why it matters:* the one number every cost review opens with.

### 5.2 Adoption — DBUs as a proxy for engagement

**Q.** Total DBUs MoM — is the platform growing?
*App page:* Billing Explorer → Overview (DBU trend).
*Needs:* `usage_quantity` aggregated daily, smoothed over months.

### 5.3 Product mix

**Q.** What share of spend is Jobs vs SQL vs DLT vs Model Serving vs Pipelines?
*App page:* SKU & Billing Origin → Origin Leaderboard.
*Needs:* `billing_origin_product` rollup of `usage_usd`.
*Why it matters:* tells the board where the lakehouse investment is paying off (and where it isn't).

### 5.4 Serverless share

**Q.** What % of compute is now Serverless vs Classic? Trend over 12 months?
*App page:* SKU & Billing Origin → Serverless Share (per-origin) + Advanced Analytics.
*Needs:* derived `is_serverless` flag from `sku_name` (`%SERVERLESS%`) or from `usage_metadata.compute_type`.
*Why it matters:* board-deck KPI. Higher serverless share = lower idle spend, better elasticity, simpler ops.

### 5.5 Concentration / risk

**Q.** What % of total cost sits in the top 5 SKUs / workspaces / users?
*App page:* SKU & Billing Origin → Concentration tab.
*Needs:* rank → cumulative share.
*Why it matters:* concentration signals single-points-of-cost; useful for negotiating discounts and for risk reviews.

```sql
SELECT label, total_cost,
       SUM(total_cost) OVER (ORDER BY total_cost DESC) / SUM(total_cost) OVER () AS cum_share
FROM (
  SELECT sku_name AS label, SUM(usage_usd) AS total_cost
  FROM billing_usage WHERE deleted_at IS NULL
  GROUP BY 1
) t ORDER BY total_cost DESC;
```

### 5.6 Forecast vs commitment

**Q.** At current run-rate, will we exceed our commit by year-end?
*App page:* Trends & Forecast (14-day forward) + Advanced Analytics → MoM Growth.
*Needs:* daily `usage_usd` time series; simple linear / Holt-Winters extrapolation.
*Why it matters:* commitment overage triggers a contract conversation; spotting it early avoids the surprise.

---

## 6. FinOps / Cost Engineering

### 6.1 Attribution & chargeback

**Q.** Cost per (cost_center, project, team, env) over the last month.
*App page:* Cost Explorer (Filter on workspace_id and group by SKU — limited by what `custom_tags` columns we extract; full tag join needs query history).
*Needs:* `usage_metadata` or `custom_tags` (open JSON) + `usage_usd` rollup.
*Why it matters:* untagged cost can't be charged back. Drives the policy of mandatory tagging.

**Q.** What % of total cost is untagged?
*Needs:* `custom_tags IS NULL OR custom_tags = '{}'` share of `usage_usd`.

### 6.2 Top-N spenders

**Q.** Top 25 users by spend this month.
*App page:* Cost Explorer → By User table.
*Needs:* `run_as` grouped sum of `usage_usd`.
*Why it matters:* the conversation starter for "is this person running something we should optimize."

**Q.** Top 25 clusters / warehouses by spend.
*App page:* Compute Resources → sort by cost. (Per-resource cost panel computes the rollup.)
*Needs:* `cluster_id` / `warehouse_id` grouped sum.

### 6.3 Failed / wasted spend

**Q.** What share of spend was on CANCELED queries that still consumed compute up to the cancel point?
*App page:* Query Profiler → FinOps → Failed Cost (cross-references billing).
*Needs:* `qi_statements.execution_status='CANCELED'` joined to billing via `compute.warehouse_id`+time window.
*Why it matters:* CANCELED is silent-spend — usually 1-3% of total but invisible in any default dashboard.

### 6.4 Per-job and per-dashboard cost

**Q.** Top 50 jobs by cost this month — which automations are the runaways?
*App page:* User Footprint → pick a `job-runner@…` identity. Cross-ref Query Profiler → DataEng → Job Failure Rates.
*Needs:* `job_id` joined `billing_usage` and `jobs.name`.

**Q.** Cost per dashboard.
*App page:* Query Profiler → BI → Slowest Dashboards (correlated with cost).
*Needs:* `query_source.dashboard_id` (qi_*) joined billing via compute attribution.

### 6.5 Rightsizing & elasticity

**Q.** Which warehouses are over-provisioned? (Low utilization, low spill, low queue.)
*App page:* Compute Resources → Warehouses tab.
*Needs:* `qi_statements.waiting_at_capacity_duration_ms ≈ 0` + `spilled_local_bytes ≈ 0` + warehouse size.
*Why it matters:* a Medium warehouse running at 10% utilization for an hour is the textbook "downsize to Small" trigger.

**Q.** Which warehouses are under-provisioned? (High wait, high spill.)
*Needs:* mirror — high `waiting_at_capacity` or high `spilled_local_bytes`.

**Q.** What's the marginal cost of moving workload X from Pro to Serverless?
*Needs:* `compute.type` mix, joined `list_prices` for both shapes.

---

## 7. Platform / IT Admin

### 7.1 Daily / weekly anomaly detection

**Q.** Where did yesterday's cost deviate from the trailing-30 baseline by > 2σ?
*App page:* Trends & Forecast → Cost Anomalies (z-score table).
*Needs:* daily `usage_usd` time series; rolling mean + std-dev; z-score per day.
*Why it matters:* the headline "why did spend spike?" detector.

```sql
WITH d AS (
  SELECT usage_date, SUM(usage_usd) AS cost
  FROM billing_usage WHERE deleted_at IS NULL GROUP BY 1
), m AS (
  SELECT usage_date, cost,
         AVG(cost) OVER (ORDER BY usage_date ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING) AS exp,
         STDDEV(cost) OVER (ORDER BY usage_date ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING) AS sd
  FROM d
)
SELECT usage_date, cost AS actual, exp, sd, (cost-exp)/NULLIF(sd,0) AS z
FROM m WHERE ABS((cost-exp)/NULLIF(sd,0)) > 2 ORDER BY usage_date DESC;
```

### 7.2 Per-cloud diff

**Q.** Cost split AWS vs Azure vs GCP this month vs last.
*App page:* Cost Explorer → by Cloud.
*Needs:* `cloud` grouped sum.
*Why it matters:* multi-cloud strategy validation; spotlight a cloud where pricing or volume changed.

### 7.3 Cluster / warehouse inventory

**Q.** Which clusters / warehouses were created last week? Which were deleted?
*App page:* Compute Resources → sort by created. (delete_time renders as "deleted" badge.)
*Needs:* `create_time`, `delete_time` filters.

**Q.** Which clusters use GPU node types?
*App page:* Compute Resources → filter `has_gpu=true`.
*Needs:* `driver_has_gpu` / `node_types.gpu_count > 0`.

---

## 8. Data Engineering / Team Leads

### 8.1 My team's footprint

**Q.** What's the spend for my workspace this month?
*App page:* Cost Explorer → filter to workspace_id.
*Needs:* `workspace_id` filter on `billing_usage`.

**Q.** What's the spend for a specific service principal (e.g. `pipeline-svc@…`) this month?
*App page:* User Footprint → enter `run_as` → see SKUs, clusters, warehouses, total cost.
*Needs:* `run_as` filter.

### 8.2 Per-resource cost drilldown

**Q.** For cluster X, what did we spend in the last 30 days? Which SKUs?
*App page:* Compute Resources → click cluster → SKU breakdown + cost panel.
*Needs:* `cluster_id` grouped `usage_usd` + SKU breakdown.

**Q.** Is this cluster Photon-enabled? Serverless?
*App page:* Compute Resources → detail pane → "Photon observed" / "Serverless observed" badges.
*Needs:* derived flags from SKU pattern `%PHOTON%` / `%SERVERLESS%`.

### 8.3 Job cost attribution

**Q.** What did Workflow-X cost last week?
*App page:* Cost Explorer + cross-reference Query Profiler → DataEng.
*Needs:* `job_id` filter on billing.

---

## 9. Analytics / BI

**Q.** Which dashboards cost the most?
*App page:* Query Profiler → BI → Slowest Dashboards (correlated). For pure cost — cross-ref Cost Explorer by source app.
*Needs:* dashboard_id × billing — see CROSS_DOMAIN.

**Q.** Per BI vendor (PowerBI, Tableau, Looker) — query count, p95 latency, cost.
*App page:* Query Profiler → BI → Vendor Footprint.
*Needs:* `client_application` × billing.

---

## 10. Data Science / ML

**Q.** Model Serving spend this month — across endpoints.
*App page:* Cost Explorer → filter `billing_origin_product='MODEL_SERVING'`.
*Needs:* `billing_origin_product='MODEL_SERVING'`.

**Q.** Foundation-model pay-per-token spend.
*App page:* Cost Explorer → SKU filter `%FOUNDATION_MODEL_PAY_PER_TOKEN%`.

**Q.** GPU vs CPU spend per workspace.
*Needs:* `usage_quantity` × is-GPU SKU pattern, grouped by `workspace_id`.

---

## 11. Procurement / Vendor Management

**Q.** Annual run-rate by SKU — for tier-pricing negotiation.
*App page:* SKU & Billing Origin → SKU Leaderboard (annualized).
*Needs:* `sku_name` rollup of `usage_usd` × annualization factor.

**Q.** Migration leverage — what would moving Tableau workload to PowerBI save?
*Needs:* `client_application` cost share + dashboards involved — see CROSS_DOMAIN.

**Q.** Commit drawdown vs purchased commit.
*Needs:* `usage_quantity` for serverless SKUs aggregated; manual subtraction from purchased commit.

---

## 12. Security / Compliance

**Q.** Is there any spend in workspaces that should have been retired?
*App page:* Cost Explorer → by Workspace + cross-check workspace meta `status`.
*Needs:* `workspaces.status` join.

**Q.** Service-principal cost — what % of total spend is automated (non-human) identities?
*App page:* User Footprint with a service-principal identity. Cost Explorer by-user.
*Needs:* heuristic on `run_as` (presence of `-svc` / `-runner` / `@*.iam.gserviceaccount.com`).

---

## 13. Cross-cutting

### 13.1 Project / keyword attribution

**Q.** Given a project name `<X>` (an LLM keyword), what's the total spend YTD?
*App page:* Query Profiler → FinOps → Project / Keyword Search (returns spend + statement-count + per-workspace breakdown).
*Needs:* fuzzy match across `query_tags`, table names in `statement_text`, job/dashboard names — see [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md).
*Why it matters:* the headline executive question; the bot wrapper supports natural language.

### 13.2 Cost per active user

**Q.** Cost per Monthly Active Consumer of the platform.
*Needs:* total cost ÷ distinct `run_as` per month.

### 13.3 Hidden-cost-of-an-analyst

**Q.** For analyst U, sum: queries they ran (cost), dashboards they author (refresh cost), notebooks they own (query cost). What do they really cost?
*App page:* User Footprint as the entry point, then cross-ref Query Profiler.
*Needs:* `run_as` and ownership joins — see CROSS_DOMAIN.

---

## 14. Joinable enrichments

| Join from | Join to | Adds |
|---|---|---|
| `cluster_id` | `clusters` | Cluster name, owner, DBR version, node specs, GPU flag |
| `warehouse_id` | `warehouses` | Warehouse name, size, type, max_clusters, autostop |
| `job_id` | `jobs` | Job name, creator, `run_as`, deletion status |
| `workspace_id` | `workspaces` (metadata) | Workspace name, URL, region, status |
| `sku_name` | `list_prices` (already pre-joined at ingest) | Per-DBU rate, validity window |
| `(cluster_id, time)` | `qi_statements` | Per-query attribution (cost ↔ statement) |
| `(cluster_id, time)` | `node_timeline` | CPU/memory utilization during the bracket — does this cost match real load? |

---

## 15. Limitations & gotchas the agent should know

- **`usage_unit` is not always DBU.** Filter `usage_unit='DBU'` before summing as DBUs; otherwise you'll add bytes/tokens.
- **`usage_usd` is computed at ingest** — if list_prices changed retroactively the historical numbers won't reflect that. Re-extracting refreshes them.
- **Serverless rows have `cluster_id` NULL** — group with `COALESCE(cluster_id, warehouse_id, 'serverless')` for a unified resource axis.
- **`delete_time` on clusters/warehouses is when the resource was deleted, not when usage ended** — a deleted resource can still have billing rows for the time before the delete.
- **`custom_tags` is an open schema** — you need an org-wide tagging policy for FinOps scenarios to work end-to-end.
- **Demo vs Real**: every billing query is implicitly scoped to the user's view mode (`data_origin`); ignore at your peril when querying via spark-sql editor.

---

## 16. How to add a new billing scenario

1. Identify the **role asking it** — slot it into the right section above.
2. Phrase it the way the persona would say it out loud.
3. List the **minimum columns + joins** required.
4. Name the **app page** that should answer it. If none exists yet, that's a roadmap input.
5. Include an **example SQL skeleton** when filtering is non-trivial (`usage_unit='DBU'`, `deleted_at IS NULL`, etc.).

---

## See also

- [`QUERY_HISTORY_SCENARIOS.md`](QUERY_HISTORY_SCENARIOS.md) — the deeper "who / what / when ran" log
- [`NODE_POOL_SCENARIOS.md`](NODE_POOL_SCENARIOS.md) — the infra-utilization counterpart
- [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) — billing ⨯ query ⨯ meta scenarios
- `docs/features_grouped/COMPUTE.md` — compute / billing technical deep dive
