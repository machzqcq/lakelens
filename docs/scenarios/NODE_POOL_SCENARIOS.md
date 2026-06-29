# Node Pool & Compute Infrastructure — Enterprise Scenarios & Questions

A field guide to what every role can learn from the five
`system.compute.*` tables — `node_timeline`, `warehouse_events`,
`instance_events`, `node_types`, and `instance_pools`. These are the
tables behind **Meta Explorer → Node Pool**.

If billing tells you *how much* the platform cost, and query history
tells you *what was run*, the node-pool family tells you **what
infrastructure actually ran underneath** — minute-by-minute CPU /
memory load, warehouse start/stop events, instance preemptions, the
hardware menu, and the warm-instance pools.

---

## 1. Which app pages back these scenarios

| App page (sidebar path) | What it answers | Backed by |
|---|---|---|
| **Meta Explorer → Node Pool** | KPI strip (row counts per table, distinct clusters / instances / warehouses / pools, last-event timestamps), event-type breakdowns, node-type category mix; sub-sections for Utilization, Warehouse Events, Instance Events, Node Types, Instance Pools. | `node_timeline`, `warehouse_events`, `instance_events`, `node_types`, `instance_pools` |

Endpoints live under `/api/meta/node-pool/*` — see
`backend/routers/node_pool.py`. The extractor lives in
`backend/extract/node_pool.py` and is documented in
`docs/features_grouped/COMPUTE.md`.

---

## 2. Why this family is a goldmine

| Table | What it records | Cadence |
|---|---|---|
| `node_timeline` | Per-instance CPU / memory utilization samples for every cluster instance. | One sample per minute (≈) per instance. **High volume** — millions of rows / day at scale. |
| `warehouse_events` | Lifecycle events for SQL Warehouses (STARTED / STOPPED / RUNNING / STOPPING / FAILED). | One row per state transition. |
| `instance_events` | Lifecycle events for individual cluster nodes (PROVISIONED / TERMINATED / PREEMPTED). | One row per state transition. |
| `node_types` | Reference catalog of available node SKUs (vCPU, memory, GPU, family). | Small (~hundreds of rows). |
| `instance_pools` | Configured warm-instance pools (min idle, max capacity, autotermination). | Tiny (one row per pool). |

Together they answer:

- **Utilization** — are we actually using the hardware we're paying for?
- **Autoscaling efficiency** — how long do warehouses sit warming up / cooling down?
- **Preemption rate** — are spot/preemptible instances hurting us?
- **Pool sizing** — are warm instances saving us cold-start time, or just costing money?
- **Hardware mix** — what node families are dominant; are GPUs idle?

---

## 3. Column cheat sheet

### `node_timeline`
| Bucket | Columns | Lets you answer |
|---|---|---|
| **Identity** | `cluster_id`, `instance_id`, `workspace_id` | Where the sample came from. |
| **CPU** | `cpu_user_percent`, `cpu_system_percent`, `cpu_idle_percent`, `cpu_wait_percent`, `cpu_iowait_percent` | How busy the CPUs are. `user+system` is the actively-working fraction. |
| **Memory** | `mem_used_percent`, `mem_free_percent`, `swap_used_percent` | Memory pressure. High `swap_used_percent` is a near-OOM smell. |
| **Network** | `network_received_bytes`, `network_sent_bytes` | Per-sample throughput. |
| **Time** | `sample_time` | The minute-level grain. |

### `warehouse_events`
| Bucket | Columns | Lets you answer |
|---|---|---|
| **Identity** | `warehouse_id`, `workspace_id` | Which warehouse. |
| **Event** | `event_type` (STARTED / STOPPING / STOPPED / RUNNING / FAILED), `event_time` | The state transition. |
| **Sizing** | `cluster_count` | How many backing clusters at this moment. |

### `instance_events`
| Bucket | Columns | Lets you answer |
|---|---|---|
| **Identity** | `cluster_id`, `instance_id`, `workspace_id`, `instance_pool_id` | The cluster + the physical instance + (optional) the pool it came from. |
| **Event** | `event_type` (PROVISIONED / TERMINATED / PREEMPTED), `event_time` | Lifecycle transition. |
| **Hardware** | `node_type` | The SKU the instance had. |

