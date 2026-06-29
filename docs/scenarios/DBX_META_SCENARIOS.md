# Unity Catalog Meta — Enterprise Scenarios & Questions

A field guide to what every department in a large enterprise can learn from
`databricks_meta` — the flat snapshot of Unity Catalog metadata produced by
the **Extractor** service (`extractor/meta_extractor.py`, output table
`databricks_meta` in Postgres, UI: **Meta Explorer**).

The catalog is grouped by role so a business user can jump straight to
"Executive", a steward to "Catalog Governance", and so on. A final section
lists cross-cutting questions that involve multiple roles collaborating on
the same query.

---

## 0. Which app pages back these scenarios

| App page (sidebar path) | What it answers | Backed by |
|---|---|---|
| **Meta Explorer → Overview** | Catalog / database / table / column counts, last-extract timestamp, catalog and database rollup tables, full-text search across the snapshot, bulk export of catalogs / tables / columns to CSV / XLSX. | `databricks_meta` |
| **Meta Explorer → Lineage — Tables / Columns** | Sister surface on `lineage_*` rollups — see [`LINEAGE_SCENARIOS.md`](LINEAGE_SCENARIOS.md). | `lineage_table_edges`, `lineage_column_edges` |
| **Meta Explorer → Audit, Node Pool** | Adjacent surfaces — see [`AUDIT_SCENARIOS.md`](AUDIT_SCENARIOS.md), [`NODE_POOL_SCENARIOS.md`](NODE_POOL_SCENARIOS.md). | `audit_events`, `assistant_events`, `system.compute.*` |

Endpoints live under `/api/meta/*` — see `backend/routers/meta_explorer.py`.

---

## 1. Why this table is a goldmine

`databricks_meta` is a per-day denormalized snapshot of **everything in
every accessible Unity Catalog catalog** — one row per
`(catalog, database, table, column)`. It is simultaneously:

- A **governance ledger** (who owns what, what's documented, what isn't)
- A **PII / sensitive-data registry** (columns named like `ssn`, `dob`,
  `email`, `credit_card`, `mrn`, `diagnosis`, …)
- A **modeling map** (canonical-key reuse, dim/fact distribution, wide
  tables, snowflake hubs)
- A **schema-drift detector** (`as_of` lets you diff today vs last week)
- A **bus-factor probe** (owner concentration per catalog / schema)
- A **stewardship coverage report** (% of columns/tables with a comment)

Combined with `qi_statement_tables` (Query Profiler) you get **two-way
attribution**: meta knows what *exists*, qi knows what's *used*. Their
intersection is the most valuable subset of the lakehouse; their
disjoint sets are the cleanup queue.

---

## 2. Column cheat sheet

| Bucket | Columns | Lets you answer |
|---|---|---|
| **Hierarchy** | `catalog`, `database`, `table_name`, `col_name` | Where the object lives (3-part name + the column inside it). |
| **Type** | `data_type`, `table_type` | What the column holds (`STRING`, `BIGINT`, `DECIMAL(18,4)`, …) and whether the parent is `MANAGED` / `EXTERNAL` / `VIEW` / `MATERIALIZED_VIEW` / `FOREIGN`. |
| **Documentation** | `comment`, `table_comment` | Column-level and table-level comments from Unity Catalog. NULL means "undocumented". |
| **Ownership** | `table_owner` | Principal that owns the table (email, group, or service principal). NULL on catalogs that don't expose the column (e.g. hive_metastore). |
| **Time** | `as_of` | The date the meta was crawled. Use `MAX(as_of)` for "last extract" KPIs; compare two `as_of` to detect drift. |
| **Isolation** | `data_origin`, `deleted_at` | `'real'` vs `'demo'` partition + soft-delete; the Meta Explorer API filters on these per user. |

> Tip: `LOWER(col_name) LIKE '%foo%'` is the bread-and-butter probe. The
> column is indexed so the query is fast even on millions of rows.

---

## 3. How to read the scenarios

Each scenario has the form:

> **Q.** The question, phrased the way the persona would ask it.
> *Needs:* columns / joins required.
> *Why it matters:* what the answer changes.

For complex scenarios, an example SQL skeleton is included so the
agentic system has a known-good template to imitate.

---

## 4. Platform / IT / Lakehouse Admin

The person on-call for "the platform is sprawling." Cares about footprint,
hot-spots, table-type distribution, and undocumented objects.

### 4.1 Footprint

