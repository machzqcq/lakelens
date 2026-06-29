"""Inline schema metadata for the qi_* (Query Intel) tables.

Used by routers/chat.py to add the qi_* tables to the LLM context. We keep
it here (rather than in the xlsx workbook) so the chatbot picks them up
even if the workbook hasn't been regenerated yet. The xlsx is updated
separately by scripts/update_consolidated_metadata.py for documentation
purposes.
"""
from __future__ import annotations

QI_TABLES_METADATA = [
    {
        "name": "qi_statements",
        "description": (
            "Flat denormalized view of every query in query_history. One row per statement_id. "
            "Built by extract/query_intel.py via sqlglot. Holds compute attribution "
            "(compute_type, warehouse_id), source attribution (source_category, job_id, "
            "pipeline_id, notebook_id, dashboard_id, alert_id, sql_query_id, "
            "genie_space_id), latency breakdown (waiting/compile/execution durations), IO "
            "metrics, error category, and derived flags (is_off_hours, is_full_scan, "
            "is_expensive, is_cache_hit, has_select_star, has_cross_join, has_cte, "
            "has_subquery, has_window, is_dml, is_ddl, is_grant_revoke)."
        ),
        "columns": [
            {"name": "statement_id", "type": "string", "description": "PK. Databricks-assigned unique id."},
            {"name": "account_id", "type": "string"},
            {"name": "workspace_id", "type": "string"},
            {"name": "executed_by", "type": "string", "description": "Email or principal that submitted the query."},
            {"name": "executed_as", "type": "string", "description": "Principal whose privileges were checked."},
            {"name": "is_delegated", "type": "boolean", "description": "True when executed_by != executed_as (on-behalf-of)."},
            {"name": "principal_kind", "type": "string", "description": "'human' | 'service' | 'unknown'"},
            {"name": "session_id", "type": "string"},
            {"name": "compute_type", "type": "string", "description": "'WAREHOUSE' | 'SERVERLESS_COMPUTE'"},
            {"name": "warehouse_id", "type": "string"},
            {"name": "cluster_id", "type": "string"},
            {"name": "statement_type", "type": "string", "description": "SELECT, INSERT, MERGE, DESCRIBE, …"},
            {"name": "execution_status", "type": "string", "description": "FINISHED | FAILED | CANCELED"},
            {"name": "statement_text_excerpt", "type": "string", "description": "First 2KB of statement_text."},
            {"name": "statement_text_length", "type": "bigint"},
            {"name": "normalized_sql_hash", "type": "string", "description": "sha1 of literal-stripped SQL — group identical queries."},
            {"name": "is_sql", "type": "boolean"},
            {"name": "has_select_star", "type": "boolean"},
            {"name": "has_cross_join", "type": "boolean"},
            {"name": "has_cte", "type": "boolean"},
            {"name": "has_subquery", "type": "boolean"},
            {"name": "has_window", "type": "boolean"},
            {"name": "is_describe_or_show", "type": "boolean"},
            {"name": "is_dml", "type": "boolean"},
            {"name": "is_ddl", "type": "boolean"},
            {"name": "is_grant_revoke", "type": "boolean"},
            {"name": "is_parameterized", "type": "boolean"},
            {"name": "client_application", "type": "string", "description": "Databricks SQL Editor, PowerBI, Tableau, …"},
            {"name": "client_driver", "type": "string"},
            {"name": "client_driver_family", "type": "string", "description": "PyConnector | JDBC | ODBC | ExecApi | ADBC | NodeJS | Other"},
            {"name": "client_driver_version", "type": "string"},
            {"name": "source_category", "type": "string", "description": "JOB | PIPELINE | NOTEBOOK | DASHBOARD | ALERT | SQL_QUERY | GENIE | AD_HOC"},
            {"name": "job_id", "type": "string"},
            {"name": "job_run_id", "type": "string"},
            {"name": "pipeline_id", "type": "string"},
            {"name": "notebook_id", "type": "string"},
            {"name": "dashboard_id", "type": "string"},
            {"name": "alert_id", "type": "string"},
            {"name": "sql_query_id", "type": "string"},
            {"name": "genie_space_id", "type": "string"},
            {"name": "total_duration_ms", "type": "bigint"},
            {"name": "waiting_for_compute_duration_ms", "type": "bigint"},
            {"name": "waiting_at_capacity_duration_ms", "type": "bigint"},
            {"name": "execution_duration_ms", "type": "bigint"},
            {"name": "compilation_duration_ms", "type": "bigint"},
            {"name": "total_task_duration_ms", "type": "bigint"},
            {"name": "result_fetch_duration_ms", "type": "bigint"},
            {"name": "start_time", "type": "timestamp"},
            {"name": "end_time", "type": "timestamp"},
            {"name": "start_date", "type": "date"},
            {"name": "start_hour", "type": "integer", "description": "0-23"},
            {"name": "start_day_of_week", "type": "integer", "description": "0=Monday, 6=Sunday"},
            {"name": "is_off_hours", "type": "boolean", "description": "True if hour < 7 or hour >= 19."},
            {"name": "is_weekend", "type": "boolean"},
            {"name": "read_partitions", "type": "bigint"},
            {"name": "pruned_files", "type": "bigint"},
            {"name": "read_files", "type": "bigint"},
            {"name": "read_rows", "type": "bigint"},
            {"name": "produced_rows", "type": "bigint"},
            {"name": "read_bytes", "type": "bigint"},
            {"name": "from_result_cache", "type": "boolean"},
            {"name": "spilled_local_bytes", "type": "bigint"},
            {"name": "written_bytes", "type": "bigint"},
            {"name": "shuffle_read_bytes", "type": "bigint"},
            {"name": "written_rows", "type": "bigint"},
            {"name": "written_files", "type": "bigint"},
            {"name": "pruning_ratio", "type": "decimal", "description": "0..1; pruned_files / (read_files + pruned_files)"},
            {"name": "selectivity_ratio", "type": "decimal", "description": "produced_rows / read_rows"},
            {"name": "waiting_pct", "type": "decimal"},
            {"name": "compile_pct", "type": "decimal"},
            {"name": "is_full_scan", "type": "boolean", "description": "read_bytes > 100GB and produced_rows < 1k"},
            {"name": "is_expensive", "type": "boolean", "description": "Top 1% by total_duration_ms in the extraction."},
            {"name": "is_cache_hit", "type": "boolean"},
            {"name": "cache_origin_statement_id", "type": "string"},
            {"name": "error_category", "type": "string", "description": "PERMISSION | NOT_FOUND | PARSE | OOM | TIMEOUT | ANALYSIS | DEPENDENCY | OTHER"},
            {"name": "error_code", "type": "string"},
            {"name": "sqlstate", "type": "string"},
            {"name": "project_keywords", "type": "json"},
            {"name": "catalogs_touched", "type": "json"},
            {"name": "schemas_touched", "type": "json"},
            {"name": "tables_touched", "type": "json"},
        ],
    },
    {
        "name": "qi_statement_tables",
        "description": "Tables a statement read/wrote. Joins to qi_statements on statement_id. role ∈ {read, write, cte, reference}.",
        "columns": [
            {"name": "statement_id", "type": "string"},
            {"name": "catalog", "type": "string"},
            {"name": "schema", "type": "string"},
            {"name": "table_name", "type": "string"},
            {"name": "fully_qualified", "type": "string", "description": "catalog.schema.table_name"},
            {"name": "role", "type": "string", "description": "read | write | cte | reference"},
            {"name": "is_system_table", "type": "boolean"},
            {"name": "is_temp", "type": "boolean"},
        ],
    },
    {
        "name": "qi_statement_columns",
        "description": "Columns referenced by a statement and the SQL clause they appeared in.",
        "columns": [
            {"name": "statement_id", "type": "string"},
            {"name": "column_name", "type": "string"},
            {"name": "table_hint", "type": "string", "description": "Alias if the column was qualified."},
            {"name": "role", "type": "string", "description": "select | where | groupby | orderby | join | having | aggregate"},
        ],
    },
    {
        "name": "qi_statement_errors",
        "description": "One row per FAILED statement with normalized error metadata.",
        "columns": [
            {"name": "statement_id", "type": "string", "description": "PK; joins to qi_statements."},
            {"name": "error_category", "type": "string"},
            {"name": "error_code", "type": "string"},
            {"name": "sqlstate", "type": "string"},
            {"name": "error_message_excerpt", "type": "string"},
            {"name": "referenced_object", "type": "string", "description": "First backticked table reference in the error."},
            {"name": "referenced_user", "type": "string"},
        ],
    },
    {
        "name": "qi_statement_tags",
        "description": "Flattened query_tags map (key, value) — usually populated for tagged production workloads.",
        "columns": [
            {"name": "statement_id", "type": "string"},
            {"name": "tag_key", "type": "string"},
            {"name": "tag_value", "type": "string"},
        ],
    },
    {
        "name": "qi_statement_parameters",
        "description": "Flattened query_parameters.named_parameters; just the names + string values.",
        "columns": [
            {"name": "statement_id", "type": "string"},
            {"name": "param_name", "type": "string"},
            {"name": "param_value", "type": "string"},
            {"name": "param_type", "type": "string"},
        ],
    },
]


QI_RELATIONSHIPS = [
    {"from_table": "qi_statement_tables", "from_column": "statement_id",
     "to_table": "qi_statements", "to_column": "statement_id"},
    {"from_table": "qi_statement_columns", "from_column": "statement_id",
     "to_table": "qi_statements", "to_column": "statement_id"},
    {"from_table": "qi_statement_errors", "from_column": "statement_id",
     "to_table": "qi_statements", "to_column": "statement_id"},
    {"from_table": "qi_statement_tags", "from_column": "statement_id",
     "to_table": "qi_statements", "to_column": "statement_id"},
    {"from_table": "qi_statement_parameters", "from_column": "statement_id",
     "to_table": "qi_statements", "to_column": "statement_id"},
    {"from_table": "qi_statements", "from_column": "workspace_id",
     "to_table": "workspaces", "to_column": "workspace_id"},
    {"from_table": "qi_statements", "from_column": "warehouse_id",
     "to_table": "warehouses", "to_column": "warehouse_id"},
    {"from_table": "qi_statements", "from_column": "cluster_id",
     "to_table": "clusters", "to_column": "cluster_id"},
    {"from_table": "qi_statements", "from_column": "job_id",
     "to_table": "jobs", "to_column": "job_id"},
]
