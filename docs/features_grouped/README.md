# Features — grouped by source schema

Per-feature deep-dives for the three system-table family extractions
that ship with the app. Each doc covers the schema, extraction shape,
dashboard, and chatbot integration for one family of tables.

| Doc | What it covers |
|---|---|
| [`AUDIT.md`](AUDIT.md) | `system.access.audit` + `system.access.assistant_events` — extraction (chunked weekly + 30-day defaults), schema mirror in `audit_events` / `assistant_events`, the Meta Explorer → Audit dashboard, view-mode scoping, and the chatbot grounding for "who did what" questions. |
| [`COMPUTE.md`](COMPUTE.md) | The `system.compute.*` node-pool family: `node_timeline` (per-minute utilisation — the heaviest table), `warehouse_events`, `node_types`, `instance_events` (sourced from `node_events`), and `instance_pools`. Per-table lookback knobs, the Meta Explorer → Node Pool dashboard, common ops questions. |
| [`LINEAGE.md`](LINEAGE.md) | `system.access.table_lineage` + `system.access.column_lineage` end-to-end: NULL-source / NULL-target event-class encoding, `entity_metadata` JSON, the Lineage Tables + Lineage Columns dashboards, depth-1 graph rendering, and `lineage_rollups` materialisation. |

---

Each doc is self-contained — read in any order. Common conventions
across all three:

- **`data_origin` / `deleted_at`** isolation columns on every row (see
  the technical README's View-Mode Isolation section).
- **Chunked weekly extraction** for the time-bounded tables, with
  per-table `*_days_back` knobs exposed in the Extract UI.
- **Meta Explorer dashboards** scoped by the caller's `viewing_data_mode`
  so Real ↔ Demo toggles cleanly.
