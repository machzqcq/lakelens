"""
Chatbot endpoints.

Flow:
  user question  ->  LLM (with metadata as system context)  ->  generated SQL
                  ->  DuckDB on the parquet files  ->  result rows
                  ->  LLM (explain results)  ->  natural-language answer

Uses helper functions copied from /helpers:
  - llm_helpers.get_available_models
  - llm_helpers.generate_sql_from_text
  - query_logger.get_query_logger (logs each end-to-end interaction)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import io

import duckdb
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import llm_helpers
import storage
from auth_utils import AuthedUser, get_current_user
from query_logger import get_query_logger

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/chat",
    tags=["chat"],
    dependencies=[Depends(get_current_user)],
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DATA_DIR = Path(os.getenv("DATA_DIR", str(_BACKEND_DIR.parent / "data")))
_METADATA_XLSX = Path(
    os.getenv(
        "METADATA_XLSX",
        str(_BACKEND_DIR.parent / "consolidated_metadata_with_descriptions.xlsx"),
    )
)
# Local fallback locations for the metadata workbook
_FALLBACK_METADATA_XLSX = _DATA_DIR / "consolidated_metadata_with_descriptions.xlsx"

# Tables exposed to the chatbot (each maps to <store>/<table>_*.parquet glob).
# Keep in lock-step with the metadata workbook — every table the LLM is told
# about in the system prompt must have a corresponding DuckDB view here, or
# generated SQL will fail with "Table with name X does not exist".
_TABLES = [
    "billing_usage",
    "list_prices",
    "clusters",
    "warehouses",
    "jobs",
    "workspaces",
    "query_history",
]

# Query Intel tables — live in Postgres (engine=duckdb) or Spark Delta
# (engine=spark). Exposed to the chatbot via either ATTACH-postgres in DuckDB
# or spark.sql() depending on the active engine.
_QI_TABLES = [
    "qi_statements",
    "qi_statement_tables",
    "qi_statement_columns",
    "qi_statement_tags",
    "qi_statement_parameters",
    "qi_statement_errors",
]

# Lineage tables — same shape as qi_* (Postgres-resident; exposed to DuckDB
# via the Postgres ATTACH). In Spark engine mode they're registered as JDBC
# temp views by `backend/spark_session.py:_BASE_TABLES`, so both engines can
# answer lineage questions from the chatbot.
_LINEAGE_TABLES = [
    "table_lineage",
    "column_lineage",
    "lineage_rollups",
]

# Other Postgres-resident tables the chatbot needs to reach via the same
# ATTACH. `databricks_meta` was historically only exposed in Spark mode;
# we now register it in DuckDB mode too so meta-∩-lineage joins work.
# audit_events + assistant_events flow through the same path so the chatbot
# can answer questions like "who exported which notebook last week" or
# "how many Assistant prompts did the data team send."
_OTHER_PG_TABLES = [
    "databricks_meta",
    "audit_events",
    "assistant_events",
]


# ---------------------------------------------------------------------------
# DuckDB session — register one view per table over its latest parquet
# ---------------------------------------------------------------------------

_VALID_VIEW_MODES = ("real", "demo")


def _safe_view_mode(view_mode: str) -> str:
    """JDBC/SQL strings embed the view_mode literal — constrain it to
    the known enum so we can't be tricked into smuggling SQL."""
    m = (view_mode or "").strip().lower()
    return m if m in _VALID_VIEW_MODES else "real"


def _latest_parquet_uri(table: str, view_mode: str = "real") -> Optional[str]:
    """Storage-agnostic: returns a file path or s3://... / az://... / gs://... URI.

    Picks the demo_* file when view_mode='demo' so the chatbot's DuckDB
    parquet views match the user's view_mode toggle. When demo is
    selected but no demo_* file exists, falls back to the real-data file
    rather than failing — better to show stale-but-consistent data than
    an empty view.
    """
    view_mode = _safe_view_mode(view_mode)
    if view_mode == "demo":
        demo = storage.latest_parquet(f"demo_{table}")
        if demo is not None:
            return demo
    return storage.latest_parquet(table)


def _attach_postgres_qi(
    con: "duckdb.DuckDBPyConnection",
    view_mode: str = "real",
) -> None:
    """ATTACH the Postgres DB and register qi_* + lineage_* + audit + meta
    views in DuckDB **filtered by `view_mode` and soft-delete**.

    Uses the same env vars the rest of the backend reads. After this call,
    the DuckDB connection can reference `qi_statements`, `qi_statement_tables`,
    `table_lineage`, `column_lineage`, `lineage_rollups`, `audit_events`,
    `databricks_meta`, etc., by their unqualified names — implemented as
    views over the attached Postgres schema with the WHERE clause baked
    in. Real and demo never cross-contaminate.
    """
    view_mode = _safe_view_mode(view_mode)
    host = os.getenv("DB_HOST", "db")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "databricks_billing")
    user = os.getenv("DB_USER", "billing_user")
    password = os.getenv("DB_PASS", "billing_pass")
    conn_str = f"host={host} port={port} dbname={name} user={user} password={password}"
    all_pg_tables = _QI_TABLES + _LINEAGE_TABLES + _OTHER_PG_TABLES
    try:
        con.execute("INSTALL postgres; LOAD postgres;")
        # READ_ONLY=TRUE so a runaway LLM-generated query can never mutate.
        con.execute(f"ATTACH '{conn_str}' AS pg (TYPE POSTGRES, READ_ONLY)")
        for t in all_pg_tables:
            con.execute(
                f"CREATE OR REPLACE VIEW {t} AS "
                f"SELECT * FROM pg.public.{t} "
                f"WHERE data_origin = '{view_mode}' AND deleted_at IS NULL"
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Chat: postgres ATTACH failed (%s); qi_* and lineage_* views will be empty stubs.", e,
        )
        for t in all_pg_tables:
            con.execute(f"CREATE OR REPLACE VIEW {t} AS SELECT 1 WHERE 0=1")


