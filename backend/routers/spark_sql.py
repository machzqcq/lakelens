"""Admin-only Spark SQL editor — ad-hoc queries against the spark-warehouse.

Mirrors the Postgres Database Explorer but routes through Spark Connect so
admins can interrogate the Delta tables produced by the Query Profiler ETL
(qi_statements, qi_statement_tables, …) plus anything else that lives in
`spark_catalog.default`.

Safety:
  * single statement only (no `;`-chained statements)
  * must start with SELECT / WITH / SHOW / DESCRIBE
  * forbidden DDL/DML verbs are rejected before execution
  * cap rows server-side via `df.limit(max_rows)`
  * runs through asyncio.to_thread so a slow Spark query doesn't block the
    asyncio event loop
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import AuthedUser, get_current_user, require_admin
from database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/spark-sql", tags=["spark-sql"])

MAX_ROWS = 1000


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------

class SparkColumnInfo(BaseModel):
    name: str
    type: str
    nullable: bool


class SparkTable(BaseModel):
    catalog: str
    database: str
    name: str
    kind: str  # MANAGED | EXTERNAL | VIEW | TEMPORARY
    columns: list[SparkColumnInfo]


class SparkQueryRequest(BaseModel):
    sql: str = Field(..., min_length=1, max_length=20_000)
    max_rows: int = Field(MAX_ROWS, ge=1, le=MAX_ROWS)


class SparkQueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    elapsed_ms: int


class SparkSessionInfo(BaseModel):
    reachable: bool
    remote: str
    spark_version: str | None = None
    warehouse_dir: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"replace|merge|copy|optimize|vacuum|cache|uncache|clear|reset|set|"
    r"refresh|analyze|msck|attach|detach|use)\b",
    re.IGNORECASE,
)
_ALLOWED_STARTS = re.compile(r"^\s*(select|with|show|describe|desc|explain)\b", re.IGNORECASE)


def _is_safe(sql: str) -> tuple[bool, str]:
    cleaned = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL).strip()
    if not cleaned:
        return False, "Empty query"
    if ";" in cleaned.rstrip(";"):
        return False, "Multiple statements are not allowed (one query per Run)."
    if not _ALLOWED_STARTS.match(cleaned):
        return False, "Only SELECT / WITH / SHOW / DESCRIBE / EXPLAIN are allowed."
    m = _FORBIDDEN.search(cleaned)
    if m:
        return False, f"Keyword '{m.group(1).upper()}' is not allowed in the read-only Spark SQL editor."
    return True, ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/session", response_model=SparkSessionInfo)
async def session_info(_: object = Depends(require_admin)):
    """Probe Spark Connect for liveness + version. Used by the UI on page load
    so the editor can show a clear 'Spark unreachable' state instead of
    failing on the first Run."""
    try:
        from spark_session import _build_remote, get_spark
        remote = _build_remote()
        spark = await asyncio.to_thread(get_spark)
        version = await asyncio.to_thread(lambda: spark.version)
        warehouse = await asyncio.to_thread(
            lambda: spark.conf.get("spark.sql.warehouse.dir", None)
        )
        return SparkSessionInfo(
            reachable=True, remote=remote, spark_version=version, warehouse_dir=warehouse,
        )
    except Exception as e:  # noqa: BLE001
        from spark_session import _build_remote
        return SparkSessionInfo(reachable=False, remote=_build_remote(), error=str(e)[:500])


@router.get("/tables", response_model=list[SparkTable])
async def list_tables(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List tables in `spark_catalog.default` with their column schema.

    Behaviour by spark_mode:
      * `jdbc_views`     — base + qi temp views are JDBC-backed and
        filtered by the caller's view_mode. The raw catalog (Delta)
        copies of those names — if a prior materialize ran — are hidden
        so the active set is unambiguous.
      * `materialized`   — base + qi temp views are SQL views over the
        catalog Delta tables, also filtered by the caller's view_mode.
        The raw 3-part `spark_catalog.default.<name>` tables stay
        reachable for admins who need the unfiltered view.

    We refresh the temp-view set with the caller's current view_mode
    BEFORE listing so the column metadata reflects what they'll see at
    query time.
    """
    from spark_session import get_spark, apply_view_mode, _BASE_TABLES, _QI_TABLES
    # We swapped require_admin for get_current_user because we need both
    # the admin check AND the calling user's view_mode. Enforce admin
    # here so the contract on this endpoint doesn't widen.
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    shadowed_in_jdbc_mode = set(_BASE_TABLES) | set(_QI_TABLES)

    # Always re-register the user-facing temp views with the caller's
    # view_mode so the column listing matches what queries will see.
    await asyncio.to_thread(apply_view_mode, user.viewing_data_mode)
    spark = await asyncio.to_thread(get_spark)

    def _enumerate() -> list[SparkTable]:
        tables = spark.catalog.listTables("default")
        out: list[SparkTable] = []
        for t in tables:
            is_temp = bool(getattr(t, "isTemporary", False))
            # Hide the raw Delta copies of names that ALSO have a temp
            # view (the temp view is the view-mode-filtered surface).
            # This applies in BOTH modes now — the editor presents one
            # row per logical table, always filtered.
            if (
                not is_temp
                and t.name in shadowed_in_jdbc_mode
            ):
                continue

            # spark.catalog.listColumns() raises TABLE_OR_VIEW_NOT_FOUND for
            # temp views (our JDBC-backed base tables) and pollutes the
            # spark-connect logs with a full stacktrace even though we catch
            # it. For known temp views skip straight to spark.table().schema.
            col_infos: list[SparkColumnInfo] = []
            if not is_temp:
                try:
                    col_infos = [
                        SparkColumnInfo(name=c.name, type=c.dataType, nullable=c.nullable)
                        for c in spark.catalog.listColumns(t.name, "default")
                    ]
                except Exception:  # noqa: BLE001
                    col_infos = []
            if not col_infos:
                try:
                    schema = spark.table(t.name).schema
                    col_infos = [
                        SparkColumnInfo(
                            name=f.name,
                            type=f.dataType.simpleString(),
                            nullable=f.nullable,
                        )
                        for f in schema.fields
                    ]
                except Exception:  # noqa: BLE001
                    col_infos = []
            out.append(SparkTable(
                catalog="spark_catalog",
                database="default",
                name=t.name,
                kind=getattr(t, "tableType", "TABLE"),
                columns=col_infos,
            ))
        out.sort(key=lambda x: (x.kind != "MANAGED", x.name))
        return out

    return await asyncio.to_thread(_enumerate)


