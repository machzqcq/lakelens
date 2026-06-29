"""Engine-agnostic SQL runner for Query Intel.

`run_qi(db, sql, params)` returns ``list[dict]`` regardless of whether the
qi_* tables live in Postgres or in Spark's Delta warehouse.

The SQL is authored in a **portable subset** that works on both engines
(PERCENTILE_CONT WITHIN GROUP, DATE_TRUNC, standard CASE WHEN). A small
post-processor rewrites the handful of Postgres-only idioms (`::date`,
`::decimal`, `FILTER (WHERE …)`) into Spark-compatible forms when needed.

Caller convention:
    sql = "SELECT ... FROM qi_statements WHERE ... LIMIT :lim"
    rows = await run_qi(db, sql, {"lim": 20})

`:name` placeholders are SQLAlchemy-style; we convert to positional `?` for
Spark Connect.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import re
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from engine_config import get_engine

logger = logging.getLogger(__name__)

# Context variable carrying the active caller's view-mode for the lifetime
# of a request. Set by the router-level `_scope_qi` dependency on
# /api/query-intel/*. run_qi consults it as a fallback when the explicit
# `view_mode=` kwarg isn't passed — so endpoints don't have to thread the
# kwarg through every call site to inherit the filter.
_view_mode_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "qi_view_mode", default=None,
)


def set_view_mode_for_request(view_mode: Optional[str]) -> None:
    """Stash the active view-mode in the request-scoped contextvar. Called
    once per request by the router-level dependency."""
    _view_mode_ctx.set(_safe_view_mode(view_mode))


_PG_DATE_CAST_RE = re.compile(r"::date\b", re.IGNORECASE)
_PG_DECIMAL_CAST_RE = re.compile(r"::decimal\b", re.IGNORECASE)
_PG_NUMERIC_CAST_RE = re.compile(r"::numeric\b", re.IGNORECASE)
_PG_FILTER_RE = re.compile(
    r"(\b\w+\s*\(\s*(?:DISTINCT\s+)?[^()]*?\))\s*FILTER\s*\(WHERE\s+([^)]+)\)",
    re.IGNORECASE,
)


def _to_spark_sql(sql: str) -> str:
    """Translate Postgres-isms in `sql` to Spark-compatible SQL."""
    # `x::date` → `CAST(x AS DATE)` is non-trivial in regex (need the
    # expression before ::date), but all our usages are
    # `date_trunc('month', col)::date` — surrounding parens make a clean swap.
    # Conservative approach: replace `<expr>::TYPE` patterns we know we use.
    # The expression *we generate* always ends in `)` (a function call) before
    # ::date, so we can use a balanced-paren match.
    def cast_replace(s: str, regex: re.Pattern, target_type: str) -> str:
        out = []
        idx = 0
        for m in regex.finditer(s):
            # walk backwards from m.start() to find the matching open-paren for the
            # closing one immediately before the ::cast.
            end = m.start()
            # If the char before is ')', walk back through balanced parens to find
            # the start of that expression. Otherwise grab the prior identifier.
            j = end - 1
            while j >= 0 and s[j].isspace():
                j -= 1
            if j < 0:
                out.append(s[idx:m.end()])
                idx = m.end()
                continue
            if s[j] == ")":
                depth = 1
                k = j - 1
                while k >= 0 and depth > 0:
                    if s[k] == ")":
                        depth += 1
                    elif s[k] == "(":
                        depth -= 1
                    k -= 1
                # Need to extend left over the function name characters.
                func_start = k + 1
                while func_start > 0 and (s[func_start - 1].isalnum() or s[func_start - 1] in "_."):
                    func_start -= 1
                expr_start = func_start
            else:
                k = j
                while k >= 0 and (s[k].isalnum() or s[k] in "_."):
                    k -= 1
                expr_start = k + 1
            expr = s[expr_start:end]
            out.append(s[idx:expr_start])
            out.append(f"CAST({expr} AS {target_type})")
            idx = m.end()
        out.append(s[idx:])
        return "".join(out)

    sql = cast_replace(sql, _PG_DATE_CAST_RE, "DATE")
    sql = cast_replace(sql, _PG_DECIMAL_CAST_RE, "DECIMAL(20,6)")
    sql = cast_replace(sql, _PG_NUMERIC_CAST_RE, "DECIMAL(20,6)")

    # FILTER (WHERE cond) → CASE-WHEN wrapped aggregate.
    # Only handles single-argument aggregates of the form
    # `COUNT(DISTINCT col) FILTER (WHERE cond)` -> `COUNT(DISTINCT
    # CASE WHEN cond THEN col ELSE NULL END)`. Good enough for our queries.
    def filter_replace(match: re.Match) -> str:
        agg_call = match.group(1).strip()  # "COUNT(DISTINCT col)" or "SUM(col)"
        cond = match.group(2).strip()
        # Split into function name and inner expression
        paren_open = agg_call.index("(")
        func_name = agg_call[:paren_open]
        inner = agg_call[paren_open + 1: agg_call.rindex(")")].strip()
        # Detect DISTINCT prefix
        distinct_prefix = ""
        if inner.upper().startswith("DISTINCT "):
            distinct_prefix = "DISTINCT "
            inner = inner[len("DISTINCT "):].strip()
        return f"{func_name}({distinct_prefix}CASE WHEN {cond} THEN {inner} ELSE NULL END)"

    sql = _PG_FILTER_RE.sub(filter_replace, sql)
    return sql


def _to_spark_params(sql: str, params: Optional[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Inline-substitute `:name` placeholders into the SQL.

    Spark Connect's parameterized API is finicky when the same name appears
    multiple times. Since our placeholders are admin-controlled (no user
    input reaches them), inline substitution is safe enough.
    """
    if not params:
        return sql, {}

    def render(v: Any) -> str:
        if v is None:
            return "NULL"
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, date):
            return f"DATE '{v.isoformat()}'"
        # String — escape single quotes
        s = str(v).replace("'", "''")
        return f"'{s}'"

    pattern = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")
    out = pattern.sub(lambda m: render(params.get(m.group(1))), sql)
    return out, {}