def _build_duckdb(
    include_qi: bool = True,
    view_mode: str = "real",
) -> duckdb.DuckDBPyConnection:
    """Build an in-memory DuckDB and register a view per table.

    Pulls files from the active storage backend (local | s3 | azure | gcs).
    For each base table, `_latest_parquet_uri` is asked for the demo_* file
    when `view_mode='demo'` (with a fallback to the real-data file). For
    Postgres-resident tables (qi_* / lineage / audit / meta), the Postgres
    ATTACH path bakes `WHERE data_origin = '<view_mode>' AND
    deleted_at IS NULL` into every view, so real and demo never mix.
    """
    view_mode = _safe_view_mode(view_mode)
    con = duckdb.connect(database=":memory:")
    storage.duckdb_setup(con)

    for t in _TABLES:
        uri = _latest_parquet_uri(t, view_mode=view_mode)
        if uri is None:
            logger.warning("Chat: no parquet for table %s (view_mode=%s), view will be empty", t, view_mode)
            con.execute(f"CREATE OR REPLACE VIEW {t} AS SELECT 1 WHERE 0=1")
            continue
        # DuckDB consumes file paths and cloud URIs (s3:// / az:// / gs://)
        # the same way once the right extension is loaded.
        sql_uri = uri.replace("\\", "/")  # Windows-safe
        con.execute(
            f"CREATE OR REPLACE VIEW {t} AS SELECT * FROM read_parquet('{sql_uri}')"
        )

    if include_qi:
        _attach_postgres_qi(con, view_mode=view_mode)
    return con


# ---------------------------------------------------------------------------
# Metadata loading -> system prompt
# ---------------------------------------------------------------------------

_SCHEMA_JSON_CACHE: Optional[dict[str, Any]] = None


def _load_metadata_xlsx() -> Path:
    """Locate the metadata workbook, falling back to the data directory."""
    for p in (_METADATA_XLSX, _FALLBACK_METADATA_XLSX):
        if p.exists():
            return p
    raise FileNotFoundError(
        f"Metadata workbook not found at {_METADATA_XLSX} or {_FALLBACK_METADATA_XLSX}. "
        "Run: python backend/metadata.py"
    )


