"""Inline schema metadata for the audit tables.

Used by `routers/chat.py` to add `audit_events` and `assistant_events` to
the LLM context so the Chatbot can answer questions about audit trails
(who logged in, what notebooks were exported, which catalog grants were
issued) and Databricks Assistant usage.

Same pattern as `chat_qi_schema.py` / `chat_lineage_schema.py` — keep the
canonical descriptions inline so the LLM has them even if the metadata
workbook hasn't been regenerated.

Authoritative Databricks references:
  - https://docs.databricks.com/aws/en/admin/system-tables/audit-logs
  - https://docs.databricks.com/aws/en/admin/system-tables/assistant
"""
from __future__ import annotations


AUDIT_TABLES_METADATA = [
    {
        "name": "audit_events",
        "description": (
            "One row per Databricks audit event (system.access.audit). Captures "
            "every workspace and account-level action: logins, table grants, "
            "notebook exports, SQL warehouse starts/stops, Unity Catalog operations, "
            "etc. `service_name` + `action_name` identify what happened; "
            "`user_identity_email` is the pre-extracted email from the nested "
            "user_identity STRUCT (full struct is also available as JSON). "
            "`response_status_code` lets you filter for errors (non-200). "
            "`audit_level` distinguishes ACCOUNT_LEVEL events (workspace_id=0) "
            "from WORKSPACE_LEVEL."
        ),
        "columns": [
            {"name": "account_id", "type": "string"},
            {"name": "workspace_id", "type": "string", "description": "'0' for ACCOUNT_LEVEL events."},
            {"name": "version", "type": "string", "description": "Audit log schema version."},
            {"name": "event_time", "type": "timestamp"},
            {"name": "event_date", "type": "date", "description": "Partitioned upstream; filter on this for time windows."},
            {"name": "source_ip_address", "type": "string"},
            {"name": "user_agent", "type": "string"},
            {"name": "session_id", "type": "string"},
            {"name": "user_identity", "type": "json", "description": "STRUCT {email, subjectName}. Use user_identity_email for cheap GROUP BY."},
            {"name": "user_identity_email", "type": "string", "description": "Pre-extracted from user_identity.email."},
            {"name": "service_name", "type": "string", "description": "Enum (open-ended). Common values: unityCatalog, notebook, SQL, accounts, clusters, jobs, dbfs, mlflow."},
            {"name": "action_name", "type": "string", "description": "What happened, e.g. createTable, login, deleteRun. Enum is open-ended; group by it for top-action analyses."},
            {"name": "request_id", "type": "string"},
            {"name": "request_params", "type": "json", "description": "MAP<string, string> of request inputs — varies by (service_name, action_name)."},
            {"name": "response", "type": "json", "description": "STRUCT {status_code, error_message, result}."},
            {"name": "response_status_code", "type": "integer", "description": "Pre-extracted from response.status_code. 200 = success."},
            {"name": "response_error_message", "type": "string", "description": "Pre-extracted from response.error_message."},
            {"name": "audit_level", "type": "string", "description": "ACCOUNT_LEVEL | WORKSPACE_LEVEL."},
            {"name": "event_id", "type": "string"},
            {"name": "identity_metadata", "type": "json", "description": "STRUCT {run_by, run_as} — for actions executed on behalf of another principal."},
            {"name": "data_origin", "type": "string", "description": "'real' or 'demo' — view-mode isolation."},
            {"name": "deleted_at", "type": "timestamp"},
        ],
    },
    {
        "name": "assistant_events",
        "description": (
            "User-submitted Databricks Assistant / Genie Code interactions "
            "(system.access.assistant_events). Excludes automated requests "
            "(autocomplete, safety checks). Useful for measuring Assistant "
            "adoption, attribution per user, and surface (notebook vs SQL "
            "editor vs dashboards) — though the published schema is minimal "
            "and `user_agent` is the main signal for surface today."
        ),
        "columns": [
            {"name": "event_id", "type": "string"},
            {"name": "account_id", "type": "string"},
            {"name": "workspace_id", "type": "string"},
            {"name": "event_time", "type": "timestamp"},
            {"name": "event_date", "type": "date"},
            {"name": "user_agent", "type": "string", "description": "Origination — proxy for which Databricks surface (notebook / SQL editor / dashboards) submitted the prompt."},
            {"name": "initiated_by", "type": "string", "description": "Email of the user initiating the request."},
            {"name": "data_origin", "type": "string"},
            {"name": "deleted_at", "type": "timestamp"},
        ],
    },
]


AUDIT_RELATIONSHIPS = [
    {"from_table": "audit_events", "from_column": "workspace_id",
     "to_table": "workspaces", "to_column": "workspace_id"},
    {"from_table": "audit_events", "from_column": "user_identity_email",
     "to_table": "billing_usage", "to_column": "run_as"},
    {"from_table": "audit_events", "from_column": "user_identity_email",
     "to_table": "qi_statements", "to_column": "executed_by"},
    {"from_table": "assistant_events", "from_column": "workspace_id",
     "to_table": "workspaces", "to_column": "workspace_id"},
    {"from_table": "assistant_events", "from_column": "initiated_by",
     "to_table": "qi_statements", "to_column": "executed_by"},
]
