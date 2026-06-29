# Lineage — Enterprise Scenarios & Questions

A field guide to what every role can learn from `system.access.table_lineage`
and `system.access.column_lineage` — the two governance ledgers behind the
**Meta Explorer → Lineage** sub-pages (Tables and Columns).

Lineage is the answer to *"if I change X, what breaks?"* and *"where did
this number come from?"* — the two questions every data steward and SRE
needs to answer on demand.

---

## 1. Which app pages back these scenarios

| App page (sidebar path) | What it answers | Backed by |
|---|---|---|
| **Meta Explorer → Lineage — Tables** | Per-table fan-in / fan-out graph (upstream + downstream neighbours), stats strip (table-edge count, distinct entities, direct vs indirect, R/W/RW counts), Tops (top sources, top targets, top entities, orphan tables, terminal tables), search bar. | `lineage_table_edges` (rolled-up from `system.access.table_lineage`) |
| **Meta Explorer → Lineage — Columns** | Per-(table, column) fan-in / fan-out, Tops (most-fanned-out columns, most-depended-on columns, tables by column-edge count, top entities), search. | `lineage_column_edges` (rolled-up from `system.access.column_lineage`) |
| **Meta Explorer → Overview** | Stats strip header showing lineage roll-up totals (table edges, column edges, last event). | Lineage stats endpoint |

Endpoints live under `/api/meta/lineage/*` — see
`backend/routers/lineage.py`. The extractor that builds the
table/column-edge rollups (one row per `(source, target)` pair with
aggregated counts and timestamps) lives in `backend/extract/lineage.py`
and is documented in `docs/features_grouped/LINEAGE.md`.

---

## 2. Why this table is a goldmine

System-level lineage in Unity Catalog records **every read and write
between a (source, target) pair**, along with the **entity** that
triggered it (job, dashboard, notebook, pipeline, Genie space). It is
simultaneously:

- A **dependency graph** (who produces / who consumes each table)
- A **blast-radius oracle** ("if I deprecate T, what breaks?")
- A **provenance trail** ("where did the number in this dashboard come from?")
- An **orphan detector** (no upstream → looks like raw landing; no downstream → never read)
- A **bus-factor probe** at the entity level (one job feeds 80% of dashboards)
- A **shadow-IT detector** (jobs no one talks about, but in lineage)

Column lineage adds **field-level granularity** — useful for "is this PII
column ever shown in a dashboard", "where does `customer_email` end up
downstream", and similar privacy / data-product questions.

---

## 3. Column cheat sheet

### `system.access.table_lineage`

| Bucket | Columns | Lets you answer |
|---|---|---|
| **Source** | `source_table_full_name`, `source_table_catalog`, `source_table_schema`, `source_type` | What was read. |
| **Target** | `target_table_full_name`, `target_table_catalog`, `target_table_schema`, `target_type` | What was written. |
| **Entity** | `entity_type` (JOB / DASHBOARD / NOTEBOOK / PIPELINE / GENIE / QUERY), `entity_id`, `entity_run_id` | What triggered the dependency. |
| **Event** | `event_time`, `event_date` | When. Use for "is this still active". |
| **Direction** | derived: `direct` vs `indirect` (transitive). | `direct` is what UC emitted; `indirect` is what we computed in the rollup for query convenience. |
| **Type** | derived: R-only / W-only / RW | When a job both reads from and writes to the same table (uncommon but flag-worthy). |

### `system.access.column_lineage`

Same shape, plus `source_column_name` and `target_column_name`.

> Tip: a single (source, target) pair often appears thousands of times
> in raw events. The Meta Explorer is built on a **rollup** — one row per
> `(source, target, entity_type, [direct/indirect])` with aggregated
> counts and `last_event`. Use the rollup unless you're doing forensics.

---

## 4. How to read the scenarios

> **Q.** The question, phrased the way the persona would ask it.
> *App page:* where to click. *Needs:* columns / joins required.
> *Why it matters:* what the answer changes.

---

## 5. Platform / IT / Lakehouse Admin

### 5.1 Footprint

**Q.** How big is our lineage graph? How many table edges, column edges, distinct entities?
*App page:* Meta Explorer → Lineage (header strip).
*Needs:* `COUNT(*)` on rollup; `COUNT(DISTINCT entity_id)`.
*Why it matters:* baseline for every other lineage measurement.

### 5.2 Orphan and terminal tables

**Q.** Which tables have no upstream sources in our lineage data? (Possible raw landings.)
*App page:* Lineage → Tables → Tops → "Orphan tables".
*Needs:* tables that appear only as `source_table_full_name` and never as `target_table_full_name`.
*Why it matters:* every orphan should be one of: a true raw landing, a manual-load table, or shadow IT. Reviewing the list separates the three.

