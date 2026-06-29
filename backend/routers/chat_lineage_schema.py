"""Inline schema metadata for the lineage tables.

Used by `routers/chat.py` to add `table_lineage`, `column_lineage`, and
`lineage_rollups` to the LLM context so the Chatbot can answer questions
about read/write graphs, job/notebook attribution, fan-in/fan-out, etc.

We keep this inline (rather than relying solely on the xlsx workbook) for
the same reason `chat_qi_schema.py` does: the workbook may not have been
regenerated since the lineage tables landed, and the LLM benefits from
the richer column descriptions + event-class semantics encoded here.

Authoritative Databricks reference:
  https://docs.databricks.com/aws/en/admin/system-tables/lineage
See also `docs/LINEAGE.md` for the dashboards-side story.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Three tables: table_lineage, column_lineage, lineage_rollups.
#
# Critical Databricks semantics encoded in descriptions:
#   * source_*  NULL + target_* NOT NULL  → write-only event (e.g. INSERT VALUES)
#   * source_*  NOT NULL + target_*  NULL → read-only event (e.g. SELECT)
#   * source_*  NOT NULL + target_*  NOT NULL → read-write event
#   * column_lineage drops events without a source (so write-only events
#     visible in table_lineage are ABSENT from column_lineage).
#   * direct_access=true means the source/target was directly referenced
#     by the statement; false means surfaced as a transitive dependency.
# ---------------------------------------------------------------------------

_TYPE_ENUM = "TABLE | PATH | VIEW | MATERIALIZED_VIEW | METRIC_VIEW | STREAMING_TABLE"
_ENTITY_TYPE_ENUM = (
    "NOTEBOOK | JOB | PIPELINE | DASHBOARD_V3 | DBSQL_DASHBOARD (deprecated) | DBSQL_QUERY"
)


_LINEAGE_COMMON_COLS = [
    {"name": "account_id", "type": "string"},
    {"name": "metastore_id", "type": "string", "description": "Unity Catalog metastore identifier."},
    {"name": "workspace_id", "type": "string", "description": "Joins to workspaces.workspace_id."},
    {"name": "event_time", "type": "timestamp", "description": "UTC."},
    {"name": "event_date", "type": "date", "description": "Partitioned upstream; filter on this for time windows."},
    {"name": "record_id", "type": "string", "description": "Per-row unique ID from Databricks."},
    {"name": "event_id", "type": "string", "description": "Shared across rows that came from the same statement (one query → many rows). Joinable across table_lineage / column_lineage."},
    {"name": "source_table_full_name", "type": "string",
     "description": "Three-part name catalog.schema.table. NULL when source is a path (then source_path is set), OR encodes a write-only event."},
    {"name": "source_table_catalog", "type": "string"},
    {"name": "source_table_schema", "type": "string"},
    {"name": "source_table_name", "type": "string"},
    {"name": "source_type", "type": "string", "description": f"Enum: {_TYPE_ENUM}."},
    {"name": "source_path", "type": "string", "description": "Cloud-storage path of the source when read was against a path."},
    {"name": "target_table_full_name", "type": "string",
     "description": "Three-part name. NULL encodes a read-only event."},
    {"name": "target_table_catalog", "type": "string"},
    {"name": "target_table_schema", "type": "string"},
    {"name": "target_table_name", "type": "string"},
    {"name": "target_type", "type": "string", "description": f"Same enum as source_type: {_TYPE_ENUM}."},
    {"name": "target_path", "type": "string"},
    {"name": "created_by", "type": "string", "description": "User / service principal / group, or 'System-User'."},
    {"name": "entity_type", "type": "string",
     "description": f"What Databricks asset drove the event. Enum: {_ENTITY_TYPE_ENUM}, or NULL for non-Databricks executions (e.g. JDBC)."},
    {"name": "entity_id", "type": "string", "description": "Stable identifier of the producing entity."},
    {"name": "entity_run_id", "type": "string", "description": "Per-execution identifier (job_run_id, dlt_update_id)."},
    {"name": "entity_metadata", "type": "json",
     "description": "Nested STRUCT (stored as JSON): job_info{job_id, job_run_id}, dlt_pipeline_info{dlt_pipeline_id, dlt_update_id}, notebook_id, dashboard_id, legacy_dashboard_id, sql_query_id, genie_space_id, alert_id."},
    {"name": "statement_id", "type": "string",
     "description": "FK to query_history.statement_id (and qi_statements.statement_id) — joins back to the Query Profiler for SQL warehouse executions."},
    {"name": "direct_access", "type": "boolean",
     "description": "True = source/target referenced directly by the statement. False = surfaced as a transitive dependency by lineage analysis."},
    {"name": "data_origin", "type": "string", "description": "'real' or 'demo' — view-mode isolation."},
    {"name": "deleted_at", "type": "timestamp", "description": "Soft-delete tombstone; non-NULL rows are hidden."},
]


LINEAGE_TABLES_METADATA = [
    {
        "name": "table_lineage",
        "description": (
            "One row per directed read/write edge between Unity Catalog tables (or path-style "
            "locations) emitted by a Databricks statement. Mirrors system.access.table_lineage. "
            "Event class is encoded in source/target nullability: source NOT NULL + target NULL = "
            "read-only; source NULL + target NOT NULL = write-only; both NOT NULL = read-write. "
            "direct_access separates direct references from transitive dependencies. "
            "entity_type+entity_id attribute the edge to a job / notebook / pipeline / dashboard / "
            "DBSQL query. statement_id joins to query_history. Upstream retention is a rolling 1 year."
        ),
        "columns": list(_LINEAGE_COMMON_COLS),
    },
    {
        "name": "column_lineage",
        "description": (
            "One row per directed column→column edge. Same fields as table_lineage with "
            "source_column_name + target_column_name added. CRITICAL: Databricks drops events "
            "without a source (e.g. INSERT VALUES) upstream, so write-only edges that appear in "
            "table_lineage are ABSENT here — column_lineage is NOT a strict subset of table_lineage. "
            "Use event_id to correlate rows that came from the same statement."
        ),
        "columns": list(_LINEAGE_COMMON_COLS) + [
            {"name": "source_column_name", "type": "string"},
            {"name": "target_column_name", "type": "string"},
        ],
    },
    {
        "name": "lineage_rollups",
        "description": (
            "Materialised aggregates over table_lineage — one row per (data_origin, full_name). "
            "Rebuilt in-place by the Transform > Lineage rollups job. Use this for fast "
            "per-table tile counts (edges_in / edges_out / direct vs indirect / distinct upstream / "
            "downstream / entities) instead of re-aggregating millions of edges per question. "
            "full_name is 'catalog.schema.table' and is the join key into databricks_meta via "
            "the three split columns (catalog, database, table_name)."
        ),
        "columns": [
            {"name": "id", "type": "bigint"},
            {"name": "data_origin", "type": "string", "description": "'real' | 'demo'."},
            {"name": "full_name", "type": "string", "description": "catalog.schema.table — the natural key together with data_origin."},
            {"name": "edges_in", "type": "bigint", "description": "Count of table_lineage rows where this full_name is the target."},
            {"name": "edges_out", "type": "bigint", "description": "Count of table_lineage rows where this full_name is the source."},
            {"name": "distinct_upstream", "type": "bigint", "description": "Distinct source_table_full_name values feeding this table — fan-in degree."},
            {"name": "distinct_downstream", "type": "bigint", "description": "Distinct target_table_full_name values this table feeds — fan-out degree."},
            {"name": "distinct_entities", "type": "bigint", "description": "Distinct entity_id touching this table on either side."},
            {"name": "direct_edges", "type": "bigint", "description": "Subset of edges_out where direct_access = true."},
            {"name": "indirect_edges", "type": "bigint", "description": "edges_out - direct_edges."},
            {"name": "last_event", "type": "timestamp"},
            {"name": "rebuilt_at", "type": "timestamp", "description": "Timestamp of the most recent Transform > Lineage rollups run that produced this row."},
        ],
    },
]


# Relationships — lineage tables join back to workspaces, query_history,
# databricks_meta (via the split catalog/schema/table columns), and to each
# other (via event_id and via the source/target FQN split columns).
LINEAGE_RELATIONSHIPS = [
    {"from_table": "table_lineage", "from_column": "workspace_id",
     "to_table": "workspaces", "to_column": "workspace_id"},
    {"from_table": "table_lineage", "from_column": "statement_id",
     "to_table": "query_history", "to_column": "statement_id"},
    {"from_table": "table_lineage", "from_column": "statement_id",
     "to_table": "qi_statements", "to_column": "statement_id"},
    {"from_table": "table_lineage", "from_column": "source_table_catalog",
     "to_table": "databricks_meta", "to_column": "catalog"},
    {"from_table": "table_lineage", "from_column": "source_table_schema",
     "to_table": "databricks_meta", "to_column": "database"},
    {"from_table": "table_lineage", "from_column": "source_table_name",
     "to_table": "databricks_meta", "to_column": "table_name"},
    {"from_table": "table_lineage", "from_column": "target_table_catalog",
     "to_table": "databricks_meta", "to_column": "catalog"},
    {"from_table": "table_lineage", "from_column": "target_table_schema",
     "to_table": "databricks_meta", "to_column": "database"},
    {"from_table": "table_lineage", "from_column": "target_table_name",
     "to_table": "databricks_meta", "to_column": "table_name"},

    {"from_table": "column_lineage", "from_column": "workspace_id",
     "to_table": "workspaces", "to_column": "workspace_id"},
    {"from_table": "column_lineage", "from_column": "statement_id",
     "to_table": "query_history", "to_column": "statement_id"},
    {"from_table": "column_lineage", "from_column": "statement_id",
     "to_table": "qi_statements", "to_column": "statement_id"},
    {"from_table": "column_lineage", "from_column": "event_id",
     "to_table": "table_lineage", "to_column": "event_id"},
    {"from_table": "column_lineage", "from_column": "source_table_catalog",
     "to_table": "databricks_meta", "to_column": "catalog"},
    {"from_table": "column_lineage", "from_column": "source_table_schema",
     "to_table": "databricks_meta", "to_column": "database"},
    {"from_table": "column_lineage", "from_column": "source_table_name",
     "to_table": "databricks_meta", "to_column": "table_name"},
    {"from_table": "column_lineage", "from_column": "source_column_name",
     "to_table": "databricks_meta", "to_column": "col_name"},
    {"from_table": "column_lineage", "from_column": "target_table_catalog",
     "to_table": "databricks_meta", "to_column": "catalog"},
    {"from_table": "column_lineage", "from_column": "target_table_schema",
     "to_table": "databricks_meta", "to_column": "database"},
    {"from_table": "column_lineage", "from_column": "target_table_name",
     "to_table": "databricks_meta", "to_column": "table_name"},
    {"from_table": "column_lineage", "from_column": "target_column_name",
     "to_table": "databricks_meta", "to_column": "col_name"},
]
