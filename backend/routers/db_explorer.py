"""
Admin-only Postgres explorer.

Exposes the database catalog (tables / views and their columns) and a
read-only ad-hoc SQL runner. Every endpoint requires the 'admin' role.

Safety model for the query runner:
  * single statement only (no `;`-chained statements)
  * must start with SELECT or WITH
  * forbidden DML/DDL keywords are rejected before execution
  * executed inside a READ ONLY transaction with a statement timeout, so even
    if something slips past the textual check the DB itself refuses writes
"""

from __future__ import annotations

import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import require_admin
from database import get_db

router = APIRouter(
    prefix="/api/admin/db",
    tags=["admin", "db-explorer"],
    dependencies=[Depends(require_admin)],
)

MAX_ROWS = 1000
STATEMENT_TIMEOUT_MS = 15_000


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------

class ColumnInfo(BaseModel):
    name: str
    type: str
    nullable: bool


class DbObject(BaseModel):
    schema_name: str
    name: str
    kind: str  # 'table' | 'view'
    approx_rows: int
    columns: list[ColumnInfo]


class QueryRequest(BaseModel):
    sql: str = Field(..., min_length=1, max_length=20_000)
    max_rows: int = Field(MAX_ROWS, ge=1, le=MAX_ROWS)


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    elapsed_ms: int


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"comment|reindex|vacuum|analyze|cluster|copy|call|do|set|reset|"
    r"prepare|deallocate|listen|notify|lock|begin|commit|rollback|savepoint)\b",
    re.IGNORECASE,
)


def _is_safe_select(sql: str) -> tuple[bool, str]:
    """Returns (ok, reason). Mirrors the chatbot guard but Postgres-flavoured."""
    cleaned = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL).strip()
    if not cleaned:
        return False, "Empty query"
    if ";" in cleaned.rstrip(";"):
        return False, "Multiple statements are not allowed"
    if not re.match(r"^\s*(select|with)\b", cleaned, re.IGNORECASE):
        return False, "Only SELECT / WITH queries are allowed"
    m = _FORBIDDEN.search(cleaned)
    if m:
        return False, f"Keyword '{m.group(1).upper()}' is not allowed in the read-only explorer"
    return True, ""


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

@router.get("/objects", response_model=list[DbObject])
async def list_objects(db: AsyncSession = Depends(get_db)):
    """Tables and views in user schemas, with columns and a row estimate."""
    obj_rows = (await db.execute(text("""
        SELECT n.nspname               AS schema_name,
               c.relname               AS name,
               CASE c.relkind WHEN 'r' THEN 'table'
                              WHEN 'p' THEN 'table'
                              WHEN 'v' THEN 'view'
                              WHEN 'm' THEN 'view'
                         END           AS kind,
               GREATEST(c.reltuples, 0)::bigint AS approx_rows
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p', 'v', 'm')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname NOT LIKE 'pg_%%'
        ORDER BY n.nspname, c.relname
    """))).all()

    col_rows = (await db.execute(text("""
        SELECT table_schema, table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name, ordinal_position
    """))).all()

    cols_by_obj: dict[tuple[str, str], list[ColumnInfo]] = {}
    for sch, tbl, cname, dtype, nullable in col_rows:
        cols_by_obj.setdefault((sch, tbl), []).append(
            ColumnInfo(name=cname, type=dtype, nullable=(nullable == "YES"))
        )

    return [
        DbObject(
            schema_name=sch,
            name=name,
            kind=kind,
            approx_rows=int(approx),
            columns=cols_by_obj.get((sch, name), []),
        )
        for sch, name, kind, approx in obj_rows
    ]


# ---------------------------------------------------------------------------
# Ad-hoc query
# ---------------------------------------------------------------------------

@router.post("/query", response_model=QueryResponse)
async def run_query(req: QueryRequest, db: AsyncSession = Depends(get_db)):
    sql = req.sql.strip().rstrip(";").strip()
    ok, reason = _is_safe_select(sql)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    # Read-only, time-boxed. SET LOCAL is scoped to this transaction.
    started = time.perf_counter()
    try:
        # SET TRANSACTION must precede the first real query in the tx.
        await db.execute(text("SET TRANSACTION READ ONLY"))
        await db.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
        result = await db.execute(text(sql))
        all_rows = result.mappings().all()
    except Exception as e:  # noqa: BLE001 — surface the DB message to the admin
        await db.rollback()
        msg = str(getattr(e, "orig", e)).splitlines()[0][:500]
        raise HTTPException(status_code=400, detail=f"Query failed: {msg}")
    finally:
        # Never let the explorer leave a write transaction open.
        await db.rollback()

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    truncated = len(all_rows) > req.max_rows
    rows = all_rows[: req.max_rows]
    columns = list(rows[0].keys()) if rows else list(result.keys())

    def _clean(v: Any) -> Any:
        # JSON-safe: dates/decimals/uuids -> str; bytes -> repr
        import datetime
        import decimal
        import uuid

        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
            return v.isoformat()
        if isinstance(v, (decimal.Decimal, uuid.UUID)):
            return str(v)
        if isinstance(v, (bytes, bytearray, memoryview)):
            return f"<{len(bytes(v))} bytes>"
        return str(v)

    return QueryResponse(
        columns=columns,
        rows=[{k: _clean(v) for k, v in r.items()} for r in rows],
        row_count=len(rows),
        truncated=truncated,
        elapsed_ms=elapsed_ms,
    )