def _parse_sample_values(raw: Any) -> list[Any]:
    """Convert the SAMPLE_VALUES cell (a stringified Python list) into JSON-friendly values."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    if isinstance(raw, list):
        return raw
    s = str(raw).strip()
    if not s or s == "[]":
        return []
    try:
        import ast
        parsed = ast.literal_eval(s)
        if isinstance(parsed, (list, tuple)):
            return [str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v for v in parsed]
    except (ValueError, SyntaxError):
        pass
    # Fallback: treat as a single-value list
    return [s]


def _build_schema_json() -> dict[str, Any]:
    """Convert the metadata workbook into a structured JSON object."""
    global _SCHEMA_JSON_CACHE
    if _SCHEMA_JSON_CACHE is not None:
        return _SCHEMA_JSON_CACHE

    xlsx = _load_metadata_xlsx()
    cols_df = pd.read_excel(xlsx, sheet_name="Column Descriptions")
    tables_df = pd.read_excel(xlsx, sheet_name="Table Descriptions")
    rels_df = pd.read_excel(xlsx, sheet_name="Table Relationships")

    # Columns grouped per table for compactness
    cols_by_table: dict[str, list[dict[str, Any]]] = {}
    for _, c in cols_df.iterrows():
        t = c["TABLE_NAME"]
        cols_by_table.setdefault(t, []).append({
            "name": c["COLUMN_NAME"],
            "description": (c.get("COLUMN_DESCRIPTION") or "") if pd.notna(c.get("COLUMN_DESCRIPTION")) else "",
            "data_type": c.get("COLUMN_DATA_TYPE") or "",
            "sample_values": _parse_sample_values(c.get("SAMPLE_VALUES")),
        })

    tables = [
        {
            "name": r["TABLE_NAME"],
            "description": (r.get("TABLE_DESCRIPTION") or "") if pd.notna(r.get("TABLE_DESCRIPTION")) else "",
            "columns": cols_by_table.get(r["TABLE_NAME"], []),
        }
        for _, r in tables_df.iterrows()
    ]

    relationships = [
        {
            "from_table": r["TABLE_NAME"],
            "from_column": r["COLUMN_NAME"],
            "to_table": r["RELATED_TABLE_NAME"],
            "to_column": r["RELATED_COLUMN_NAME"],
        }
        for _, r in rels_df.iterrows()
    ]

    # Splice in the qi_* tables (richer descriptions than the xlsx carries).
    from routers.chat_qi_schema import QI_TABLES_METADATA, QI_RELATIONSHIPS
    existing_names = {t["name"] for t in tables}
    for qi_t in QI_TABLES_METADATA:
        if qi_t["name"] not in existing_names:
            tables.append(qi_t)
    relationships.extend(QI_RELATIONSHIPS)

    # Splice in the lineage tables. Workbook MAY carry them depending on
    # when scripts/update_consolidated_metadata.py was last run; this
    # inline path is the safety net AND supplies the event-class semantics
    # the LLM needs to write correct SQL against `table_lineage`.
    from routers.chat_lineage_schema import LINEAGE_TABLES_METADATA, LINEAGE_RELATIONSHIPS
    existing_names = {t["name"] for t in tables}
    for lt in LINEAGE_TABLES_METADATA:
        if lt["name"] not in existing_names:
            tables.append(lt)
    relationships.extend(LINEAGE_RELATIONSHIPS)

    # audit_events + assistant_events follow the same inline pattern — the
    # LLM needs the audit_level / response_status_code semantics + service /
    # action enum hints to write useful "who did what" SQL.
    from routers.chat_audit_schema import AUDIT_TABLES_METADATA, AUDIT_RELATIONSHIPS
    existing_names = {t["name"] for t in tables}
    for at in AUDIT_TABLES_METADATA:
        if at["name"] not in existing_names:
            tables.append(at)
    relationships.extend(AUDIT_RELATIONSHIPS)

    # system.compute.* — node_timeline / warehouse_events / node_types /
    # instance_events / instance_pools. The LLM needs the time-window
    # warning on node_timeline (high-cardinality), the event-type enums on
    # warehouse_events and instance_events, and the foreign-key topology
    # back to clusters / warehouses / node_types.
    from routers.chat_node_pool_schema import NODE_POOL_TABLES_METADATA, NODE_POOL_RELATIONSHIPS
    existing_names = {t["name"] for t in tables}
    for npt in NODE_POOL_TABLES_METADATA:
        if npt["name"] not in existing_names:
            tables.append(npt)
    relationships.extend(NODE_POOL_RELATIONSHIPS)

    _SCHEMA_JSON_CACHE = {
        "dialect": "duckdb",
        "tables": tables,
        "relationships": relationships,
    }
    return _SCHEMA_JSON_CACHE


_SYSTEM_PROMPT_CACHE_BY_KEY: dict[str, str] = {}


def _build_system_prompt(engine: str = "duckdb", spark_mode: str = "jdbc_views") -> str:
    """Build the SQL-generation system prompt for the given engine + mode.

    DuckDB prompt = current behavior + qi_* + lineage tables.

    Spark prompt has TWO sub-shapes:
      * spark + jdbc_views (default): base PG tables are JDBC temp views,
        referenced UNQUALIFIED (`SELECT ... FROM table_lineage`).
      * spark + materialized: base PG tables are managed Delta tables in
        spark-warehouse, referenced with the 3-part name
        (`SELECT ... FROM spark_catalog.default.table_lineage`).
    """
    cache_key = engine if engine != "spark" else f"spark::{spark_mode}"
    cached = _SYSTEM_PROMPT_CACHE_BY_KEY.get(cache_key)
    if cached is not None:
        return cached

    schema = _build_schema_json()
    schema_for_prompt = {**schema, "dialect": engine, "spark_mode": spark_mode}
    schema_json = json.dumps(schema_for_prompt, ensure_ascii=False, separators=(",", ":"))

    if engine == "spark":
        if spark_mode == "materialized":
            rules = _SPARK_RULES_MATERIALIZED
        else:
            rules = _SPARK_RULES
    else:
        rules = _DUCKDB_RULES
    prompt = rules + schema_json
    _SYSTEM_PROMPT_CACHE_BY_KEY[cache_key] = prompt
    return prompt


# Back-compat alias for the older cache name used by health/debug endpoints.
_SYSTEM_PROMPT_CACHE_BY_ENGINE = _SYSTEM_PROMPT_CACHE_BY_KEY


_DUCKDB_RULES = (
    "You are a SQL analyst for a Databricks billing dashboard. Translate the user's "
    "natural-language question into a single DuckDB-flavored SQL query that runs over "
    "the parquet-backed billing tables AND the postgres-attached qi_* (Query Intel) "
    "tables described in the schema JSON below.\n\n"
    "OUTPUT RULES:\n"
    "1. Return ONLY one SQL statement, wrapped in a ```sql ... ``` fenced code block. "
    "No commentary outside the fence.\n"
    "2. Use ONLY the tables and columns in `schema.tables`. Do not invent names.\n"
    "3. The dialect is DuckDB. Date casts use CAST(... AS DATE). String concat uses ||. "
    "Window functions, CTEs, and aggregates are supported.\n"
    "4. ALWAYS apply a LIMIT (default 200) unless the user asked for an aggregate.\n"
    "5. For cost calculations: prefer billing_usage.usage_usd when not NULL; otherwise "
    "join list_prices on (sku_name, cloud, usage_unit) and bound the time window with "
    "  `billing_usage.usage_end_time >= list_prices.price_start_time AND "
    "(list_prices.price_end_time IS NULL OR billing_usage.usage_end_time < list_prices.price_end_time)`. "
    "DO NOT use `COALESCE(price_end_time, NOW())` — the parquet timestamps are TIMESTAMP_NS "
    "and NOW() is TIMESTAMP WITH TIME ZONE, which DuckDB refuses to mix in COALESCE.\n"
    "6. clusters and warehouses are change-event tables — pick the latest config per id "
    "with DISTINCT ON or a window function ordered by change_time DESC if you need names.\n"
    "7. \"Utilization\" = sum of usage_quantity (DBU). \"Cost\" = USD (usage_usd or "
    "usage_quantity * effective_list_price). Return both when ambiguous.\n"
    "8. Query Intel (qi_*) tables answer questions about what queries ran, by whom, "
    "what they read/wrote, errors, latency, source (job/dashboard/notebook/genie). "
    "Join qi_statement_tables/columns to qi_statements on statement_id.\n"
    "9. Lineage tables (`table_lineage`, `column_lineage`, `lineage_rollups`) answer "
    "questions about table/column dependency graphs — \"what feeds X\", \"what consumes X\", "
    "\"which job writes to table Y\", \"orphan tables\", \"most-fanned-out columns\". "
    "Critical encoding: source_table_full_name NOT NULL + target_table_full_name NULL = "
    "read-only event; source NULL + target NOT NULL = write-only; both NOT NULL = read-write. "
    "ALWAYS filter `source_table_full_name IS NOT NULL` (or target) before counting upstream/"
    "downstream neighbours so you don't accidentally count read-only or write-only events twice. "
    "Use `direct_access = TRUE` when you want only direct references (skips transitive deps). "
    "For per-table tile counts, prefer `lineage_rollups` over re-aggregating `table_lineage`. "
    "column_lineage drops events with no source — so write-only events visible in table_lineage "
    "are ABSENT from column_lineage. Join lineage to qi_statements / query_history via statement_id, "
    "and to databricks_meta via the split catalog/schema/table_name columns.\n\n"
    "SCHEMA (JSON):\n"
)


_SPARK_RULES = (
    "You are a Spark SQL analyst for a Databricks billing dashboard. Translate the user's "
    "natural-language question into a single Spark SQL query that runs over the qi_* "
    "(Query Intel) Delta tables in spark_catalog.default plus the parquet-backed billing "
    "tables described in the schema JSON below.\n\n"
    "OUTPUT RULES:\n"
    "1. Return ONLY one SQL statement, wrapped in a ```sql ... ``` fenced code block. "
    "No commentary outside the fence.\n"
    "2. Use ONLY the tables and columns in `schema.tables`. Do not invent names. The "
    "qi_* tables are unqualified — reference them as `qi_statements`, `qi_statement_tables`, "
    "etc. (they resolve to spark_catalog.default.qi_*).\n"
    "3. The dialect is Apache Spark SQL 4.x. Use:\n"
    "   - `CAST(x AS DATE)` instead of `x::date`\n"
    "   - `CAST(x AS DECIMAL(10,4))` instead of `x::decimal`\n"
    "   - String concat: `CONCAT(a, b)` or `||` (both work)\n"
    "   - DO NOT use `FILTER (WHERE ...)` — use `SUM(CASE WHEN cond THEN x ELSE 0 END)` instead\n"
    "   - DO NOT use `DISTINCT ON` — use a window function (ROW_NUMBER + qualify) instead\n"
    "   - `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY col)` works\n"
    "   - `DATE_TRUNC('month', col)` works\n"
    "   - `current_date()`, `current_timestamp()` — note the parentheses\n"
    "4. ALWAYS apply a LIMIT (default 200) unless the user asked for an aggregate.\n"
    "5. For cost calculations, same join rules as DuckDB but write timestamp literals as "
    "`TIMESTAMP '2099-12-31'` (Spark also accepts this).\n"
    "6. Query Intel (qi_*) tables answer questions about what queries ran. Join "
    "qi_statement_tables / qi_statement_columns to qi_statements on statement_id.\n"
    "7. Boolean columns (is_off_hours, has_select_star, …) — compare to TRUE/FALSE directly.\n"
    "8. Byte-size thresholds: write the integer literal directly (`107374182400` for 100 GB), "
    "or `CAST(100 AS BIGINT) * 1073741824`. Do NOT write `100 * 1024 * 1024 * 1024` — every operand "
    "is a 32-bit INT, the partial product overflows, and Spark refuses to evaluate it.\n"
    "9. Lineage tables (`table_lineage`, `column_lineage`, `lineage_rollups`) cover read/write "
    "graphs and entity attribution (job / notebook / pipeline / dashboard / DBSQL query). "
    "Event class is encoded in source/target nullability: source NOT NULL + target NULL = "
    "read-only; source NULL + target NOT NULL = write-only; both NOT NULL = read-write. ALWAYS "
    "filter the relevant side IS NOT NULL when counting upstream/downstream neighbours. "
    "Filter `direct_access = TRUE` to skip transitive dependencies. column_lineage drops events "
    "without a source — write-only edges visible in table_lineage are NOT in column_lineage. "
    "For per-table tile counts use `lineage_rollups` (one row per (data_origin, full_name)). "
    "Join via `statement_id` to query_history / qi_statements, and via split catalog/schema/"
    "table_name columns to databricks_meta.\n"
    "10. Audit tables (`audit_events`, `assistant_events`) cover Databricks audit trails. "
    "audit_events: one row per (service_name, action_name) event; key filters are "
    "`response_status_code` (200 = success, non-200 = error), `audit_level` "
    "(ACCOUNT_LEVEL = workspace_id='0', WORKSPACE_LEVEL otherwise), `user_identity_email` "
    "(pre-extracted from the user_identity STRUCT — prefer over user_identity.email). "
    "Common service_name values: unityCatalog, notebook, SQL, accounts, clusters, jobs, "
    "dbfs, mlflow. assistant_events captures user-submitted Databricks Assistant prompts "
    "(autocomplete excluded); `initiated_by` is the user email, `user_agent` is the surface.\n\n"
    "SCHEMA (JSON):\n"
)


# Spark + materialized mode: base PG tables have been copied into
# spark_catalog.default as managed Delta tables. They MUST be referenced
# with the 3-part name (the JDBC temp views are intentionally dropped to
# avoid shadowing). qi_* are already Delta and unqualified — unchanged.
_SPARK_RULES_MATERIALIZED = (
    "You are a Spark SQL analyst for a Databricks billing dashboard. Translate the user's "
    "natural-language question into a single Spark SQL query that runs against managed Delta "
    "tables in `spark_catalog.default` plus the qi_* Delta tables described in the schema JSON "
    "below.\n\n"
    "OUTPUT RULES:\n"
    "1. Return ONLY one SQL statement, wrapped in a ```sql ... ``` fenced code block. "
    "No commentary outside the fence.\n"
    "2. The base tables (billing_usage, list_prices, clusters, warehouses, jobs, workspaces, "
    "query_history, databricks_meta, table_lineage, column_lineage, lineage_rollups) have been "
    "MATERIALISED as managed Delta tables in spark-warehouse. Reference them with the THREE-PART "
    "name `spark_catalog.default.<table>` — e.g. `FROM spark_catalog.default.billing_usage b "
    "JOIN spark_catalog.default.list_prices p ON ...`. qi_* tables are also in "
    "spark_catalog.default but Spark's resolution allows them unqualified.\n"
    "3. The dialect is Apache Spark SQL 4.x. Use:\n"
    "   - `CAST(x AS DATE)` instead of `x::date`\n"
    "   - `CAST(x AS DECIMAL(10,4))` instead of `x::decimal`\n"
    "   - String concat: `CONCAT(a, b)` or `||`\n"
    "   - DO NOT use `FILTER (WHERE ...)` — use `SUM(CASE WHEN cond THEN x ELSE 0 END)` instead\n"
    "   - DO NOT use `DISTINCT ON` — use a window function (ROW_NUMBER + qualify)\n"
    "   - `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY col)` works\n"
    "   - `DATE_TRUNC('month', col)` works\n"
    "   - `current_date()`, `current_timestamp()` — note the parentheses\n"
    "4. ALWAYS apply a LIMIT (default 200) unless the user asked for an aggregate.\n"
    "5. For cost calculations, prefer `billing_usage.usage_usd` when present; otherwise join "
    "`list_prices` on (sku_name, cloud, usage_unit) bounded by the price time window.\n"
    "6. Query Intel (qi_*) tables answer questions about what queries ran. Join "
    "qi_statement_tables / qi_statement_columns to qi_statements on statement_id.\n"
    "7. Boolean columns (is_off_hours, has_select_star, …) — compare to TRUE/FALSE directly.\n"
    "8. Byte-size thresholds: write the integer literal directly (`107374182400` for 100 GB), "
    "or `CAST(100 AS BIGINT) * 1073741824`. Do NOT write `100 * 1024 * 1024 * 1024`.\n"
    "9. Lineage tables work the same as in jdbc_views mode (read/write graphs, event class encoded "
    "in source/target nullability, `direct_access` filter, `lineage_rollups` for per-table tile "
    "counts, column_lineage drops no-source events). The ONLY difference is that you now reference "
    "them as `spark_catalog.default.table_lineage` rather than unqualified.\n"
    "10. Audit tables work the same — `audit_events` (filter on response_status_code, audit_level, "
    "service_name, action_name; user is in user_identity_email) and `assistant_events` (Genie "
    "prompts). Reference as `spark_catalog.default.audit_events` and "
    "`spark_catalog.default.assistant_events`.\n\n"
    "SCHEMA (JSON):\n"
)


_SERVER_ROW_CAP = 1000


def _humanize_engine_error(engine: str, exc: Exception, sql: str) -> str:
    """Boil a Spark/DuckDB stack trace down to the meaningful first line +
    a tactical hint when we recognize a common failure pattern.

    The full stack is still visible in `qlog` (server-side query log); the
    user just sees something they can act on.
    """
    raw = str(exc)
    # Take the first non-empty line that looks like an error rather than stack frames.
    first_line = ""
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("at ") or s.startswith("Caused by:"):
            continue
        first_line = s
        break
    if not first_line:
        first_line = raw.splitlines()[0] if raw else type(exc).__name__

    msg = f"SQL execution failed on the {engine} engine: {first_line}"

    # Tactical hints for patterns we've seen the LLM walk into.
    hints: list[str] = []
    raw_l = raw.lower()
    if "arithmetic_overflow" in raw_l or "integer overflow" in raw_l:
        hints.append(
            "The LLM likely wrote `100 * 1024 * 1024 * 1024` (all INT32 operands → overflow). "
            "Try rewriting your question so the model writes the byte literal directly, "
            "e.g. `read_bytes > 107374182400` for 100 GB."
        )
    if "table_or_view_not_found" in raw_l or "unresolved_table" in raw_l:
        # Extract the missing table name from the error message so the hint
        # is specific.
        import re as _re
        m = _re.search(r"`([^`]+)`", raw)
        missing = m.group(1) if m else None
        if missing and missing.startswith("qi_"):
            hints.append(
                f"The Query Profiler table `{missing}` isn't populated in this engine. "
                "Click 'Extract query profiler' in Data Management (engine=spark) to populate it."
            )
        elif missing:
            hints.append(
                f"Spark couldn't find `{missing}`. Base tables (billing_usage, list_prices, clusters, "
                "warehouses, jobs, workspaces, query_history) are registered as temp views over the "
                "latest parquet snapshot at session-init — try restarting the backend container if "
                "this just appeared. qi_* tables come from the spark-warehouse — re-run "
                "'Extract query profiler' if they're missing."
            )
        else:
            hints.append(
                "Spark couldn't find one of the tables. Base tables (billing_usage etc.) are temp "
                "views over parquet; qi_* live in spark_catalog.default after 'Extract query profiler'."
            )
    if "ambiguous_reference" in raw_l or "ambiguous column" in raw_l:
        hints.append(
            "A column appears in more than one joined table without a qualifier. "
            "Ask the question more specifically so the LLM aliases the join."
        )
    if hints:
        msg += "\n\nHint: " + " ".join(hints)
    return msg


def _validate_sql(sql: str, dialect: str) -> None:
    """Parse the SQL with sqlglot before sending it to the engine.

    Catches LLM truncation (`...LIMIT ` with no value), unbalanced parens,
    stray fence tokens — anything sqlglot's parser can detect. Raises
    `ValueError` with a clean one-line message; the wrapper in `ask()`
    converts that to a chatbot-failure response that still shows the user
    the full LLM output for diagnosis.
    """
    try:
        import sqlglot
        sqlglot.parse_one(sql, dialect=dialect)
    except Exception as e:  # noqa: BLE001 — sqlglot raises many shapes
        msg = str(e).splitlines()[0] if str(e) else type(e).__name__
        raise ValueError(
            f"Generated SQL failed to parse as {dialect} (likely the LLM truncated mid-statement). "
            f"Parser said: {msg}"
        )


def _execute_duckdb_sql(sql: str, view_mode: str = "real") -> pd.DataFrame:
    """Run a SQL string through DuckDB with billing parquet + qi_* attached.

    Caps the result at `_SERVER_ROW_CAP` rows via DuckDB's relation API so
    the LLM's own LIMIT/ORDER BY semantics are preserved.

    The DuckDB session is built per-request with the caller's `view_mode`
    baked into every view (parquet selection + Postgres-attached views'
    WHERE clauses) so toggling demo/real on the user record immediately
    changes what the chatbot sees.
    """
    _validate_sql(sql, dialect="duckdb")
    con = _build_duckdb(include_qi=True, view_mode=view_mode)
    try:
        return con.execute(sql).fetch_df().head(_SERVER_ROW_CAP)
    finally:
        try:
            con.close()
        except Exception:
            pass


def _execute_spark_sql(sql: str, view_mode: str = "real") -> pd.DataFrame:
    """Run a SQL string through Spark Connect.

    Refreshes the user-facing temp views with the caller's `view_mode`
    BEFORE running so the same caller seeing demo data in the UI gets
    demo data from the chatbot in the same request.
    """
    _validate_sql(sql, dialect="databricks")
    from spark_session import apply_view_mode, get_spark
    apply_view_mode(view_mode)
    spark = get_spark()
    df = spark.sql(sql).limit(_SERVER_ROW_CAP)
    return df.toPandas()


def _extract_sql(response: str) -> str:
    """Pull a SQL statement out of the LLM response.

    Handles three shapes the LLM might emit:
      1. Properly fenced: ```sql\\n<body>\\n```  — the happy path.
      2. Open fence with no close — LLM truncated mid-statement (token-limit
         hit). We still recover the body after the opening fence.
      3. Bare SQL with no fences at all.

    Defense in depth: after extraction, we strip any stray leading/trailing
    fence markers so they can't leak into the executed SQL.
    """
    if not response:
        raise ValueError("Empty LLM response")

    text = response.strip()

    # 1. Properly fenced block (greedy match — the last `` ``` `` ends it)
    m = re.search(r"```(?:sql)?\s*\n(.*)\n```", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        sql = m.group(1)
    else:
        # 2. Open fence with no close (truncated response)
        m = re.search(r"```(?:sql)?\s*\n(.*)", text, flags=re.DOTALL | re.IGNORECASE)
        sql = m.group(1) if m else text

    # 3. Belt-and-suspenders: strip any remaining fence tokens, regardless
    # of whether they had a language tag or just bare backticks.
    sql = re.sub(r"^```(?:sql)?\s*\n?", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\n?```\s*$", "", sql)
    sql = sql.strip()

    if not sql:
        raise ValueError("LLM response contained no extractable SQL")
    return sql.rstrip(";").strip()


def _is_safe_select(sql: str) -> bool:
    """Reject statements that mutate, are clearly malformed, or call multiple statements.

    Catches:
      * Stray markdown fence tokens (``` or ```sql) that the extractor missed.
      * Statements that don't start with SELECT / WITH (the only two shapes
        a single read-only query takes).
      * Multi-statement (;-separated) batches.
      * Forbidden mutation/control verbs.
    """
    cleaned = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()
    if not cleaned:
        return False
    # Stray fence tokens are a smoking gun — the extractor missed something.
    if "```" in cleaned:
        return False
    # Must start with SELECT or WITH (CTE form).
    head = cleaned.lstrip().split(None, 1)[0].upper() if cleaned.split() else ""
    if head not in ("SELECT", "WITH"):
        return False
    if ";" in cleaned.rstrip(";"):
        return False
    forbidden = (
        r"\b(insert|update|delete|drop|alter|create|truncate|attach|detach|"
        r"copy|export|pragma|set|call)\b"
    )
    if re.search(forbidden, cleaned, flags=re.IGNORECASE):
        return False
    return True


def _explain_results(
    user_query: str,
    sql: str,
    rows: list[dict[str, Any]],
    columns: list[str],
    provider: str,
    model: str,
    api_key: Optional[str],
) -> tuple[str, LlmCall]:
    """Ask the LLM to explain the result set; returns (explanation, call_transcript)."""
    preview = pd.DataFrame(rows[:20], columns=columns).to_string(index=False) if rows else "(no rows)"
    explain_system = (
        "You are a Databricks billing analyst. The user asked a question and we ran a SQL "
        "query against billing data. Explain the results in 2-4 short sentences. Cite "
        "specific numbers from the result. Don't restate the SQL. If the result is empty, "
        "say so and hint at why."
    )
    explain_user = (
        f"User question:\n{user_query}\n\n"
        f"SQL run:\n{sql}\n\n"
        f"Result ({len(rows)} rows shown above; first 20 below):\n{preview}"
    )
    started = time.perf_counter()
    raw = ""
    explanation: str
    try:
        raw = llm_helpers.generate_sql_from_text(
            user_query=explain_user,
            system_prompt=explain_system,
            model=model,
            provider=provider,
            api_key=api_key,
            temperature=0.3,
            max_tokens=600,
        )
        explanation = raw.strip()
    except Exception as e:
        logger.warning("Explanation failed: %s", e)
        raw = f"<error: {e}>"
        explanation = (
            f"({len(rows)} row{'s' if len(rows) != 1 else ''} returned. "
            f"Explanation step failed: {e})"
        )
    elapsed = time.perf_counter() - started
    call = LlmCall(
        name="explain_results",
        system_prompt=explain_system,
        user_message=explain_user,
        raw_response=raw,
        elapsed_seconds=elapsed,
    )
    return explanation, call


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    message: str = Field(..., description="Natural-language question")
    provider: str = Field("google", description="LLM provider: google|anthropic|openai|deepseek|azure|ollama|vllm")
    model: str = Field("gemini-2.0-flash", description="Provider-specific model id")
    api_key: Optional[str] = Field(None, description="Override key (else env var)")
    explain: bool = Field(True, description="Run a 2nd LLM call to summarize results")


class LlmCall(BaseModel):
    """One LLM call transcript (for the 'LLM call details' disclosure on the UI)."""
    name: str = Field(description="Logical step: 'sql_generation' or 'explain_results'")
    system_prompt: str
    user_message: str
    raw_response: str
    elapsed_seconds: float


class AskResponse(BaseModel):
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    explanation: Optional[str]
    error: Optional[str] = None
    # Top-level transcript metadata
    user_message: str
    provider: str
    model: str
    total_elapsed_seconds: float
    # All LLM calls made for this turn (sql_generation + optional explain_results)
    llm_calls: list[LlmCall] = Field(default_factory=list)
    # --- Deprecated legacy fields (kept for old client compat); same data as llm_calls[0] ---
    system_prompt: str
    raw_llm_response: str
    elapsed_seconds: float


class ModelsResponse(BaseModel):
    models: dict[str, list[str]]


class DownloadRequest(BaseModel):
    sql: str = Field(..., description="SQL previously generated by /ask. Re-validated and re-executed.")
    format: str = Field("csv", pattern="^(csv|xlsx)$")
    filename: Optional[str] = Field(None, description="Filename stem (no extension)")
    max_rows: int = Field(100_000, ge=1, le=1_000_000)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_MODELS_CACHE_TTL_SECONDS = int(os.getenv("CHAT_MODELS_CACHE_TTL", "600"))  # 10 min default
_models_cache: Optional[tuple[float, dict[str, list[str]]]] = None
_models_lock = asyncio.Lock()


@router.get("/models", response_model=ModelsResponse)
async def list_models(refresh: bool = False):
    """Return available models per provider, queried at runtime.

    Why this is non-trivial:

    * ``llm_helpers.get_available_models()`` is **synchronous** and makes HTTP
      calls to every configured LLM provider. Calling it directly in an
      async endpoint blocks the event loop, which queues every other
      request behind it. With one uvicorn worker the whole UI freezes
      while it runs.
    * We therefore run it in a thread pool (``run_in_threadpool``) so other
      requests keep flowing.
    * We cache the result for ``CHAT_MODELS_CACHE_TTL`` seconds so repeat
      navigations don't re-probe every provider.
    * An ``asyncio.Lock`` ensures concurrent callers share a single
      in-flight enumeration instead of fanning out N parallel calls.
    * On enumeration failure we serve the previous cached value (if any)
      rather than 500-ing.

    Pass ``?refresh=1`` to force a re-enumeration.
    """
    global _models_cache
    now = time.monotonic()

    if not refresh and _models_cache and (now - _models_cache[0] < _MODELS_CACHE_TTL_SECONDS):
        return ModelsResponse(models=_models_cache[1])

    async with _models_lock:
        # Re-check inside the lock — another waiter may have refreshed it.
        now = time.monotonic()
        if not refresh and _models_cache and (now - _models_cache[0] < _MODELS_CACHE_TTL_SECONDS):
            return ModelsResponse(models=_models_cache[1])

        try:
            models = await run_in_threadpool(llm_helpers.get_available_models)
        except Exception as e:
            logger.exception("Failed to enumerate models")
            if _models_cache:
                logger.warning("Serving stale model list from %.0fs ago", now - _models_cache[0])
                return ModelsResponse(models=_models_cache[1])
            raise HTTPException(status_code=500, detail=str(e))

        _models_cache = (time.monotonic(), models)
        return ModelsResponse(models=models)


@router.get("/system-prompt")
async def system_prompt_preview():
    """Preview the rendered system prompt (debug/diagnostic)."""
    try:
        return {"prompt": _build_system_prompt()}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/schema")
async def schema_preview():
    """Preview the structured schema JSON the LLM sees as context."""
    try:
        return _build_schema_json()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/ask", response_model=AskResponse)
async def ask(
    req: AskRequest,
    user: AuthedUser = Depends(get_current_user),
):
    """One-shot ask: NL question -> SQL -> result -> explanation.

    Dispatches based on the active Query Intel engine:
      * duckdb (default) — generates DuckDB SQL, executes via the in-memory
        DuckDB session with billing parquet + Postgres-attached qi_* views.
      * spark — generates Spark SQL, executes via Spark Connect against
        spark_catalog.default.qi_*.

    Every view registered in the DuckDB session AND every Spark temp
    view registered in the Spark session is filtered by the caller's
    `view_mode` (real / demo) so toggling demo ↔ real on the user record
    immediately changes the dataset the chatbot reasons over.
    """
    qlog = get_query_logger()
    started = time.perf_counter()
    view_mode = user.viewing_data_mode

    # Pull the active engine + spark mode. Use a fresh session here (chat
    # router is not currently auth-scoped to a DB dependency).
    from database import async_session
    from engine_config import get_engine as get_qi_engine, get_spark_mode

    async with async_session() as _db:
        engine = await get_qi_engine(_db)
        spark_mode = await get_spark_mode(_db) if engine == "spark" else "jdbc_views"

    try:
        system_prompt = _build_system_prompt(engine, spark_mode)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # 1. Generate SQL
    sql_call_started = time.perf_counter()
    try:
        raw = llm_helpers.generate_sql_from_text(
            user_query=req.message,
            system_prompt=system_prompt,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key,
            temperature=0.2,
            # 65000 gives room for very long Meta Explorer / Query Profiler
            # responses (multi-CTE Spark queries with extensive comments, or
            # reasoning models that emit chain-of-thought before the SQL).
            # Earlier caps (1500/4000/8000) truncated complex queries
            # mid-statement, leaking partial SQL to the executor as
            # PARSE_SYNTAX_ERROR. Most providers accept this — the model's
            # own context-window limit is the practical ceiling.
            max_tokens=65000,
        )
    except Exception as e:
        qlog.log_execution(
            user_query=req.message,
            system_prompt=system_prompt,
            provider=req.provider,
            model=req.model,
            generated_code="",
            execution_type="sql",
            execution_status="error",
            error_message=str(e),
            execution_time_seconds=time.perf_counter() - started,
        )
        raise HTTPException(status_code=502, detail=f"SQL generation failed: {e}")

    sql_call_elapsed = time.perf_counter() - sql_call_started
    sql_call = LlmCall(
        name="sql_generation",
        system_prompt=system_prompt,
        user_message=req.message,
        raw_response=raw,
        elapsed_seconds=sql_call_elapsed,
    )

    sql = _extract_sql(raw)

    # When the LLM output fails the safety pre-check OR fails to execute, we
    # still want the user to see the raw response + the extracted SQL in the
    # UI so they can diagnose. Return AskResponse(error=...) with rows=[]
    # rather than raising — the frontend renders the same LLM-call disclosure
    # panel either way.
    def _failure_response(reason: str) -> AskResponse:
        elapsed_total = time.perf_counter() - started
        qlog.log_execution(
            user_query=req.message,
            system_prompt=system_prompt,
            provider=req.provider,
            model=req.model,
            generated_code=sql,
            execution_type="sql",
            execution_status="error",
            error_message=reason,
            execution_time_seconds=elapsed_total,
        )
        return AskResponse(
            sql=sql,
            columns=[],
            rows=[],
            row_count=0,
            truncated=False,
            explanation=None,
            error=reason,
            user_message=req.message,
            provider=req.provider,
            model=req.model,
            total_elapsed_seconds=elapsed_total,
            llm_calls=[sql_call],
            system_prompt=system_prompt,
            raw_llm_response=raw,
            elapsed_seconds=sql_call_elapsed,
        )

    if not _is_safe_select(sql):
        return _failure_response(
            "Generated SQL was rejected (only single SELECT / WITH statements are allowed, "
            "no mutations, no multi-statement batches, no stray markdown fences). "
            "See the LLM response below for what the model actually produced."
        )

    # 2. Execute the SQL via the appropriate engine.
    try:
        if engine == "spark":
            df = await run_in_threadpool(_execute_spark_sql, sql, view_mode)
        else:
            df = await run_in_threadpool(_execute_duckdb_sql, sql, view_mode)
    except Exception as e:
        return _failure_response(_humanize_engine_error(engine, e, sql))

    # JSON-friendly conversion
    df = df.fillna("")
    rows = df.head(200).to_dict(orient="records")
    columns = list(df.columns)

    # 3. Explain (optional) — captures its own LlmCall transcript
    explanation: Optional[str] = None
    explain_call: Optional[LlmCall] = None
    if req.explain:
        explanation, explain_call = _explain_results(
            user_query=req.message,
            sql=sql,
            rows=rows,
            columns=columns,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key,
        )

    elapsed = time.perf_counter() - started
    qlog.log_execution(
        user_query=req.message,
        system_prompt=system_prompt,
        provider=req.provider,
        model=req.model,
        generated_code=sql,
        execution_type="sql",
        llm_explanation=explanation,
        execution_status="success",
        result_summary=f"{len(df)} rows, {len(columns)} cols",
        result_row_count=int(len(df)),
        execution_time_seconds=elapsed,
    )

    llm_calls = [sql_call] + ([explain_call] if explain_call else [])
    return AskResponse(
        sql=sql,
        columns=columns,
        rows=rows,
        row_count=int(len(df)),
        truncated=len(df) > 200,
        explanation=explanation,
        user_message=req.message,
        provider=req.provider,
        model=req.model,
        total_elapsed_seconds=elapsed,
        llm_calls=llm_calls,
        # legacy fields (same as llm_calls[0])
        system_prompt=system_prompt,
        raw_llm_response=raw,
        elapsed_seconds=sql_call_elapsed,
    )


def _safe_filename(stem: Optional[str], default: str = "chatbot-result") -> str:
    """Sanitize filename stem: kebab-case, no extension, capped length."""
    s = (stem or default).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")[:80]
    return s or default


@router.post("/download")
async def download_results(
    req: DownloadRequest,
    user: AuthedUser = Depends(get_current_user),
):
    """Re-execute a previously-generated SQL and stream the FULL result set as CSV or XLSX.

    The SQL is re-validated against the same safety rules as /ask. Capped at
    `max_rows` (default 100k) to prevent runaway downloads. The DuckDB /
    Spark views are filtered by the caller's `view_mode` so the export
    matches what they saw on the screen.
    """
    if not _is_safe_select(req.sql):
        raise HTTPException(status_code=400, detail="SQL rejected (only single SELECT statements are allowed).")

    view_mode = user.viewing_data_mode

    from database import async_session
    from engine_config import get_engine as get_qi_engine
    async with async_session() as _db:
        engine = await get_qi_engine(_db)

    try:
        if engine == "spark":
            _validate_sql(req.sql, dialect="databricks")
            from spark_session import apply_view_mode, get_spark
            apply_view_mode(view_mode)
            spark = get_spark()
            df = await run_in_threadpool(
                lambda: spark.sql(req.sql).limit(int(req.max_rows)).toPandas()
            )
        else:
            _validate_sql(req.sql, dialect="duckdb")
            con = _build_duckdb(include_qi=True, view_mode=view_mode)
            try:
                df = con.execute(req.sql).fetch_df().head(int(req.max_rows))
            finally:
                try:
                    con.close()
                except Exception:
                    pass
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SQL execution failed: {e}")

    timestamp = time.strftime("%Y%m%d-%H%M")
    stem = f"{_safe_filename(req.filename)}-{timestamp}"

    if req.format == "csv":
        buf = io.StringIO()
        # UTF-8 BOM so Excel auto-detects encoding when opening
        buf.write("﻿")
        df.to_csv(buf, index=False, lineterminator="\r\n")
        body = buf.getvalue().encode("utf-8")
        return StreamingResponse(
            io.BytesIO(body),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{stem}.csv"',
                "X-Row-Count": str(len(df)),
            },
        )

    # xlsx
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Result")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}.xlsx"',
            "X-Row-Count": str(len(df)),
        },
    )
