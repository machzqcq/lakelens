"""Query Intel ETL — turn `query_history` parquet into structured analysis tables.

Run via the "Extract query intel" button in Data Management, which hits
POST /api/admin/extract-query-intel. The transformer:

1. Reads the latest demo_query_history_*.parquet (or query_history_*.parquet)
   from the data directory.
2. Flattens nested structs (compute, query_source, query_parameters, query_tags).
3. Parses statement_text with sqlglot (databricks dialect) to extract:
     * tables referenced (catalog, schema, table) + the role each played
     * columns referenced (select/where/groupby/orderby/join/having/aggregate)
     * SQL features (CTE, subquery, window, select *, cross join)
4. Categorizes errors into PARSE / PERMISSION / NOT_FOUND / OOM / TIMEOUT / OTHER.
5. Derives metrics (pruning ratio, selectivity, waiting %, off-hours flag, …).
6. Replaces (TRUNCATE + bulk INSERT) into the qi_* tables — these are
   derived data, so we rebuild them in full on every run.

Designed to be idempotent. Failure of any individual statement-level parse
does not fail the run; we simply note `is_sql=false` and skip entity
extraction for that row.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    QiExtractRun,
    QiStatement,
    QiStatementColumn,
    QiStatementError,
    QiStatementParameter,
    QiStatementTable,
    QiStatementTag,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# sqlglot — parse SQL; we lean on the databricks dialect.
# ---------------------------------------------------------------------------

import sqlglot
from sqlglot import exp

# Silence sqlglot's per-statement "unsupported syntax, falling back to Command"
# warnings — they're expected (we throw all 50k statements at it) and they
# spam server logs.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

DIALECT = "databricks"

BATCH_SIZE = 1000

# ---------------------------------------------------------------------------
# Heuristics — is this statement_text actually SQL, or Python/Scala code?
# query_history captures Databricks notebook cells, many of which are
# python/scala. We don't want to feed those to sqlglot.
# ---------------------------------------------------------------------------

_PYTHON_TELLS = (
    "dbutils.",
    "spark.sql(",
    "spark.read",
    "df.write",
    "df.show",
    "df.collect",
    " = set([",
    " = [",
    "import ",
    "def ",
    "lambda ",
    "F.col(",
    "self._",
    "print(",
    "if __name__",
)

_SQL_FIRST_KEYWORDS = {
    "SELECT", "INSERT", "MERGE", "CREATE", "DROP", "ALTER", "GRANT", "REVOKE",
    "USE", "SHOW", "DESCRIBE", "EXPLAIN", "REFRESH", "SET", "OPTIMIZE",
    "ANALYZE", "VACUUM", "COPY", "REPLACE", "WITH", "CALL", "DELETE", "UPDATE",
    "TRUNCATE", "COMMENT",
}


def _looks_like_sql(text: str) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    # Reject Python-y / Scala-y first lines fast.
    head = stripped[:200]
    for tell in _PYTHON_TELLS:
        if tell in head:
            return False
    # Strip leading SQL comments to find the first non-comment keyword.
    lines = [ln for ln in stripped.splitlines() if ln.strip() and not ln.strip().startswith("--")]
    if not lines:
        return False
    first_token = lines[0].lstrip().split(None, 1)[0].upper().strip(";")
    return first_token in _SQL_FIRST_KEYWORDS


# ---------------------------------------------------------------------------
# Error categorization
# ---------------------------------------------------------------------------

_ERROR_CODE_RE = re.compile(r"\[([A-Z][A-Z0-9_]+)\]")
_SQLSTATE_RE = re.compile(r"SQLSTATE:\s*([A-Z0-9]+)", re.IGNORECASE)
_BACKTICK_OBJECT_RE = re.compile(r"`([^`]+)`(?:\.`([^`]+)`)?(?:\.`([^`]+)`)?")


_ERROR_CATEGORY_MAP = [
    ("PERMISSION", ("INSUFFICIENT_PERMISSIONS", "PERMISSION_DENIED", "ACCESS_DENIED")),
    ("NOT_FOUND",  ("TABLE_OR_VIEW_NOT_FOUND", "UNRESOLVED_COLUMN", "UNRESOLVED_TABLE",
                    "SCHEMA_NOT_FOUND", "DATABASE_NOT_FOUND", "COLUMN_NOT_FOUND")),
    ("PARSE",      ("PARSE_SYNTAX_ERROR", "PARSE_ERROR", "INVALID_SYNTAX")),
    ("OOM",        ("OUT_OF_MEMORY", "OOM", "MEMORY_LIMIT_EXCEEDED")),
    ("TIMEOUT",    ("STATEMENT_TIMEOUT", "TIMEOUT", "QUERY_TIMEOUT")),
    ("ANALYSIS",   ("ANALYSIS_ERROR", "AMBIGUOUS_REFERENCE", "DATATYPE_MISMATCH",
                    "GROUP_BY_POS_OUT_OF_RANGE", "INVALID_PARAMETER_VALUE")),
    ("DEPENDENCY", ("FAILED_DEPENDENCY", "DELTA_VERSIONS_NOT_CONTIGUOUS")),
]


def _categorize_error(msg: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (category, error_code, sqlstate)."""
    if not msg:
        return None, None, None
    code_match = _ERROR_CODE_RE.search(msg)
    error_code = code_match.group(1) if code_match else None
    sqlstate_match = _SQLSTATE_RE.search(msg)
    sqlstate = sqlstate_match.group(1) if sqlstate_match else None
    upper = msg.upper()
    if error_code:
        for cat, codes in _ERROR_CATEGORY_MAP:
            if error_code in codes:
                return cat, error_code, sqlstate
    # fall back to substring scan
    for cat, codes in _ERROR_CATEGORY_MAP:
        for needle in codes:
            if needle in upper:
                return cat, error_code, sqlstate
    return "OTHER", error_code, sqlstate