# ---------------------------------------------------------------------------
# View-mode injection
# ---------------------------------------------------------------------------
#
# Every Query Intel endpoint should pass `view_mode=user.viewing_data_mode`
# into run_qi. The runner then transparently wraps every FROM/JOIN reference
# to a qi_* table in a `(SELECT * FROM <t> WHERE data_origin='<mode>') AS <t>`
# subquery, so the endpoint's SQL stays view-mode-agnostic and the read
# never crosses the real/demo partition.
#
# When `view_mode` is None we fall back to the legacy behaviour — no filter
# applied. New endpoints should always pass it.

_VIEW_MODE_TABLES = (
    "qi_statements",
    "qi_statement_tables",
    "qi_statement_columns",
    "qi_statement_tags",
    "qi_statement_parameters",
    "qi_statement_errors",
)
_VALID_VIEW_MODES = ("real", "demo")


def _safe_view_mode(view_mode: Optional[str]) -> Optional[str]:
    """Clamp view_mode to the safelisted enum so it can be safely
    interpolated into SQL. Returns None when caller didn't supply one
    (no filter applied — legacy path)."""
    if view_mode is None:
        return None
    m = (view_mode or "").strip().lower()
    return m if m in _VALID_VIEW_MODES else "real"


# SQL keywords that can legally follow a FROM/JOIN table reference and
# therefore must NOT be mis-read as a table alias when we capture the
# optional alias after the table name. Anything in this set is "no alias,
# next clause" rather than "alias = <keyword>".
_NOT_AN_ALIAS = frozenset({
    "WHERE", "ON", "USING", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS",
    "GROUP", "ORDER", "LIMIT", "HAVING", "UNION", "INTERSECT", "EXCEPT",
    "WINDOW", "QUALIFY", "FETCH", "OFFSET", "FOR", "LATERAL", "WITH",
})