**Q.** How big is our Unity Catalog right now — catalogs / schemas / tables / columns?
*Needs:* `COUNT(DISTINCT catalog)`, `COUNT(DISTINCT catalog||'.'||database)`, `COUNT(DISTINCT 3-part name)`, `COUNT(*)`.
*Why it matters:* baseline for every other measurement. Drives onboarding capacity planning.

**Q.** Per-catalog headcount: how many schemas, tables, and columns live in each catalog?
*Needs:* `catalog`, grouped distinct counts.
*Why it matters:* spots runaway catalogs that should be split, and empty catalogs that should be archived.

### 4.2 Object-type distribution

**Q.** What's the breakdown of MANAGED vs EXTERNAL vs VIEW vs MATERIALIZED_VIEW across the platform?
*Needs:* `table_type`, distinct table count.
*Why it matters:* high EXTERNAL count → storage governance lives in the cloud bucket, not UC. High MV count → recompute cost to monitor.

```sql
SELECT table_type, COUNT(DISTINCT catalog || '.' || database || '.' || table_name) AS tables
FROM databricks_meta WHERE deleted_at IS NULL
GROUP BY 1 ORDER BY tables DESC;
```

### 4.3 Schema density

**Q.** Which schemas have the most tables? Which catalogs have the most schemas?
*Needs:* group by `(catalog, database)`, distinct tables.
*Why it matters:* schema sprawl is a chronic anti-pattern; a 500-table schema is unsearchable.

### 4.4 Wide-table smell

**Q.** Which tables have > 100 columns? Which have > 250?
*Needs:* group by 3-part name; `COUNT(col_name)` ≥ 100.
*Why it matters:* very wide tables hint at god-tables / EAV / dumped CSVs and usually indicate a missed normalization opportunity.

### 4.5 Drift (requires ≥2 as_of snapshots)

**Q.** Which tables were added / removed since the last meta extract?
*Needs:* compare distinct 3-part names across two `as_of` values.
*Why it matters:* unannounced churn → broken dashboards, broken jobs.

---

## 5. Security / Compliance / Privacy

Cares about PII exposure, undocumented sensitive columns, and unowned tables.

### 5.1 PII heuristics

**Q.** Which tables have columns whose names suggest PII?
*Needs:* `LOWER(col_name) ~* '(ssn|social|dob|birth|email|phone|address|zip|postal|credit_card|cc_num|passport|license|mrn|patient|diagnosis|race|religion|nationality)'`.
*Why it matters:* first pass for the DLP review queue. Pair with classification tags via Unity Catalog `column_tags`.

```sql
SELECT catalog, database, table_name, col_name, data_type
FROM databricks_meta
WHERE deleted_at IS NULL
  AND LOWER(col_name) ~* '(ssn|dob|birth|email|phone|credit_card|passport|mrn|patient|diagnosis)';
```

### 5.2 Ownerless tables

**Q.** Which tables have NULL `table_owner`?
*Needs:* `table_owner IS NULL` grouped by `(catalog, database, table_name)`.
*Why it matters:* an unowned table is unauditable. Routing it to a steward is the lowest-effort governance win.

### 5.3 Owner concentration / bus factor

**Q.** Per catalog, which owners hold > 20% of the tables?
*Needs:* group by `(catalog, table_owner)`; share of catalog total.
*Why it matters:* concentration is a single-point-of-failure; departures stall data product roadmaps.

### 5.4 Undocumented sensitive columns

**Q.** Among PII-named columns (5.1), how many have NO comment? How many have NO `table_comment`?
*Needs:* PII heuristic + `comment IS NULL`.
*Why it matters:* "what is this column" must be answerable from metadata alone for any sensitive field, by law in many jurisdictions.

### 5.5 Cross-catalog same-name drift

**Q.** Where does the same column name appear with different `data_type`s across catalogs?
*Needs:* group by `col_name`, count distinct `data_type`.
*Why it matters:* `account_id STRING` in one place and `account_id BIGINT` in another causes silent join failures and misaligned dashboards.

---

## 6. Catalog Governance / Data Stewardship

Cares about documentation coverage, naming conventions, and steward workload.

### 6.1 Documentation coverage

**Q.** What % of tables have a non-NULL `table_comment` per catalog?
*Needs:* group by `catalog`, count distinct tables vs tables with `table_comment IS NOT NULL`.
*Why it matters:* the headline KPI for any data-stewardship program. Goal: 100%.