**Q.** Which tables have no downstream consumers?
*App page:* Lineage → Tables → Tops → "Terminal tables".
*Needs:* the mirror.
*Why it matters:* dead-end tables are either KPI surfaces (legitimate) or zombie outputs (cleanup queue). Cross-ref with `qi_*` (Query Profiler) to be sure — see Cross-cutting.

```sql
SELECT t.table_full_name
FROM (SELECT DISTINCT target_table_full_name AS table_full_name FROM lineage_table_edges) t
LEFT JOIN (SELECT DISTINCT source_table_full_name FROM lineage_table_edges) s
  ON s.source_table_full_name = t.table_full_name
WHERE s.source_table_full_name IS NULL;
```

### 5.3 Entity-type mix

**Q.** What share of lineage events come from Jobs vs Dashboards vs Notebooks vs Pipelines vs Genie?
*App page:* Lineage → Tables → header pie ("by entity type").
*Needs:* group by `entity_type`.
*Why it matters:* heavy Notebook share → most of the org is in interactive mode; heavy Job share → mature pipeline maturity.

### 5.4 Direct vs indirect

**Q.** What share of edges are direct (Unity Catalog emitted) vs indirect (transitively computed)?
*App page:* Lineage → stats strip.
*Needs:* derived `direct` flag.
*Why it matters:* indirect edges are an *inference* convenience for the UI — sanity-check that the share isn't dominated by indirect for a critical question.

---

## 6. Data Engineering / Modeling

### 6.1 Fan-in and fan-out

**Q.** Which tables have the most upstream sources? (Wide ingest surface — usually a fact table.)
*App page:* Lineage → Tables → Tops → "Tables with most upstream tables".
*Needs:* group by `target_table_full_name`, count distinct `source_table_full_name`.

**Q.** Which tables have the most downstream consumers? (The most-depended-on tables.)
*App page:* Lineage → Tables → Tops → "Tables with most downstream tables".
*Needs:* group by `source_table_full_name`, count distinct `target_table_full_name`.
*Why it matters:* these are your **bus-factor tables** — if they break, everything downstream breaks. They deserve schema-evolution discipline.

### 6.2 Cycle detection