def _inject_view_mode(sql: str, view_mode: str) -> str:
    """Replace every `FROM <qi_table>` / `JOIN <qi_table>` reference with a
    filtering subquery. Pattern is word-boundary anchored so it won't touch
    string literals or qualified names like `spark_catalog.default.qi_statements`
    (which the chatbot Spark-mode prompt uses — those carry the filter via
    the Delta-shadow temp view registrar instead).

    Handles optional table aliases:
      * `FROM qi_statements`           → `FROM (subq) AS qi_statements`
      * `FROM qi_statements s`         → `FROM (subq) AS s`
      * `FROM qi_statements AS s`      → `FROM (subq) AS s`
      * `FROM qi_statements WHERE ...` → `FROM (subq) AS qi_statements WHERE ...`
        (the trailing WHERE is detected as a clause keyword, not an alias)

    Preserving the caller's alias matters because downstream column
    qualifiers like `s.executed_by` reference it; if we always aliased the
    subquery as the table name we'd produce `FROM (subq) AS qi_statements s`
    which is invalid SQL (double alias) — that's the bug this function
    was fixing.
    """
    for table in _VIEW_MODE_TABLES:
        # Two capturing groups: (1) the FROM/JOIN keyword, (2) the optional
        # alias identifier. The `(?:AS\s+)?` lets us match both `t alias`
        # and `t AS alias` shapes. We then post-filter the captured alias
        # in the replacement function so a SQL clause keyword adjacent to
        # the table name (e.g. `WHERE`) doesn't get consumed as an alias.
        pattern = re.compile(
            rf"(\bFROM|\bJOIN)\s+{table}\b(?!\s*\()"
            rf"(?:\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*)\b)?",
            re.IGNORECASE,
        )

        def repl(m: re.Match) -> str:
            kw = m.group(1)
            alias_candidate = m.group(2)
            subq = f"(SELECT * FROM {table} WHERE data_origin = '{view_mode}')"
            if alias_candidate and alias_candidate.upper() not in _NOT_AN_ALIAS:
                # Use the caller's alias verbatim.
                return f"{kw} {subq} AS {alias_candidate}"
            # No alias OR what we captured was actually a clause keyword.
            # In the latter case the captured group is still consumed by the
            # regex match, so we must re-emit it after the subquery alias to
            # preserve the original SQL.
            trailing = f" {alias_candidate}" if alias_candidate else ""
            return f"{kw} {subq} AS {table}{trailing}"

        sql = pattern.sub(repl, sql)
    return sql


async def run_qi(
    db: AsyncSession,
    sql: str,
    params: Optional[dict[str, Any]] = None,
    view_mode: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Run `sql` on the active engine and return rows as dicts.

    `view_mode` ('real' / 'demo'), when supplied, scopes every qi_* table
    reference in the SQL to that data_origin partition — see
    `_inject_view_mode` for the mechanics. When the kwarg is omitted we
    fall back to the request-scoped contextvar set by the router-level
    dependency, so endpoints in /api/query-intel/* inherit the filter
    transparently.
    """
    if view_mode is not None:
        safe_mode = _safe_view_mode(view_mode)
    else:
        safe_mode = _view_mode_ctx.get()
    if safe_mode is not None:
        sql = _inject_view_mode(sql, safe_mode)

    engine = await get_engine(db)
    if engine == "spark":
        spark_sql = _to_spark_sql(sql)
        spark_sql, _ = _to_spark_params(spark_sql, params)
        rows = await asyncio.to_thread(_run_spark, spark_sql)
        return rows
    # Default: Postgres
    result = await db.execute(text(sql), params or {})
    return [dict(r) for r in result.mappings().all()]


def _run_spark(sql: str) -> list[dict[str, Any]]:
    """Execute `sql` against Spark Connect. Synchronous. Called via
    asyncio.to_thread so the asyncio loop isn't blocked by gRPC."""
    from spark_session import get_spark

    spark = get_spark()
    df = spark.sql(sql)
    pdf = df.toPandas()
    if pdf.empty:
        return []
    # Coerce pandas types into JSON-friendly Python (Timestamp → ISO, NaN → None).
    import pandas as pd
    records = pdf.to_dict("records")
    out: list[dict[str, Any]] = []
    for r in records:
        cleaned = {}
        for k, v in r.items():
            if v is None or (isinstance(v, float) and pd.isna(v)):
                cleaned[k] = None
            elif isinstance(v, pd.Timestamp):
                cleaned[k] = v.isoformat()
            else:
                cleaned[k] = v
        out.append(cleaned)
    return out