**Q.** What % of columns have a non-NULL `comment`?
*Needs:* `comment IS NOT NULL` share per catalog or per table_type.
*Why it matters:* column-level documentation is where the actual business knowledge lives.

### 6.2 Steward workload

**Q.** Per owner, how many tables and how many of them are undocumented?
*Needs:* group by `table_owner`, count tables, count `table_comment IS NULL`.
*Why it matters:* concretely turns the documentation backlog into a routable list with assignees.

### 6.3 Naming convention adherence

**Q.** Which tables follow `dim_` / `fact_` / `bridge_` / `stg_` / `raw_` prefixes? Which don't?
*Needs:* `LOWER(table_name) LIKE 'dim_%'` etc.
*Why it matters:* convention drift makes self-service discovery harder. Helpful as a refactor backlog.

### 6.4 Empty schemas

**Q.** Which schemas exist but have zero tables in this snapshot?
*Needs:* compare schemas via `SHOW SCHEMAS` (live) vs distinct `(catalog, database)` in meta.
*Why it matters:* empty schemas often outlive their projects; candidates for deletion.

---

## 7. Data Engineering / Modeling

Cares about reusable keys, anti-patterns, and refactor opportunities.

### 7.1 Canonical-key reuse

**Q.** Which column names appear across the most tables platform-wide?
*Needs:* group by `col_name`, count distinct 3-part names.
*Why it matters:* the natural-key dictionary. `customer_id`, `account_id`, `order_id`, etc., should be defined once and joined everywhere.

```sql
SELECT col_name, COUNT(DISTINCT catalog || '.' || database || '.' || table_name) AS tables
FROM databricks_meta
WHERE deleted_at IS NULL
GROUP BY 1
HAVING COUNT(DISTINCT catalog || '.' || database || '.' || table_name) >= 5
ORDER BY tables DESC LIMIT 50;
```

### 7.2 Data-type inconsistency

**Q.** For each high-reuse column (≥5 tables), how many distinct `data_type` values does it have?
*Needs:* group by `col_name`, count distinct `data_type`.
*Why it matters:* finds the `id STRING` vs `id BIGINT` time-bombs before they cause a missed join.

### 7.3 View dependency footprint

**Q.** What share of objects are views? Per catalog, how many views vs base tables?
*Needs:* `table_type = 'VIEW'` distinct count vs `'MANAGED' | 'EXTERNAL'`.
*Why it matters:* view-heavy estates point to lots of compute hidden in `CREATE VIEW`; pair with Query Profiler to find slow views.

### 7.4 Wide-tables refactor candidates

**Q.** Top 20 widest tables (most columns)?
*Needs:* group by 3-part name; `COUNT(col_name)`.
*Why it matters:* the refactor queue. Usually 1 such table per business domain.

### 7.5 STRUCT / MAP usage

**Q.** Which tables use STRUCT or MAP columns?
*Needs:* `LOWER(data_type) LIKE 'struct%' OR LOWER(data_type) LIKE 'map<%'`.
*Why it matters:* nested types break naive BI tools and require flattening logic — surface them so the integration team isn't surprised.

---

## 8. Analytics / BI / Self-Service

Cares about discoverability — "where do I find the customer table?"

### 8.1 Dim / fact inventory

**Q.** List every `dim_*` table with column counts and owner.
*Needs:* `table_name LIKE 'dim_%'`, joined with `COUNT(col_name)`.
*Why it matters:* the starter pack for a new dashboard author.

### 8.2 Date columns

**Q.** Which tables have a `created_at` / `updated_at` / `event_date` style column?
*Needs:* `LOWER(col_name) ~* '(_at$|_date$|^event_date|^as_of|^business_date)'`.
*Why it matters:* time series candidates; drives the "available date columns" picker in the BI layer.

### 8.3 Comment-rich tables (good docs)

**Q.** Which tables have BOTH a populated `table_comment` AND `>= 80% of columns` with a comment?
*Needs:* per-table: `MAX(table_comment) IS NOT NULL` plus `share of COUNT(comment) / COUNT(*)`.
*Why it matters:* a discoverable subset for self-service users; surface these first in chatbot answers.

---

## 9. Executive / Data Office

Cares about KPIs you can put on one slide.

### 9.1 Documentation KPI

**Q.** What % of all tables in the company have a `table_comment`?
*Needs:* distinct 3-part name with `table_comment IS NOT NULL` ÷ total.
*Why it matters:* the one slide-headline number.

### 9.2 Ownership KPI

