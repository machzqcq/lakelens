"""
Catalogue of toggleable product features.

This is the single source of truth for the per-role feature matrix
rendered by the Admin > Roles editor (and consumed by the frontend
`useFeatures()` hook + `RequireFeature` route guard). Each entry has:

  key             stable identifier, used in storage and on the frontend
                  to ask `isFeatureEnabled(key)`. Prefix encodes section:
                    ui.*       — frontend / navigation surfaces
                    backend.*  — backend-only capabilities and services
  title           short human label for the admin page
  description     longer sentence about what turning this off would hide
  category        'frontend' | 'backend'
  default_enabled whether a NEW role starts with the feature checked

Features are granted PER ROLE. The effective set for a user is the union
of features across their non-system roles (admins + plain 'user' get all).
The matrix is the basis for future pricing plans — a tier maps to a
role's feature list; assigning the role applies the tier.
"""

from __future__ import annotations

from typing import Literal, TypedDict


class FeatureSpec(TypedDict):
    key: str
    title: str
    description: str
    category: Literal["frontend", "backend"]
    default_enabled: bool


FEATURES: list[FeatureSpec] = [
    # -----------------------------------------------------------------------
    # Frontend (UI surfaces / panels users can see)
    # -----------------------------------------------------------------------
    {
        "key": "ui.billing_explorer",
        "title": "Billing Explorer",
        "description": (
            "Aggregated billing dashboard with cost-by-SKU, cost-by-origin, "
            "daily trend, and top-10 SKU charts. Includes the sub-pages: "
            "Cost Explorer, User Footprint, Trends & Forecast, Compute "
            "Resources, SKU & Billing Origin, Advanced Analytics."
        ),
        "category": "frontend",
        "default_enabled": True,
    },
    {
        "key": "ui.query_profiler",
        "title": "Query Profiler",
        "description": (
            "Parsed view of query_history with per-department scenarios "
            "(FinOps, Platform/IT, Security, Data Eng, BI, DS, Exec, DevEx, "
            "Cross-cutting). Hidden when off — the qi_* extract continues "
            "to populate but is not surfaced."
        ),
        "category": "frontend",
        "default_enabled": True,
    },
    {
        "key": "ui.meta_explorer",
        "title": "Meta Explorer",
        "description": (
            "Unity Catalog snapshot browser (catalogs / databases / tables / "
            "columns / search) and the bulk CSV/XLSX export controls."
        ),
        "category": "frontend",
        "default_enabled": True,
    },
    {
        "key": "ui.chatbot",
        "title": "Chatbot",
        "description": (
            "Natural-language SQL chatbot over the operational warehouse. "
            "Disabling hides the sidebar entry; the backend chat endpoints "
            "can be gated separately via backend.chatbot_llm."
        ),
        "category": "frontend",
        "default_enabled": True,
    },
    {
        "key": "ui.data_management",
        "title": "Data Management",
        "description": (
            "Admin page for ingesting parquet / triggering Databricks "
            "extracts, switching the Query Profiler engine, and toggling "
            "user view-mode (real vs demo)."
        ),
        "category": "frontend",
        "default_enabled": True,
    },
    {
        "key": "ui.database_explorer",
        "title": "Database Explorer",
        "description": (
            "Read-only Postgres console for admins, with parser-level guard "
            "against writes."
        ),
        "category": "frontend",
        "default_enabled": True,
    },
    {
        "key": "ui.spark_sql_editor",
        "title": "Spark SQL Editor",
        "description": (
            "Admin-only SQL editor against the local spark-warehouse Delta "
            "tables. Visible only when the Spark stack is up."
        ),
        "category": "frontend",
        "default_enabled": True,
    },
    {
        "key": "ui.view_mode_toggle",
        "title": "View-Mode Toggle (Real / Demo)",
        "description": (
            "Per-user real-vs-demo data isolation toggle in the top-right "
            "cluster. Hides the toggle button; the underlying `data_origin` "
            "scoping remains active server-side."
        ),
        "category": "frontend",
        "default_enabled": True,
    },
    {
        "key": "ui.notifications_bell",
        "title": "Notifications Bell",
        "description": (
            "Top-right bell that lists background-job results (extracts, "
            "ingests, deletes)."
        ),
        "category": "frontend",
        "default_enabled": True,
    },
    {
        "key": "ui.theme_switcher",
        "title": "Theme Switcher",
        "description": (
            "Light / Dark / system theme picker in the top-right cluster."
        ),
        "category": "frontend",
        "default_enabled": True,
    },
    {
        "key": "ui.exports_csv_xlsx",
        "title": "CSV / XLSX Exports",
        "description": (
            "Per-chart and Meta Explorer bulk exports. Disabling hides the "
            "download buttons across the app."
        ),
        "category": "frontend",
        "default_enabled": True,
    },

    # -----------------------------------------------------------------------
    # Backend (services / capabilities the server provides)
    # -----------------------------------------------------------------------
    {
        "key": "backend.databricks_extractor",
        "title": "Databricks Extractor",
        "description": (
            "The isolated extractor container that talks to Databricks "
            "(`/extract`, `/extract-meta`, `/extract-qi`) via databricks-sdk "
            "+ databricks-connect. Off → only parquet ingest and demo seed."
        ),
        "category": "backend",
        "default_enabled": True,
    },
    {
        "key": "backend.spark_engine",
        "title": "Spark / Delta Engine",
        "description": (
            "Apache Spark 4.1.1 stack (master, worker, Connect server). When "
            "enabled, the Query Profiler can run in Spark mode and write to "
            "Delta tables; off → forced DuckDB mode."
        ),
        "category": "backend",
        "default_enabled": True,
    },
    {
        "key": "backend.chatbot_llm",
        "title": "Chatbot LLM Calls",
        "description": (
            "Outbound calls from `/api/chat/...` to the LLM. Off → the chat "
            "endpoints return 503; the UI tab still renders (gate it with "
            "ui.chatbot for a clean hide)."
        ),
        "category": "backend",
        "default_enabled": True,
    },
    {
        "key": "backend.oauth_login",
        "title": "OAuth Login",
        "description": (
            "Google / GitHub / Microsoft OAuth flows under `/api/auth/oauth/*`. "
            "Off → password login only."
        ),
        "category": "backend",
        "default_enabled": True,
    },
    {
        "key": "backend.email_verification",
        "title": "Email Verification (SES)",
        "description": (
            "Send-verification-email step on registration. Off → accounts "
            "are marked verified immediately."
        ),
        "category": "backend",
        "default_enabled": True,
    },
    {
        "key": "backend.background_jobs",
        "title": "Background Jobs",
        "description": (
            "The `background_jobs` queue that runs long-running ingests / "
            "extracts / deletes. Off → operations run inline on the request "
            "thread (slower, no progress reporting)."
        ),
        "category": "backend",
        "default_enabled": True,
    },
    {
        "key": "backend.audit_log",
        "title": "Audit Log",
        "description": (
            "Captures admin actions (user create/delete, role assigns, data "
            "deletes) into the audit log."
        ),
        "category": "backend",
        "default_enabled": True,
    },
    {
        "key": "backend.rbac_filters",
        "title": "RBAC Data-Scope Filters",
        "description": (
            "Per-role filters JSON (workspace_ids, sku_name_pattern, etc.) "
            "applied to billing/compute queries. Off → admins see everything; "
            "non-admins are still restricted by the role-assignment system."
        ),
        "category": "backend",
        "default_enabled": True,
    },
    {
        "key": "backend.demo_data",
        "title": "Demo Data Generator",
        "description": (
            "The `scripts/simulate_demo_data.py` pipeline and the demo "
            "view-mode. Off → the view-mode toggle has only 'real' "
            "available and demo_*.parquet files are ignored on ingest."
        ),
        "category": "backend",
        "default_enabled": True,
    },
    {
        "key": "backend.meta_extractor",
        "title": "Unity Catalog Meta Extractor",
        "description": (
            "Extractor pass that populates `databricks_meta` by walking "
            "INFORMATION_SCHEMA via the Databricks SDK. Off → Meta Explorer "
            "shows whatever snapshot already exists, no refresh."
        ),
        "category": "backend",
        "default_enabled": True,
    },
]


# ---------------------------------------------------------------------------
# Convenience lookups
# ---------------------------------------------------------------------------

FEATURES_BY_KEY: dict[str, FeatureSpec] = {f["key"]: f for f in FEATURES}


def is_known_feature(key: str) -> bool:
    return key in FEATURES_BY_KEY


def default_enabled(key: str) -> bool:
    spec = FEATURES_BY_KEY.get(key)
    return spec["default_enabled"] if spec else True