### `node_types`
| Bucket | Columns | Lets you answer |
|---|---|---|
| **SKU** | `node_type`, `core_count`, `memory_mb`, `gpu_count`, `category` | Hardware specs. `category` is a UC-emitted free-text family marker (some clouds don't populate it — extractor tolerates NULL). |

### `instance_pools`
| Bucket | Columns | Lets you answer |
|---|---|---|
| **Pool** | `instance_pool_id`, `instance_pool_name`, `node_type`, `min_idle_instances`, `max_capacity`, `idle_instance_autotermination_minutes`, `enable_elastic_disk`, `workspace_id`, `create_time`, `change_time` | Pool config. |

> Tip: `instance_pools` may return `INSUFFICIENT_PERMISSIONS` on some
> orgs — the extractor tolerates this and the dashboard simply shows an
> empty list. It's not an error.

---

## 4. How to read the scenarios

> **Q.** The question, phrased the way the persona would ask it.
> *App page:* where to click. *Needs:* columns / joins required.
> *Why it matters:* what the answer changes.

---

## 5. Platform / IT / SRE

### 5.1 Cluster utilization snapshot

**Q.** Which clusters had average CPU < 25% AND average memory < 50% over the last week? (Over-provisioned.)
*App page:* Meta Explorer → Node Pool → Utilization (sortable).
*Needs:* `cluster_id` grouped averages on `cpu_user_percent + cpu_system_percent` and `mem_used_percent`.
*Why it matters:* the clean rightsizing list. Pair with `clusters.worker_count` × `worker_node_type` for a "drop one worker" recommendation.

```sql
SELECT cluster_id,
       AVG(cpu_user_percent + cpu_system_percent) AS avg_cpu_active,
       AVG(mem_used_percent) AS avg_mem,
       MAX(cpu_user_percent + cpu_system_percent) AS peak_cpu,
       COUNT(*) AS samples
FROM node_timeline
WHERE sample_time >= CURRENT_DATE - INTERVAL '7 days' AND deleted_at IS NULL
GROUP BY cluster_id
HAVING AVG(cpu_user_percent + cpu_system_percent) < 25 AND AVG(mem_used_percent) < 50
ORDER BY samples DESC LIMIT 50;
```

### 5.2 Memory pressure

**Q.** Which clusters spent > 20% of samples at > 90% memory used?
*App page:* Node Pool → Utilization (max memory column).
*Needs:* `mem_used_percent > 90` share per cluster.
*Why it matters:* OOM precursor — upsize or refactor the workload.

### 5.3 Swap usage

**Q.** Any clusters ever swapping? (Swap on Spark workers is pathological.)
*Needs:* `swap_used_percent > 1` filter.
*Why it matters:* almost always a misconfiguration; deserves immediate attention.

### 5.4 Preemption rate

**Q.** What share of instance terminations are PREEMPTED vs TERMINATED this week?
*App page:* Node Pool → Instance Events → by-event-type pie.
*Needs:* `instance_events.event_type` rollup.
*Why it matters:* preemptions = spot eviction = compute cost savings but with reliability friction. Track the ratio.

### 5.5 Cold starts

**Q.** How long do warehouses spend in STARTING → RUNNING transitions?
*App page:* Node Pool → Warehouse Events; cross-ref Query Profiler → Platform → Capacity Queueing.
*Needs:* `warehouse_events` per `warehouse_id`, diff `STARTED` → `RUNNING` timestamps.
*Why it matters:* the cold-start latency users see; affects "the platform feels slow" perception.

---

## 6. FinOps / Cost Engineering

### 6.1 Idle pools

**Q.** Which instance pools are oversized for actual demand?
*App page:* Node Pool → Instance Pools (config) + Instance Events (usage).
*Needs:* `instance_pools.min_idle_instances` × actual concurrent PROVISIONED instances from that pool.
*Why it matters:* `min_idle_instances=5` × $0.50/hour × 24h × 30d = $1,800/month per pool of pure idle spend.

### 6.2 Hardware mix

**Q.** What's the cost split GPU vs CPU this month?
*App page:* Compute Resources (Billing) + cross-ref Node Pool → Node Types.
*Needs:* `node_types.gpu_count > 0` joined billing.

### 6.3 Right-tier check

**Q.** Are we paying for r-family memory-optimized instances on clusters that average 25% memory?
*App page:* Node Pool → Utilization + Node Types.
*Needs:* `cluster_id` × `worker_node_type` × node-type family + memory utilization.
*Why it matters:* a one-line family swap (r5d → m5d) can drop cost 20-30% with no perf impact.

---

## 7. Capacity Planning / Autoscale Tuning

### 7.1 Autoscale efficiency

**Q.** For autoscaling clusters, what's the median time between PROVISIONED events?
*App page:* Node Pool → Instance Events.
*Needs:* per-cluster instance-event diffs.
*Why it matters:* short median = autoscale thrashing; long median = stable. Tune `min_workers` / `max_workers` accordingly.

### 7.2 Warehouse demand curve

**Q.** For each warehouse, build an hour-of-day demand curve from STARTED counts.
*App page:* Node Pool → Warehouse Events.
*Needs:* `warehouse_events` grouped by hour-of-day.
*Why it matters:* the input to per-warehouse auto-stop tuning. A warehouse that's hot 9am-5pm doesn't need a 60-minute auto-stop.

### 7.3 Pool autotermination tuning

**Q.** Which pools have idle instances autoterminating before they were reused?
*App page:* Node Pool → Instance Pools + Instance Events.
*Needs:* `instance_events.event_type='TERMINATED'` from a pool's instance ID range, with no nearby `PROVISIONED` re-use.
*Why it matters:* `idle_instance_autotermination_minutes` too low ⇒ users hit cold-start; too high ⇒ paying for idle.

---

## 8. Data Engineering / Cluster Owners

### 8.1 My cluster's profile

**Q.** For cluster X, what was its average CPU, memory, max CPU, peak memory over the last week?
*App page:* Node Pool → Utilization → search.
*Needs:* `node_timeline` filtered to cluster.

### 8.2 Hot vs cold runs

**Q.** Was last night's job-run on cluster X memory-bound or CPU-bound?
*Needs:* per-run window from `qi_statements.start_time/end_time` → `node_timeline` aggregate over that window.

### 8.3 GPU utilization

**Q.** For GPU clusters, what's the GPU utilization?
*Currently:* node_timeline does NOT include GPU metrics in the system table — only CPU/memory. GPU monitoring requires a sidecar (e.g. DCGM exporter to Prometheus). Note that in the dashboard.
*Why it matters:* a GPU cluster with 10% GPU utilization is the most expensive class of waste.

---

## 9. Hardware Inventory / Architecture

### 9.1 Node-type catalog

**Q.** What node types are available in our region / cloud?
*App page:* Node Pool → Node Types (with vCPU, memory, GPU columns).
*Needs:* `node_types` rows.

### 9.2 In-use node types

**Q.** Which node types are actively in use this month?
*App page:* Node Pool → Instance Events → top node_type.
*Needs:* `instance_events.node_type` distinct counts.
*Why it matters:* node-type breadth (>20) is a complexity smell; consolidating to 4-8 picks simplifies ops and pricing predictability.

### 9.3 Discontinued / deprecated node types

**Q.** Are any clusters still configured on a deprecated node type?
*Needs:* `clusters.driver_node_type / worker_node_type` ⨯ deprecation list.
*Why it matters:* deprecated SKUs often cost more for less, and may stop accepting new launches.

---

## 10. Executive / Data Office

### 10.1 Compute efficiency KPI

**Q.** What's our weighted-average CPU utilization across all clusters?
*Needs:* `node_timeline` averaged.
*Why it matters:* board-ready efficiency number. < 30% = a clear FinOps backlog.

### 10.2 Compute fleet size

**Q.** Distinct clusters, instances, warehouses observed this week vs last month.
*App page:* Node Pool → KPI strip.
*Needs:* distinct counts in `node_timeline` / `warehouse_events`.

---

## 11. Cross-cutting

### 11.1 Node-pool ⨯ Query Profiler — perf during a slow query

**Q.** Was cluster X memory-saturated during the slow query at 14:32?
*Needs:* `qi_statements.start_time/end_time` window → `node_timeline` aggregate over that window. See CROSS_DOMAIN §4.

### 11.2 Node-pool ⨯ Billing — utilization vs cost

**Q.** For each cluster, divide weekly billing $ by mean CPU utilization to compute $/CPU%. Find the worst offenders.
*Needs:* `billing_usage` per cluster × `node_timeline` averages. See CROSS_DOMAIN §6.

### 11.3 Node-pool ⨯ Audit — instance preemption timeline

**Q.** Match `instance_events.event_type='PREEMPTED'` to the audit cluster-restart action that followed.
*Needs:* `instance_events` ⨯ `audit_events.action_name='restartCluster'` on the same cluster_id ± 5min.

---

## 12. Limitations & gotchas

- **Volume is huge.** `node_timeline` produces millions of rows / day at scale. Always restrict by `sample_time` and (when possible) `cluster_id` before opening the table.
- **The dashboard utilization view samples** — it shows aggregates, not raw per-minute rows.
- **`category` on `node_types` may be NULL** on some clouds — the extractor casts NULL when the source column doesn't exist.
- **`instance_pools` may return `INSUFFICIENT_PERMISSIONS`** on some orgs (UC ACL); the extractor tolerates this and the dashboard just shows an empty pools list.
- **No GPU utilization** — `node_timeline` is CPU/memory only. GPU monitoring needs a separate sidecar.
- **Warehouse events lag the warehouse state** by 1-2 minutes — don't treat as real-time.
- **`instance_id` is not a cloud-provider machine identifier** — it's a Databricks-internal ID; do not cross-join to cloud-provider VM lists without translation.
- **Demo vs Real**: extracts produce a `data_origin` value; view-mode toggle filters.

---

## 13. How to add a new node-pool scenario

1. Identify the **role** asking it (SRE / FinOps / capacity / cluster owner / exec).
2. Phrase the question the way they'd say it.
3. Decide whether the answer needs **per-minute granularity** (timeline) or **event-level granularity** (warehouse_events / instance_events).
4. Name the **app page** that should serve it.
5. Include the **time window** explicitly — most node-pool scenarios are window-bounded and the timeline table is too large otherwise.

---

## See also

- `docs/features_grouped/COMPUTE.md` — technical deep-dive on extractor + tables
- [`BILLING_SCENARIOS.md`](BILLING_SCENARIOS.md) — the cost-side counterpart
- [`QUERY_HISTORY_SCENARIOS.md`](QUERY_HISTORY_SCENARIOS.md) §4 — capacity / queueing questions from the SQL side
- [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) — node-pool ⨯ billing / query / audit