**Q.** What % of tables have an explicit owner (`table_owner IS NOT NULL`)?
*Needs:* distinct count where owner non-NULL ÷ total.
*Why it matters:* governance maturity score.

### 9.3 Catalog growth

**Q.** How many tables existed last month vs this month? Per catalog?
*Needs:* two `as_of` snapshots.
*Why it matters:* track lakehouse adoption velocity.

### 9.4 Concentration

**Q.** What % of all tables sit in the top 5 catalogs?
*Needs:* `RANK()` catalogs by table count; share-of-total.
*Why it matters:* indicates whether the lakehouse is concentrated (good for stewardship) or scattered (governance overhead).

---

## 10. Cross-cutting

### 10.1 Type histogram

**Q.** What does the platform's column-type distribution look like?
*Needs:* group by `data_type`, count.
*Why it matters:* fingerprint of the data model. A 90% STRING + 5% DECIMAL distribution tells you no one runs analytics on this catalog (everything's a string).

### 10.2 Meta ↔ Query-Profiler intersection (with `qi_*`)

**Q.** Of all tables in meta, which ones are NEVER queried (per Query Profiler)?
*Needs:* anti-join `databricks_meta` 3-part name vs `qi_statement_tables.fully_qualified`.
*Why it matters:* the "zombie tables" candidate list — exist but generate no value. Deletion saves storage and review effort.

**Q.** Of all tables that are queried, how many have NO documentation?
*Needs:* intersection of `qi_statement_tables` and `databricks_meta` where `table_comment IS NULL`.
*Why it matters:* prioritized docs backlog — document what people actually use first.

### 10.3 Per-data-product audit

**Q.** Given a domain keyword (`patient`, `sales`, `marketing`, `claims`, …), how many tables, how many columns, which owners, how many undocumented?
*Needs:* `LOWER(catalog||'.'||database||'.'||table_name) LIKE '%keyword%'` aggregations.
*Why it matters:* the executive's "tell me about Project X" question, answered from metadata alone.

### 10.4 Top-N comments by length

**Q.** Which comments are exceptionally long? Which are suspiciously short ("yes", "tbd", "see above")?
*Needs:* `LENGTH(comment)` percentiles + regex filter for placeholder strings.
*Why it matters:* finds documentation theater — comments that exist but say nothing.

---

## Wrap-up

Everything above uses only the single `databricks_meta` table. The same SQL is exposed via the Meta Explorer API (`/api/meta/*` — see `backend/routers/meta_explorer.py`) and rendered in the **Meta Explorer** menu in the app.

Next-step extensions worth considering:

1. **Tagging** — JOIN Unity Catalog `system.information_schema.column_tags` for classification-aware filtering.
2. **Lineage** ✅ — **shipped.** `system.access.table_lineage` and `system.access.column_lineage` are now extracted, ingested, and surfaced via the **Meta Explorer → Lineage** sub-pages. See [`../features_grouped/LINEAGE.md`](../features_grouped/LINEAGE.md) for schema, dashboards, and the chunked-extraction strategy, and [`LINEAGE_SCENARIOS.md`](LINEAGE_SCENARIOS.md) for the persona-first catalogue. The `meta ⋈ lineage` join enables exactly the questions section 10.2 hints at (orphan tables, terminal nodes, etc.) — the Tables dashboard already shows these out of the box.
3. **Activity** — JOIN to `qi_statement_tables` (Query Profiler) for the meta-∩-activity pairing referenced in section 10.2. See [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) for the worked-out skeletons.
4. **LLM-assisted documentation drafts** — for each undocumented table/column, use the table name + column names + sample rows to draft a comment, then route to the steward for approval.
5. **Diff feed** — every successful Full/Incremental extract appends a new `as_of`. Compute table/column add/remove between consecutive snapshots and publish to a Slack/Teams "lakehouse drift" channel.

---

## See also

- [`LINEAGE_SCENARIOS.md`](LINEAGE_SCENARIOS.md) — the sister catalogue for lineage questions
- [`QUERY_HISTORY_SCENARIOS.md`](QUERY_HISTORY_SCENARIOS.md) — query-side companion (catalog-usage / table activity)
- [`CROSS_DOMAIN_SCENARIOS.md`](CROSS_DOMAIN_SCENARIOS.md) — meta × query × lineage × billing × audit joins
- [`../features_grouped/LINEAGE.md`](../features_grouped/LINEAGE.md) — technical deep-dive on lineage extraction
- [`../DATA_DICTIONARY.md`](../DATA_DICTIONARY.md) — column-level reference