**Q.** Are there any cycles? (Shouldn't exist; a sanity check.)
*Needs:* `WITH RECURSIVE` graph traversal on (source, target).
*Why it matters:* cycles in a DAG ⇒ the lineage data is wrong or someone's doing something exotic.

### 6.3 Hub tables

**Q.** Which tables sit on both sides — high read AND high write — i.e. core staging hubs?
*App page:* Lineage → Tables → Tops → top sources + top targets, intersect.
*Needs:* tables appearing in both top-source and top-target lists.
*Why it matters:* these are the **staging hubs** of your lakehouse — they justify dedicated ownership.

### 6.4 Pipeline detective work

**Q.** For pipeline P, what's its full input + output set?
*App page:* Lineage → Tables → search by entity name; click into the graph view.
*Needs:* `entity_id = P` grouped by source/target.

---

## 7. Catalog Governance / Data Stewardship

### 7.1 Ownership × lineage

**Q.** For tables in the top-50 most-depended-on list, do they all have explicit `table_owner` set?
*App page:* Lineage → Tops + Meta Explorer table-detail.
*Needs:* join lineage rollup × `databricks_meta` on full table name; filter `table_owner IS NULL`.
*Why it matters:* an ownerless table being depended on by 200 downstream consumers is a governance emergency.

### 7.2 Documentation × lineage

**Q.** For tables in the top-50 most-read list, what % have a `table_comment`?
*Needs:* lineage × meta join.
*Why it matters:* the most-used tables should be the best-documented. They usually aren't.

### 7.3 Sensitive data lineage

**Q.** A column flagged as PII (heuristic on name or via UC tags) — what downstream tables / dashboards consume it?
*App page:* Lineage → Columns → search for the column → fan-out.
*Needs:* PII heuristic on `databricks_meta.col_name`; then column-graph traversal.
*Why it matters:* the privacy team's most-asked question; surfaces hidden exposure.

---

## 8. BI / Analytics

### 8.1 Dashboard provenance

**Q.** Where does dashboard D get its data from? (Full ancestor tree.)
*App page:* Lineage → Tables → search for entity `D`.
*Needs:* `entity_type='DASHBOARD'` filter + transitive traversal of source tables.

### 8.2 Shared upstream

**Q.** Which tables feed > 5 distinct dashboards?
*Needs:* group by source table, count distinct downstream entities with `entity_type='DASHBOARD'`.
*Why it matters:* candidate for dedicated SLA / monitoring.

---

## 9. Data Science / ML

**Q.** For ML model M, what features (tables/columns) does it consume? (Feature provenance.)
*App page:* Lineage → Tables → search for the model job entity.
*Needs:* `entity_id` = model training job → upstream source tables.

**Q.** Which feature tables fan out to multiple model-training jobs? (Feature reuse.)
*Needs:* `entity_type IN ('JOB','PIPELINE')` + heuristic on entity name like `train_`/`model_`.

---

## 10. Security / Governance / Compliance

### 10.1 Data-exfil detective

**Q.** Are there any lineage edges into external sinks (foreign tables, external locations)?
*Needs:* `target_type IN ('EXTERNAL','FOREIGN')`.
*Why it matters:* data leaving the lakehouse boundary deserves a review.

### 10.2 Cross-catalog flows

**Q.** Which catalog-to-catalog flows exist? (Sometimes a sign of a desensitization or a violation.)
*Needs:* compare `source_table_catalog` vs `target_table_catalog`; group flows.

### 10.3 Column-level PII propagation

**Q.** Which downstream columns are derived from `customer.ssn`?
*App page:* Lineage → Columns → search `customer.ssn` → downstream graph.
*Needs:* column lineage traversal.
*Why it matters:* if SSN ends up in a non-PII-flagged downstream table, you've got a classification gap.

---

## 11. Executive / Data Office

### 11.1 Connectivity KPI

**Q.** What % of tables in the catalog have at least one inbound or outbound lineage edge?
*Needs:* count distinct table names in lineage; divide by `databricks_meta` total.
*Why it matters:* low connectivity means most tables are unused — likely cleanup candidates.

### 11.2 Entity catalog

**Q.** How many distinct jobs / dashboards / notebooks / pipelines / Genie spaces have we observed?
*App page:* Lineage → Tables → header stats.
*Needs:* `COUNT(DISTINCT entity_id)` grouped by `entity_type`.
*Why it matters:* the platform's "active surface" — useful for board-deck adoption numbers.

---

## 12. Cross-cutting

### 12.1 Lineage ⨯ Meta — orphan tables that are ALSO never queried

**Q.** Tables in `databricks_meta` with **zero** lineage edges AND **zero** `qi_statement_tables` references.
*App page:* Meta Explorer overview cross-ref (the "zombie candidate" list).
*Needs:* anti-joins meta vs lineage vs qi tables.
*Why it matters:* the cleanest deletion candidates — pay for storage, generate no value. See [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) §3.

### 12.2 Lineage ⨯ Audit — who triggered a sensitive flow

**Q.** A flow into PII tables — who triggered the entity that wrote there?
*Needs:* lineage `target=PII` → entity_id → `audit_events` action where the entity was launched. See [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) §5.

### 12.3 Lineage ⨯ Billing — cost-per-output

**Q.** For each top output table, what's the rolling weekly cost of producing it?
*Needs:* lineage → entity_id → billing via job_id / pipeline_id / dashboard_id. See [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) §6.

### 12.4 Deprecation blast radius

**Q.** If I deprecate table T tomorrow, who breaks?
*App page:* Lineage → Tables → search T → fan-out graph + list of impacted entities (jobs + dashboards + notebooks).
*Needs:* transitive `descendants(T)`; cross-ref entity owners (when known).
*Why it matters:* every deprecation review starts here.

---

## 13. Limitations & gotchas

- **Lineage events lag UC writes by minutes** — fresh data may not have edges yet. Use `last_event` to gauge freshness.
- **The rollup loses event-time granularity** — for forensic "exactly which run" questions, hit the raw `system.access.{table,column}_lineage` directly (not the dashboard rollup).
- **`entity_id` only identifies a job / dashboard / etc — not who triggered it**. To get the human / SP, join `audit_events` on `entity_id` (best-effort).
- **Genie / AI/BI lineage rows are first-class** — they show up with `entity_type='GENIE'`. This is the cleanest way to measure Genie's footprint at the table level.
- **Indirect edges are inferred, not authoritative.** If a question must be authoritative, filter `direct_edges` only.
- **Catalog comparisons assume Unity Catalog naming** — hive_metastore objects may appear with NULL `catalog`; treat them as "unmanaged".

---

## 14. How to add a new lineage scenario

1. Identify the **role** asking it.
2. Phrase the question the way they'd say it.
3. Decide whether it's table-level (graph between 3-part names) or column-level (graph between `(table, column)` pairs).
4. List the **needed traversal** — direct only? transitive? bounded depth?
5. Note the **app page** that should serve it; if none, that's a roadmap item.

---

## See also

- `docs/features_grouped/LINEAGE.md` — technical deep-dive on the lineage rollups
- [`DBX_META_SCENARIOS.md`](DBX_META_SCENARIOS.md) §10 — meta-aware lineage questions
- [`QUERY_HISTORY_SCENARIOS.md`](QUERY_HISTORY_SCENARIOS.md) §17 — query × lineage cross-cuts
- [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) — billing ⨯ query ⨯ meta ⨯ lineage ⨯ audit