def _extract_error_object(msg: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Pull the first `backticked.object` reference and any user@domain from the error."""
    if not msg:
        return None, None
    obj = None
    m = _BACKTICK_OBJECT_RE.search(msg)
    if m:
        parts = [p for p in m.groups() if p]
        obj = ".".join(parts)
    user = None
    user_match = re.search(r"User\s+([\w\.-]+(?:@[\w\.-]+)?)", msg)
    if user_match:
        user = user_match.group(1)
    return obj, user


# ---------------------------------------------------------------------------
# Client driver parsing
# ---------------------------------------------------------------------------

def _parse_driver(driver: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Map 'PyDatabricksSqlConnector, 4.2.6' -> ('PyConnector', '4.2.6')."""
    if not driver:
        return None, None
    name_version = [p.strip() for p in driver.split(",", 1)]
    name = name_version[0] if name_version else None
    version = name_version[1] if len(name_version) > 1 else None
    family = None
    if name:
        n = name.lower()
        if "pydatabricks" in n or "pythonsql" in n:
            family = "PyConnector"
        elif "jdbc" in n:
            family = "JDBC"
        elif "odbc" in n:
            family = "ODBC"
        elif "execapi" in n.replace(" ", ""):
            family = "ExecApi"
        elif "adbc" in n:
            family = "ADBC"
        elif "nodejs" in n:
            family = "NodeJS"
        else:
            family = "Other"
    return family, version


def _principal_kind(executed_by: Optional[str], user_id: Optional[str]) -> str:
    if not executed_by and not user_id:
        return "unknown"
    if executed_by and "@" in executed_by:
        return "human"
    if user_id and user_id.isdigit():
        return "service"
    return "unknown"


# ---------------------------------------------------------------------------
# sqlglot extraction — tables, columns, SQL features.
# ---------------------------------------------------------------------------

# Statement types that genuinely write/modify a target table. The first
# child Table of these expression types is the "write" target; the rest
# are reads.
_WRITE_EXP_TYPES = (exp.Insert, exp.Update, exp.Delete, exp.Merge,
                    exp.Create, exp.Alter, exp.Drop)


def _normalize_sql(text: str) -> Optional[str]:
    """Return a stripped, parameter-stripped form for dedup hashing."""
    try:
        tree = sqlglot.parse_one(text, dialect=DIALECT)
        if tree is None:
            return None
        # Replace every literal with a placeholder to collapse semantically-
        # equivalent queries that only differ in WHERE values.
        for lit in tree.find_all(exp.Literal):
            lit.set("this", "?")
        return tree.sql(dialect=DIALECT, normalize=True)
    except Exception:  # noqa: BLE001 — sqlglot raises many shapes
        return None


def _extract_sql_features(text: str) -> dict[str, Any]:
    """Parse SQL, return dict with: is_sql, tables, columns, normalized_sql_hash,
    has_select_star, has_cross_join, has_cte, has_subquery, has_window,
    is_describe_or_show, is_dml, is_ddl, is_grant_revoke."""
    out: dict[str, Any] = {
        "is_sql": False,
        "tables": [],
        "columns": [],
        "normalized_sql_hash": None,
        "has_select_star": False,
        "has_cross_join": False,
        "has_cte": False,
        "has_subquery": False,
        "has_window": False,
        "is_describe_or_show": False,
        "is_dml": False,
        "is_ddl": False,
        "is_grant_revoke": False,
    }
    if not _looks_like_sql(text):
        # Even non-SQL Python cells can still mention catalog.table —
        # we extract those as a best-effort below.
        out["tables"] = _extract_tables_from_freetext(text)
        return out

    try:
        tree = sqlglot.parse_one(text, dialect=DIALECT)
    except Exception:  # noqa: BLE001
        tree = None
    if tree is None:
        out["tables"] = _extract_tables_from_freetext(text)
        return out

    out["is_sql"] = True

    # Normalized hash
    try:
        norm = _normalize_sql(text)
        if norm:
            out["normalized_sql_hash"] = hashlib.sha1(norm.encode("utf-8")).hexdigest()
    except Exception:
        pass

    # Categorical SQL flavor
    out["is_dml"] = isinstance(tree, (exp.Insert, exp.Update, exp.Delete, exp.Merge))
    out["is_ddl"] = isinstance(tree, (exp.Create, exp.Drop, exp.Alter))
    out["is_grant_revoke"] = isinstance(tree, (exp.Grant,)) or text.strip().upper().startswith(("GRANT ", "REVOKE "))

    head = text.strip().upper().split(None, 1)[0]
    out["is_describe_or_show"] = head in ("DESCRIBE", "DESC", "SHOW")

    # Features
    out["has_cte"] = bool(tree.find(exp.With))
    out["has_subquery"] = bool(tree.find(exp.Subquery))
    out["has_window"] = bool(tree.find(exp.Window))
    out["has_select_star"] = any(isinstance(s, exp.Star) for s in tree.find_all(exp.Star))
    # Cross-join detection: a Join node without 'on' / 'using'.
    for j in tree.find_all(exp.Join):
        if not j.args.get("on") and not j.args.get("using"):
            kind = (j.args.get("kind") or "").upper()
            if kind in ("CROSS", "", None):
                out["has_cross_join"] = True
                break

    # ---- Tables ---------------------------------------------------------
    # cte_names: names declared in WITH clauses — those are temp views, not tables.
    cte_names: set[str] = set()
    for cte in tree.find_all(exp.CTE):
        alias = cte.alias_or_name
        if alias:
            cte_names.add(alias.lower())

    write_target_id: Optional[int] = None
    if isinstance(tree, _WRITE_EXP_TYPES):
        first_table = tree.find(exp.Table)
        if first_table is not None:
            write_target_id = id(first_table)

    seen: set[tuple] = set()
    tables_out: list[dict] = []
    for tbl in tree.find_all(exp.Table):
        name = tbl.name
        if not name:
            continue
        if name.lower() in cte_names:
            tables_out.append({
                "catalog": None, "schema": None, "table_name": name,
                "fully_qualified": name,
                "role": "cte", "is_system_table": False, "is_temp": True,
            })
            continue
        # `db` is the schema slot in sqlglot; `catalog` is the catalog slot.
        catalog = tbl.args.get("catalog").name if tbl.args.get("catalog") else None
        schema = tbl.args.get("db").name if tbl.args.get("db") else None
        fq = ".".join([p for p in (catalog, schema, name) if p])
        key = (catalog, schema, name)
        is_write_target = id(tbl) == write_target_id
        role = "write" if is_write_target else "read"
        # Dedup so a multi-reference target doesn't blow up the table.
        dedup_key = (catalog, schema, name, role)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        tables_out.append({
            "catalog": catalog,
            "schema": schema,
            "table_name": name,
            "fully_qualified": fq,
            "role": role,
            "is_system_table": (catalog == "system") if catalog else False,
            "is_temp": False,
        })
    out["tables"] = tables_out

    # ---- Columns --------------------------------------------------------
    columns: list[dict] = []
    seen_cols: set[tuple] = set()

    def _push(col_name: str, table_hint: Optional[str], role: str) -> None:
        key = (col_name, table_hint, role)
        if key in seen_cols:
            return
        seen_cols.add(key)
        columns.append({"column_name": col_name, "table_hint": table_hint, "role": role})

    # WHERE
    for w in tree.find_all(exp.Where):
        for c in w.find_all(exp.Column):
            _push(c.name, c.table or None, "where")
    # GROUP BY
    for g in tree.find_all(exp.Group):
        for c in g.find_all(exp.Column):
            _push(c.name, c.table or None, "groupby")
    # ORDER BY
    for o in tree.find_all(exp.Order):
        for c in o.find_all(exp.Column):
            _push(c.name, c.table or None, "orderby")
    # HAVING
    for h in tree.find_all(exp.Having):
        for c in h.find_all(exp.Column):
            _push(c.name, c.table or None, "having")
    # JOIN conditions
    for j in tree.find_all(exp.Join):
        on = j.args.get("on")
        if on:
            for c in on.find_all(exp.Column):
                _push(c.name, c.table or None, "join")
    # SELECT projection (only when no Star — Star yields no columns)
    sel = tree.find(exp.Select)
    if sel:
        for proj in sel.expressions or []:
            for c in proj.find_all(exp.Column):
                _push(c.name, c.table or None, "select")
    # Aggregates (count/sum/avg/max/min) — useful signal even if also captured under select
    for f in tree.find_all(exp.AggFunc):
        for c in f.find_all(exp.Column):
            _push(c.name, c.table or None, "aggregate")

    out["columns"] = columns
    return out


# Fallback table extraction for non-SQL cells: scan for `catalog`.`schema`.`table`
# patterns in raw text. Matches backticked Databricks-style 3-part names.
_FREETEXT_FQ_RE = re.compile(
    r"`([A-Za-z0-9_\-]+)`\s*\.\s*`?([A-Za-z0-9_]+)`?\s*\.\s*`?([A-Za-z0-9_]+)`?"
)


def _extract_tables_from_freetext(text: str) -> list[dict]:
    if not text:
        return []
    seen: set[tuple] = set()
    out: list[dict] = []
    for m in _FREETEXT_FQ_RE.finditer(text):
        catalog, schema, table = m.group(1), m.group(2), m.group(3)
        key = (catalog, schema, table)
        if key in seen:
            continue
        seen.add(key)
        fq = f"{catalog}.{schema}.{table}"
        out.append({
            "catalog": catalog,
            "schema": schema,
            "table_name": table,
            "fully_qualified": fq,
            "role": "reference",
            "is_system_table": catalog == "system",
            "is_temp": False,
        })
    return out


# ---------------------------------------------------------------------------
# Source-category derivation
# ---------------------------------------------------------------------------

def _source_category(qs: Optional[dict]) -> str:
    if not qs:
        return "AD_HOC"
    job_info = qs.get("job_info") or {}
    if job_info.get("job_id"):
        return "JOB"
    pipe = qs.get("pipeline_info") or {}
    if pipe.get("pipeline_id"):
        return "PIPELINE"
    if qs.get("notebook_id"):
        return "NOTEBOOK"
    if qs.get("dashboard_id") or qs.get("legacy_dashboard_id"):
        return "DASHBOARD"
    if qs.get("alert_id"):
        return "ALERT"
    if qs.get("sql_query_id"):
        return "SQL_QUERY"
    if qs.get("genie_space_id"):
        return "GENIE"
    return "AD_HOC"


# ---------------------------------------------------------------------------
# query_parameters AST — extract just the names and string values, not the
# whole tree.
# ---------------------------------------------------------------------------

def _flatten_query_parameters(params: Any) -> list[dict]:
    """The Spark AST is huge but we only need parameter names and their
    string literal values, which live at
        named_parameters.<PARAM_NAME>.exprs[0].literal.string_value
    """
    if not params:
        return []
    if not isinstance(params, dict):
        return []
    named = params.get("named_parameters")
    if not isinstance(named, dict):
        return []
    out: list[dict] = []
    for name, ast in named.items():
        if not isinstance(ast, dict):
            out.append({"param_name": name, "param_value": None, "param_type": None})
            continue
        exprs = ast.get("exprs") or []
        if not exprs:
            out.append({"param_name": name, "param_value": None, "param_type": None})
            continue
        first = exprs[0] if isinstance(exprs[0], dict) else {}
        literal = first.get("literal") or {}
        ptype_struct = first.get("data_type") or {}
        ptype = ptype_struct.get("type_name") if isinstance(ptype_struct, dict) else None
        value = None
        for k in ("string_value", "int_value", "long_value", "double_value",
                  "boolean_value", "date_value", "timestamp_value"):
            if literal.get(k) is not None:
                value = str(literal[k])
                break
        out.append({"param_name": name, "param_value": value, "param_type": ptype})
    return out


def _flatten_query_tags(tags: Any) -> list[dict]:
    if not tags:
        return []
    if not isinstance(tags, dict):
        return []
    return [{"tag_key": str(k), "tag_value": (str(v) if v is not None else None)}
            for k, v in tags.items()]


# ---------------------------------------------------------------------------
# Project keyword extraction — for the "cost by project keyword" scenarios.
# Pulls catalog + schema names, parameter names, tag values; strips trivial
# stop-tokens like 'default' / 'hive_metastore'.
# ---------------------------------------------------------------------------

_KEYWORD_STOPLIST = {
    "default", "main", "system", "hive_metastore", "information_schema",
    "tmp", "test", "dev", "prod", "uat", "staging", "demo", "sandbox",
    "schema", "table", "user", "users",
}


def _project_keywords(tables: list[dict], tags: list[dict], params: list[dict]) -> list[str]:
    kws: set[str] = set()
    for t in tables:
        for piece in (t.get("catalog"), t.get("schema")):
            if not piece:
                continue
            lp = piece.lower()
            # split on common token separators
            for tok in re.split(r"[_\-\.\s]+", lp):
                if tok and tok not in _KEYWORD_STOPLIST and len(tok) > 2:
                    kws.add(tok)
    for t in tags:
        v = t.get("tag_value")
        if v and v.lower() not in _KEYWORD_STOPLIST:
            kws.add(v.lower())
    for p in params:
        n = p.get("param_name")
        if n and n.lower() not in _KEYWORD_STOPLIST and len(n) > 2:
            kws.add(n.lower())
    return sorted(kws)[:30]  # cap


# ---------------------------------------------------------------------------
# Off-hours / weekend
# ---------------------------------------------------------------------------

def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return None


def _safe_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return s or None


def _ratio(num: Optional[int], denom: Optional[int]) -> Optional[float]:
    if num is None or denom is None or denom == 0:
        return None
    return round(num / denom, 4)


# ---------------------------------------------------------------------------
# Row transform
# ---------------------------------------------------------------------------

def _transform_row(r: dict) -> dict[str, Any]:
    """Produce all output records for one query_history row.

    Returns a dict with keys:
      statement: dict (for qi_statements)
      tables:    list[dict] (for qi_statement_tables)
      columns:   list[dict] (for qi_statement_columns)
      tags:      list[dict] (for qi_statement_tags)
      params:    list[dict] (for qi_statement_parameters)
      error:     Optional[dict] (for qi_statement_errors, None if not failed)
    """
    statement_id = _safe_str(r.get("statement_id"))
    text = _safe_str(r.get("statement_text")) or ""

    compute = r.get("compute") or {}
    if not isinstance(compute, dict):
        compute = {}
    qs = r.get("query_source") or {}
    if not isinstance(qs, dict):
        qs = {}
    job_info = qs.get("job_info") if isinstance(qs.get("job_info"), dict) else {}
    pipe_info = qs.get("pipeline_info") if isinstance(qs.get("pipeline_info"), dict) else {}

    qparams = r.get("query_parameters")
    qtags = r.get("query_tags")

    sql_feats = _extract_sql_features(text)
    params = _flatten_query_parameters(qparams)
    tags = _flatten_query_tags(qtags)

    # Derived metrics
    read_files = _safe_int(r.get("read_files"))
    pruned_files = _safe_int(r.get("pruned_files"))
    pruning_ratio = None
    if read_files is not None and pruned_files is not None and (read_files + pruned_files) > 0:
        pruning_ratio = round(pruned_files / (read_files + pruned_files), 4)

    read_rows = _safe_int(r.get("read_rows"))
    produced_rows = _safe_int(r.get("produced_rows"))
    selectivity_ratio = _ratio(produced_rows, read_rows)

    total_duration = _safe_int(r.get("total_duration_ms")) or 0
    waiting_for = _safe_int(r.get("waiting_for_compute_duration_ms")) or 0
    waiting_at = _safe_int(r.get("waiting_at_capacity_duration_ms")) or 0
    compilation = _safe_int(r.get("compilation_duration_ms")) or 0
    waiting_pct = round((waiting_for + waiting_at) / total_duration, 4) if total_duration > 0 else None
    compile_pct = round(compilation / total_duration, 4) if total_duration > 0 else None

    read_bytes = _safe_int(r.get("read_bytes"))
    is_full_scan = (read_bytes is not None and read_bytes > 100 * (1 << 30)  # 100 GB
                    and (produced_rows is not None and produced_rows < 1000))

    # Time
    start_time = r.get("start_time")
    if isinstance(start_time, pd.Timestamp):
        start_time = start_time.to_pydatetime()
    elif not isinstance(start_time, (datetime, type(None))):
        start_time = pd.to_datetime(start_time, errors="coerce")
        if pd.isna(start_time):
            start_time = None
        else:
            start_time = start_time.to_pydatetime()

    end_time = r.get("end_time")
    if isinstance(end_time, pd.Timestamp):
        end_time = end_time.to_pydatetime()
    update_time = r.get("update_time")
    if isinstance(update_time, pd.Timestamp):
        update_time = update_time.to_pydatetime()

    start_date_v: Optional[date] = None
    start_hour: Optional[int] = None
    start_dow: Optional[int] = None
    is_off_hours = None
    is_weekend = None
    if isinstance(start_time, datetime):
        start_date_v = start_time.date()
        start_hour = start_time.hour
        start_dow = start_time.weekday()
        is_off_hours = (start_hour < 7) or (start_hour >= 19)
        is_weekend = start_dow >= 5

    # Error
    execution_status = _safe_str(r.get("execution_status"))
    error_message = _safe_str(r.get("error_message"))
    err_cat, err_code, sqlstate = _categorize_error(error_message)
    error_rec = None
    if execution_status == "FAILED" or error_message:
        ref_obj, ref_user = _extract_error_object(error_message)
        error_rec = {
            "statement_id": statement_id,
            "error_category": err_cat,
            "error_code": err_code,
            "sqlstate": sqlstate,
            "error_message_excerpt": (error_message[:2000] if error_message else None),
            "referenced_object": ref_obj,
            "referenced_user": ref_user,
        }

    # Identity
    executed_by = _safe_str(r.get("executed_by"))
    executed_by_user_id = _safe_str(r.get("executed_by_user_id"))
    executed_as = _safe_str(r.get("executed_as"))
    executed_as_user_id = _safe_str(r.get("executed_as_user_id"))
    is_delegated = (executed_by != executed_as) if (executed_by and executed_as) else False
    principal_kind = _principal_kind(executed_by, executed_by_user_id)

    # Driver
    driver_family, driver_version = _parse_driver(_safe_str(r.get("client_driver")))

    # Project keywords
    keywords = _project_keywords(sql_feats["tables"], tags, params)
    catalogs_touched = sorted({t["catalog"] for t in sql_feats["tables"] if t.get("catalog")})
    schemas_touched = sorted({t["schema"] for t in sql_feats["tables"] if t.get("schema")})
    tables_touched = sorted({t["fully_qualified"] for t in sql_feats["tables"]})[:50]

    # Statement-text helpers
    text_sha1 = hashlib.sha1(text.encode("utf-8")).hexdigest() if text else None
    excerpt = text[:2000] if text else None

    statement = {
        "statement_id": statement_id,
        "account_id": _safe_str(r.get("account_id")),
        "workspace_id": _safe_str(r.get("workspace_id")),
        "executed_by": executed_by,
        "executed_by_user_id": executed_by_user_id,
        "executed_as": executed_as,
        "executed_as_user_id": executed_as_user_id,
        "session_id": _safe_str(r.get("session_id")),
        "is_delegated": is_delegated,
        "principal_kind": principal_kind,
        "compute_type": _safe_str(compute.get("type")),
        "warehouse_id": _safe_str(compute.get("warehouse_id")),
        "cluster_id": _safe_str(compute.get("cluster_id")),
        "statement_type": _safe_str(r.get("statement_type")),
        "execution_status": execution_status,
        "statement_text_excerpt": excerpt,
        "statement_text_length": len(text) if text else 0,
        "statement_text_sha1": text_sha1,
        "normalized_sql_hash": sql_feats["normalized_sql_hash"],
        "is_sql": sql_feats["is_sql"],
        "has_select_star": sql_feats["has_select_star"],
        "has_cross_join": sql_feats["has_cross_join"],
        "has_cte": sql_feats["has_cte"],
        "has_subquery": sql_feats["has_subquery"],
        "has_window": sql_feats["has_window"],
        "is_describe_or_show": sql_feats["is_describe_or_show"],
        "is_dml": sql_feats["is_dml"],
        "is_ddl": sql_feats["is_ddl"],
        "is_grant_revoke": sql_feats["is_grant_revoke"],
        "is_parameterized": bool(params),
        "client_application": _safe_str(r.get("client_application")),
        "client_driver": _safe_str(r.get("client_driver")),
        "client_driver_family": driver_family,
        "client_driver_version": driver_version,
        "source_category": _source_category(qs),
        "job_id": _safe_str(job_info.get("job_id")),
        "job_run_id": _safe_str(job_info.get("job_run_id")),
        "job_task_run_id": _safe_str(job_info.get("job_task_run_id")),
        "pipeline_id": _safe_str(pipe_info.get("pipeline_id")),
        "update_id": _safe_str(pipe_info.get("update_id")),
        "notebook_id": _safe_str(qs.get("notebook_id")),
        "dashboard_id": _safe_str(qs.get("dashboard_id")),
        "legacy_dashboard_id": _safe_str(qs.get("legacy_dashboard_id")),
        "alert_id": _safe_str(qs.get("alert_id")),
        "sql_query_id": _safe_str(qs.get("sql_query_id")),
        "genie_space_id": _safe_str(qs.get("genie_space_id")),
        "total_duration_ms": _safe_int(r.get("total_duration_ms")),
        "waiting_for_compute_duration_ms": _safe_int(r.get("waiting_for_compute_duration_ms")),
        "waiting_at_capacity_duration_ms": _safe_int(r.get("waiting_at_capacity_duration_ms")),
        "execution_duration_ms": _safe_int(r.get("execution_duration_ms")),
        "compilation_duration_ms": _safe_int(r.get("compilation_duration_ms")),
        "total_task_duration_ms": _safe_int(r.get("total_task_duration_ms")),
        "result_fetch_duration_ms": _safe_int(r.get("result_fetch_duration_ms")),
        "start_time": start_time if isinstance(start_time, datetime) else None,
        "end_time": end_time if isinstance(end_time, datetime) else None,
        "update_time": update_time if isinstance(update_time, datetime) else None,
        "start_date": start_date_v,
        "start_hour": start_hour,
        "start_day_of_week": start_dow,
        "is_off_hours": is_off_hours,
        "is_weekend": is_weekend,
        "read_partitions": _safe_int(r.get("read_partitions")),
        "pruned_files": pruned_files,
        "read_files": read_files,
        "read_rows": read_rows,
        "produced_rows": produced_rows,
        "read_bytes": read_bytes,
        "read_io_cache_percent": _safe_int(r.get("read_io_cache_percent")),
        "from_result_cache": _safe_bool(r.get("from_result_cache")),
        "spilled_local_bytes": _safe_int(r.get("spilled_local_bytes")),
        "written_bytes": _safe_int(r.get("written_bytes")),
        "shuffle_read_bytes": _safe_int(r.get("shuffle_read_bytes")),
        "written_rows": _safe_int(r.get("written_rows")),
        "written_files": _safe_int(r.get("written_files")),
        "pruned_files_bytes": _safe_int(r.get("pruned_files_bytes")),
        "read_files_bytes": _safe_int(r.get("read_files_bytes")),
        "pruning_ratio": pruning_ratio,
        "selectivity_ratio": selectivity_ratio,
        "waiting_pct": waiting_pct,
        "compile_pct": compile_pct,
        "is_full_scan": is_full_scan,
        "is_expensive": False,  # filled in after a percentile pass
        "is_cache_hit": _safe_bool(r.get("from_result_cache")),
        "cache_origin_statement_id": _safe_str(r.get("cache_origin_statement_id")),
        "error_category": err_cat,
        "error_code": err_code,
        "sqlstate": sqlstate,
        "project_keywords": keywords,
        "catalogs_touched": catalogs_touched,
        "schemas_touched": schemas_touched,
        "tables_touched": tables_touched,
    }

    # Per-row exploded children
    tables_out = [{"statement_id": statement_id, **t} for t in sql_feats["tables"]]
    cols_out = [{"statement_id": statement_id, **c} for c in sql_feats["columns"]]
    tags_out = [{"statement_id": statement_id, **t} for t in tags]
    params_out = [{"statement_id": statement_id, **p} for p in params]

    return {
        "statement": statement,
        "tables": tables_out,
        "columns": cols_out,
        "tags": tags_out,
        "params": params_out,
        "error": error_rec,
    }


# ---------------------------------------------------------------------------
# Bulk insertion helpers
# ---------------------------------------------------------------------------

async def _batched_insert(session: AsyncSession, table, records: list[dict]) -> int:
    """Insert in BATCH_SIZE-sized chunks."""
    n = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        if not batch:
            continue
        await session.execute(table.__table__.insert(), batch)
        n += len(batch)
    return n


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Spark persistence — when engine='spark', we write the qi_* tables as Delta
# tables under spark_catalog.default. The qi_extract_runs audit row stays in
# Postgres regardless of engine.
# ---------------------------------------------------------------------------

_SPARK_TABLES = [
    "qi_statements",
    "qi_statement_tables",
    "qi_statement_columns",
    "qi_statement_tags",
    "qi_statement_parameters",
    "qi_statement_errors",
]


def _persist_spark(
    statements: list[dict],
    tables: list[dict],
    columns: list[dict],
    tags: list[dict],
    params: list[dict],
    errors: list[dict],
) -> dict[str, int]:
    """Write the qi_* records as Delta tables. Synchronous (Spark Connect
    is gRPC-blocking — we run this off the asyncio thread)."""
    from spark_session import get_spark

    spark = get_spark()

    # Spark Connect serializes createDataFrame(pdf) as an Arrow IPC stream
    # that has to fit entirely in the driver JVM heap. At ~1 KB / qi_statements
    # row, 1.2 M rows = ~1.2 GB → OOMs the default 1 GB driver heap. Chunk in
    # batches of 50 k (~50 MB Arrow). First chunk creates the table
    # (mode=overwrite); subsequent chunks append.
    #
    # IMPORTANT: Spark infers schema from each pandas DataFrame independently.
    # A chunk where every row has a non-null `total_duration_ms` becomes LongType;
    # one where some rows have null becomes DoubleType (pandas' int-with-NaN ->
    # float64 promotion). Delta APPEND refuses to merge LongType + DoubleType,
    # so we PIN the schema from the first chunk and force subsequent chunks to
    # use it.
    CHUNK = 50_000

    def _coerce(pdf: pd.DataFrame) -> pd.DataFrame:
        for c in pdf.columns:
            if pdf[c].dtype == object:
                pdf[c] = pdf[c].astype(object).where(pdf[c].notna(), None)
        return pdf

    def _write(name: str, records: list[dict]) -> int:
        # Always drop first so each ETL run is a clean snapshot.
        spark.sql(f"DROP TABLE IF EXISTS spark_catalog.default.{name}")
        if not records:
            return 0

        # First chunk: let Spark infer the schema, then capture it.
        first = records[:CHUNK]
        pdf = _coerce(pd.DataFrame(first))
        first_sdf = spark.createDataFrame(pdf)
        pinned = first_sdf.schema
        first_sdf.write.format("delta").mode("overwrite").saveAsTable(
            f"spark_catalog.default.{name}"
        )
        total = len(first)
        logger.info("  spark write %s: %d / %d rows", name, total, len(records))

        # Subsequent chunks: convert pandas dtypes to match the pinned schema
        # (force int columns to nullable Int64 so they don't drift to float),
        # then create DataFrame with the explicit schema so Spark coerces.
        from pyspark.sql import types as T
        int_cols = {f.name for f in pinned.fields if isinstance(f.dataType, (T.LongType, T.IntegerType, T.ShortType, T.ByteType))}
        for i in range(CHUNK, len(records), CHUNK):
            chunk = records[i:i + CHUNK]
            pdf = _coerce(pd.DataFrame(chunk))
            # Pin int columns to pandas nullable Int64 to avoid float64 promotion
            for c in int_cols:
                if c in pdf.columns and pdf[c].dtype != "Int64":
                    pdf[c] = pdf[c].astype("Int64")
            try:
                sdf = spark.createDataFrame(pdf, schema=pinned)
            except Exception as e:  # noqa: BLE001
                # If strict schema rejects (e.g. a column genuinely has a wider
                # type in this chunk), fall back to inferred and let Delta's
                # mergeSchema sort it out.
                logger.warning("  spark write %s: chunk %d schema mismatch, falling back: %s", name, i, e)
                sdf = spark.createDataFrame(pdf)
            sdf.write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable(
                f"spark_catalog.default.{name}"
            )
            total += len(chunk)
            logger.info("  spark write %s: %d / %d rows", name, total, len(records))
        return total

    n_stmt = _write("qi_statements", statements)
    n_tbl = _write("qi_statement_tables", tables)
    n_col = _write("qi_statement_columns", columns)
    n_tag = _write("qi_statement_tags", tags)
    n_par = _write("qi_statement_parameters", params)
    err_seen: set[str] = set()
    dedup_errors = []
    for e in errors:
        sid = e["statement_id"]
        if sid and sid not in err_seen:
            err_seen.add(sid)
            dedup_errors.append(e)
    n_err = _write("qi_statement_errors", dedup_errors)

    return {
        "statements": n_stmt, "tables": n_tbl, "columns": n_col,
        "tags": n_tag, "params": n_par, "errors": n_err,
    }


async def extract_query_intel(
    session: AsyncSession,
    data_dir: str = "data",
    file_prefix: str = "demo_",
) -> dict[str, Any]:
    """Read the latest <prefix>query_history_*.parquet and rebuild qi_* tables."""
    started = datetime.utcnow()
    t0 = time.time()

    data_path = Path(data_dir)
    pattern = f"{file_prefix}query_history_*.parquet"
    candidates = sorted(data_path.glob(pattern), reverse=True)
    if not candidates and file_prefix == "demo_":
        # Fall back to real query_history if demo missing
        candidates = sorted(data_path.glob("query_history_*.parquet"), reverse=True)
        candidates = [c for c in candidates if not c.name.startswith("demo_")]
    if not candidates:
        raise FileNotFoundError(
            f"No parquet file found matching {pattern} in {data_dir}/"
        )

    source_file = candidates[0]
    logger.info("Query Intel: reading %s", source_file)

    # Derive the data_origin partition from the source parquet — demo_*.parquet
    # always produces demo rows; everything else is real. Stamped on every
    # qi_* row inserted below so the runner can filter by view-mode.
    data_origin = "demo" if source_file.name.startswith("demo_") else "real"
    logger.info("Query Intel: data_origin partition = %s", data_origin)

    # Audit row
    run = QiExtractRun(
        started_at=started,
        source_file=str(source_file.name),
        status="running",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    run_id = run.id

    try:
        df = pd.read_parquet(source_file)
        rows = df.to_dict("records")
        logger.info("Query Intel: loaded %d rows, transforming ...", len(rows))

        statements: list[dict] = []
        tables: list[dict] = []
        columns: list[dict] = []
        tags: list[dict] = []
        params: list[dict] = []
        errors: list[dict] = []
        parse_failures = 0

        for i, row in enumerate(rows):
            try:
                out = _transform_row(row)
            except Exception:  # noqa: BLE001
                parse_failures += 1
                continue
            statements.append(out["statement"])
            tables.extend(out["tables"])
            columns.extend(out["columns"])
            tags.extend(out["tags"])
            params.extend(out["params"])
            if out["error"]:
                errors.append(out["error"])
            if (i + 1) % 10_000 == 0:
                logger.info("  ... %d/%d rows transformed", i + 1, len(rows))

        # Stamp data_origin on every output row so the partition stays
        # consistent across the parent + child tables. The runner relies
        # on this column to scope reads by view-mode.
        for s in statements: s["data_origin"] = data_origin
        for r in tables:     r["data_origin"] = data_origin
        for r in columns:    r["data_origin"] = data_origin
        for r in tags:       r["data_origin"] = data_origin
        for r in params:     r["data_origin"] = data_origin
        for r in errors:     r["data_origin"] = data_origin

        # Post-pass: top-1% by total_duration_ms → mark is_expensive.
        durations = [s["total_duration_ms"] or 0 for s in statements]
        if durations:
            threshold = sorted(durations)[max(0, int(len(durations) * 0.99) - 1)]
            for s in statements:
                if (s["total_duration_ms"] or 0) >= threshold and threshold > 0:
                    s["is_expensive"] = True

        logger.info(
            "Query Intel: transformed %d statements, %d tables, %d columns, "
            "%d tags, %d params, %d errors, %d parse failures",
            len(statements), len(tables), len(columns), len(tags), len(params),
            len(errors), parse_failures,
        )

        # Dispatch persistence based on the (engine, spark_mode) combo:
        #
        #   duckdb                          → Postgres
        #   spark + jdbc_views (default)    → Postgres (read by Spark via JDBC temp views)
        #   spark + materialized            → Delta tables in spark_catalog.default
        #
        # "Spark over Postgres" deliberately keeps qi_* in Postgres so Spark
        # SQL Editor surfaces them as TEMP views and the Spark engine reads
        # the same physical rows as DuckDB engine would. Materialized mode
        # copies the data into the warehouse for faster, no-round-trip reads.
        from engine_config import get_engine, get_spark_mode

        engine = await get_engine(session)
        spark_mode = await get_spark_mode(session) if engine == "spark" else "jdbc_views"
        persist_to_delta = (engine == "spark" and spark_mode == "materialized")
        logger.info(
            "Query Intel: persisting via engine=%s spark_mode=%s → %s",
            engine, spark_mode, "Delta" if persist_to_delta else "Postgres",
        )

        if persist_to_delta:
            # Heavy: gRPC + JVM. Run off the asyncio thread so we don't
            # block the event loop while Spark does its work.
            import asyncio
            counts = await asyncio.to_thread(
                _persist_spark, statements, tables, columns, tags, params, errors,
            )
            st_n, tb_n, cl_n, tg_n, pr_n, er_n = (
                counts["statements"], counts["tables"], counts["columns"],
                counts["tags"], counts["params"], counts["errors"],
            )
        else:
            # Postgres path (default). Scoped delete — only wipe rows whose
            # data_origin matches this ETL run's partition so real + demo
            # qi_* can coexist (run the demo ETL, then the real ETL, and
            # the demo rows survive the second run).
            for table in (QiStatementError, QiStatementParameter, QiStatementTag,
                          QiStatementColumn, QiStatementTable, QiStatement):
                await session.execute(
                    sa.delete(table).where(table.data_origin == data_origin)
                )
            await session.commit()

            st_n = await _batched_insert(session, QiStatement, statements)
            tb_n = await _batched_insert(session, QiStatementTable, tables)
            cl_n = await _batched_insert(session, QiStatementColumn, columns)
            tg_n = await _batched_insert(session, QiStatementTag, tags)
            pr_n = await _batched_insert(session, QiStatementParameter, params)
            err_seen: set[str] = set()
            dedup_errors = []
            for e in errors:
                sid = e["statement_id"]
                if sid and sid not in err_seen:
                    err_seen.add(sid)
                    dedup_errors.append(e)
            er_n = await _batched_insert(session, QiStatementError, dedup_errors)

            await session.commit()

        ended = datetime.utcnow()
        elapsed = round(time.time() - t0, 2)
        await session.execute(
            sa.update(QiExtractRun).where(QiExtractRun.id == run_id).values(
                ended_at=ended,
                rows_processed=len(rows),
                statements_inserted=st_n,
                tables_extracted=tb_n,
                columns_extracted=cl_n,
                tags_extracted=tg_n,
                params_extracted=pr_n,
                errors_extracted=er_n,
                parse_failures=parse_failures,
                duration_seconds=elapsed,
                status="success",
            )
        )
        await session.commit()

        return {
            "source_file": str(source_file.name),
            "rows_processed": len(rows),
            "statements_inserted": st_n,
            "tables_extracted": tb_n,
            "columns_extracted": cl_n,
            "tags_extracted": tg_n,
            "params_extracted": pr_n,
            "errors_extracted": er_n,
            "parse_failures": parse_failures,
            "duration_seconds": elapsed,
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("Query Intel extraction failed")
        await session.execute(
            sa.update(QiExtractRun).where(QiExtractRun.id == run_id).values(
                ended_at=datetime.utcnow(),
                status="failed",
                error_message=str(e),
            )
        )
        await session.commit()
        raise