@router.post("/query", response_model=SparkQueryResponse)
async def run_query(
    req: SparkQueryRequest,
    user: AuthedUser = Depends(get_current_user),
):
    """Execute one read-only Spark SQL statement and stream back at most
    `max_rows` rows.

    Refreshes the user-facing temp views with the caller's `view_mode`
    BEFORE executing, so toggling real ↔ demo in the top-right cluster
    immediately changes what `SELECT * FROM billing_usage` returns
    without the user having to add a `WHERE` clause.
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    sql = req.sql.strip().rstrip(";").strip()
    ok, reason = _is_safe(sql)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    from spark_session import apply_view_mode, get_spark
    # Refresh first so the upcoming spark.sql() sees the right partition.
    await asyncio.to_thread(apply_view_mode, user.viewing_data_mode)
    spark = await asyncio.to_thread(get_spark)

    started = time.perf_counter()
    try:
        # asyncio.to_thread because Spark Connect's RPC is blocking.
        def _execute() -> tuple[list[str], list[dict[str, Any]], bool]:
            df = spark.sql(sql)
            limited = df.limit(req.max_rows + 1)  # +1 so we can detect truncation
            pdf = limited.toPandas()
            truncated = len(pdf) > req.max_rows
            if truncated:
                pdf = pdf.head(req.max_rows)
            cols = list(pdf.columns)
            records = _coerce_records(pdf)
            return cols, records, truncated

        columns, rows, truncated = await asyncio.to_thread(_execute)
    except Exception as e:  # noqa: BLE001 — surface a friendly first line
        first_line = _first_meaningful_line(str(e))
        raise HTTPException(status_code=400, detail=f"Query failed: {first_line}")

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return SparkQueryResponse(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        elapsed_ms=elapsed_ms,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_records(pdf) -> list[dict[str, Any]]:
    """pandas → JSON-safe dicts (datetimes → ISO, decimals → str, …)."""
    import datetime
    import decimal
    import pandas as pd

    def _clean(v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, float):
            return None if pd.isna(v) else v
        if isinstance(v, (str, int, bool)):
            return v
        if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
            return v.isoformat()
        if isinstance(v, decimal.Decimal):
            return str(v)
        if isinstance(v, (list, tuple)):
            return [_clean(x) for x in v]
        if isinstance(v, dict):
            return {k: _clean(val) for k, val in v.items()}
        if isinstance(v, pd.Timestamp):
            return v.isoformat()
        return str(v)

    out: list[dict[str, Any]] = []
    for record in pdf.to_dict(orient="records"):
        out.append({k: _clean(v) for k, v in record.items()})
    return out


def _first_meaningful_line(msg: str) -> str:
    for line in msg.splitlines():
        s = line.strip()
        if s and not s.startswith("at ") and not s.startswith("Caused by:"):
            return s[:500]
    return msg.splitlines()[0][:500] if msg else "<no error message>"
