"""Query Intel analytics endpoints — engine-agnostic.

Every endpoint funnels through `qi_runner.run_qi(db, sql, params)` so it
works against Postgres OR Spark Delta tables depending on the active engine
(toggled via Data Management).

All SQL is authored in a portable subset that works on both engines:
PERCENTILE_CONT WITHIN GROUP, DATE_TRUNC, standard CASE WHEN. The runner
rewrites the few Postgres-only forms (``::date``, ``::decimal``,
``FILTER (WHERE …)``) for the Spark path.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import AuthedUser, get_current_user
from database import get_db
from engine_config import get_engine
from qi_runner import run_qi, set_view_mode_for_request

logger = logging.getLogger(__name__)


def _scope_qi(user: AuthedUser = Depends(get_current_user)) -> AuthedUser:
    """Router-level dependency. Stashes the caller's view-mode in the
    qi_runner contextvar so every run_qi() call inside this router
    automatically filters by data_origin = user.viewing_data_mode. Every
    Query Intel endpoint inherits the filter without changing its
    signature — the kwarg-based opt-in still works for callers that
    want to override (e.g. a future cross-mode comparison view)."""
    set_view_mode_for_request(user.viewing_data_mode)
    return user


router = APIRouter(
    prefix="/api/query-intel",
    tags=["query-intel"],
    dependencies=[Depends(_scope_qi)],
)


# ---------------------------------------------------------------------------
# Filter helper — apply (start_date, end_date, workspace_id) to a query
# ---------------------------------------------------------------------------

def _date_filter_sql(
    start_date: Optional[date],
    end_date: Optional[date],
    workspace_id: Optional[str],
    source_category: Optional[str] = None,
    alias: str = "",
) -> tuple[str, dict[str, Any]]:
    """Return (' AND ...' clauses, params dict) for the requested filters."""
    prefix = f"{alias}." if alias else ""
    where: list[str] = []
    params: dict[str, Any] = {}
    if start_date is not None:
        where.append(f"{prefix}start_date >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        where.append(f"{prefix}start_date <= :end_date")
        params["end_date"] = end_date
    if workspace_id:
        where.append(f"{prefix}workspace_id = :workspace_id")
        params["workspace_id"] = workspace_id
    if source_category:
        where.append(f"{prefix}source_category = :source_category")
        params["source_category"] = source_category
    return (" AND " + " AND ".join(where) if where else "", params)


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

class OverviewKPI(BaseModel):
    total_statements: int
    distinct_users: int
    distinct_workspaces: int
    success_rate: float
    failed_count: int
    canceled_count: int
    median_duration_ms: Optional[float]
    p95_duration_ms: Optional[float]
    cache_hit_rate: float
    serverless_share: float
    genie_query_count: int
    dashboard_query_count: int
    job_query_count: int
    notebook_query_count: int
    has_data: bool
    last_extract_at: Optional[datetime] = None
    last_extract_source: Optional[str] = None
    date_min: Optional[date] = None
    date_max: Optional[date] = None
    engine: str = "duckdb"


@router.get("/overview", response_model=OverviewKPI)
async def overview(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    workspace_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    engine = await get_engine(db)
    # Cheap: does qi_statements have any rows?
    try:
        n_rows = await run_qi(db, "SELECT COUNT(*) AS n FROM qi_statements")
    except Exception as e:  # noqa: BLE001
        # If Spark engine selected but Spark isn't reachable, surface a 503.
        if engine == "spark":
            raise HTTPException(
                status_code=503,
                detail=f"Spark Connect is unavailable: {e}. Switch back to DuckDB or start the Spark services.",
            )
        raise
    total = int((n_rows[0]["n"] if n_rows else 0) or 0)
    if total == 0:
        return OverviewKPI(
            total_statements=0, distinct_users=0, distinct_workspaces=0,
            success_rate=0, failed_count=0, canceled_count=0,
            median_duration_ms=None, p95_duration_ms=None,
            cache_hit_rate=0, serverless_share=0,
            genie_query_count=0, dashboard_query_count=0,
            job_query_count=0, notebook_query_count=0,
            has_data=False, engine=engine,
        )

    where, params = _date_filter_sql(start_date, end_date, workspace_id)
    agg_sql = f"""
        SELECT
            COUNT(*) AS total,
            COUNT(DISTINCT executed_by) AS users,
            COUNT(DISTINCT workspace_id) AS ws,
            SUM(CASE WHEN execution_status = 'FINISHED' THEN 1 ELSE 0 END) AS finished,
            SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN execution_status = 'CANCELED' THEN 1 ELSE 0 END) AS canceled,
            SUM(CASE WHEN from_result_cache THEN 1 ELSE 0 END) AS cache,
            SUM(CASE WHEN compute_type = 'SERVERLESS_COMPUTE' THEN 1 ELSE 0 END) AS serverless,
            SUM(CASE WHEN source_category = 'GENIE' THEN 1 ELSE 0 END) AS genie,
            SUM(CASE WHEN source_category = 'DASHBOARD' THEN 1 ELSE 0 END) AS dash,
            SUM(CASE WHEN source_category = 'JOB' THEN 1 ELSE 0 END) AS job,
            SUM(CASE WHEN source_category = 'NOTEBOOK' THEN 1 ELSE 0 END) AS nb,
            MIN(start_date) AS dmin,
            MAX(start_date) AS dmax
        FROM qi_statements
        WHERE 1=1 {where}
    """
    pct_sql = f"""
        SELECT
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_duration_ms) AS p50,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_duration_ms) AS p95
        FROM qi_statements
        WHERE 1=1 {where}
    """
    agg_rows = await run_qi(db, agg_sql, params)
    pct_rows = await run_qi(db, pct_sql, params)
    r = agg_rows[0] if agg_rows else {}
    p = pct_rows[0] if pct_rows else {}
    n = max(int(r.get("total") or 0), 1)

    # Audit row only lives in Postgres regardless of engine — query directly.
    from sqlalchemy import select
    from models import QiExtractRun
    last_run = (await db.execute(
        select(QiExtractRun).where(QiExtractRun.status == "success").order_by(QiExtractRun.id.desc()).limit(1)
    )).scalar_one_or_none()

    return OverviewKPI(
        total_statements=int(r.get("total") or 0),
        distinct_users=int(r.get("users") or 0),
        distinct_workspaces=int(r.get("ws") or 0),
        success_rate=round(int(r.get("finished") or 0) / n, 4),
        failed_count=int(r.get("failed") or 0),
        canceled_count=int(r.get("canceled") or 0),
        median_duration_ms=float(p["p50"]) if p.get("p50") is not None else None,
        p95_duration_ms=float(p["p95"]) if p.get("p95") is not None else None,
        cache_hit_rate=round(int(r.get("cache") or 0) / n, 4),
        serverless_share=round(int(r.get("serverless") or 0) / n, 4),
        genie_query_count=int(r.get("genie") or 0),
        dashboard_query_count=int(r.get("dash") or 0),
        job_query_count=int(r.get("job") or 0),
        notebook_query_count=int(r.get("nb") or 0),
        has_data=True,
        last_extract_at=last_run.ended_at if last_run else None,
        last_extract_source=last_run.source_file if last_run else None,
        date_min=r.get("dmin"),
        date_max=r.get("dmax"),
        engine=engine,
    )


# ---------------------------------------------------------------------------
# Platform / IT Admin
# ---------------------------------------------------------------------------

@router.get("/platform/expensive-queries")
async def expensive_queries(
    limit: int = Query(50, le=200),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    workspace_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    where, params = _date_filter_sql(start_date, end_date, workspace_id)
    params["lim"] = limit
    return await run_qi(db, f"""
        SELECT statement_id, executed_by, workspace_id, warehouse_id, compute_type,
               total_duration_ms, read_bytes, shuffle_read_bytes, spilled_local_bytes,
               produced_rows, statement_type, statement_text_excerpt, start_time
        FROM qi_statements WHERE 1=1 {where}
        ORDER BY total_duration_ms DESC NULLS LAST LIMIT :lim
    """, params)


@router.get("/platform/full-scans")
async def full_scans(
    limit: int = Query(50, le=200),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    workspace_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    where, params = _date_filter_sql(start_date, end_date, workspace_id)
    params["lim"] = limit
    return await run_qi(db, f"""
        SELECT statement_id, executed_by, workspace_id, read_bytes, produced_rows,
               total_duration_ms, statement_text_excerpt, start_time
        FROM qi_statements
        WHERE is_full_scan = TRUE {where}
        ORDER BY read_bytes DESC NULLS LAST LIMIT :lim
    """, params)


@router.get("/platform/spill-leaders")
async def spill_leaders(
    limit: int = Query(20),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    workspace_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    where, params = _date_filter_sql(start_date, end_date, workspace_id)
    params["lim"] = limit
    return await run_qi(db, f"""
        SELECT executed_by AS "user",
               SUM(spilled_local_bytes) AS spill_bytes,
               COUNT(*) AS statements
        FROM qi_statements
        WHERE spilled_local_bytes > 0 {where}
        GROUP BY executed_by
        ORDER BY SUM(spilled_local_bytes) DESC LIMIT :lim
    """, params)


@router.get("/platform/error-trends")
async def error_trends(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    workspace_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    where, params = _date_filter_sql(start_date, end_date, workspace_id)
    return await run_qi(db, f"""
        SELECT start_date AS d, error_category AS category, COUNT(*) AS n
        FROM qi_statements
        WHERE error_category IS NOT NULL {where}
        GROUP BY start_date, error_category
        ORDER BY start_date
    """, params)


@router.get("/platform/error-categories")
async def error_categories(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    workspace_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    where, params = _date_filter_sql(start_date, end_date, workspace_id)
    return await run_qi(db, f"""
        SELECT error_category AS category, error_code AS code, COUNT(*) AS n
        FROM qi_statements
        WHERE error_category IS NOT NULL {where}
        GROUP BY error_category, error_code
        ORDER BY COUNT(*) DESC
    """, params)


@router.get("/platform/capacity-queueing")
async def capacity_queueing(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    workspace_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    where, params = _date_filter_sql(start_date, end_date, workspace_id)
    return await run_qi(db, f"""
        SELECT start_hour AS hour,
               workspace_id AS workspace,
               AVG(waiting_at_capacity_duration_ms) AS avg_wait_ms,
               COUNT(*) AS statements
        FROM qi_statements
        WHERE start_hour IS NOT NULL {where}
        GROUP BY start_hour, workspace_id
        ORDER BY start_hour
    """, params)


@router.get("/platform/cache-effectiveness")
async def cache_effectiveness(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    workspace_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    where, params = _date_filter_sql(start_date, end_date, workspace_id)
    rows = await run_qi(db, f"""
        SELECT dashboard_id AS dashboard,
               COUNT(*) AS total,
               SUM(CASE WHEN from_result_cache THEN 1 ELSE 0 END) AS cache_hits
        FROM qi_statements
        WHERE dashboard_id IS NOT NULL {where}
        GROUP BY dashboard_id
        ORDER BY COUNT(*) DESC LIMIT 50
    """, params)
    return [{**r, "cache_rate": (r["cache_hits"] / r["total"]) if r["total"] else 0} for r in rows]


# ---------------------------------------------------------------------------
# Catalog usage
# ---------------------------------------------------------------------------

@router.get("/catalog/top-tables")
async def top_tables(
    limit: int = Query(20),
    role: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    workspace_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    where, params = _date_filter_sql(start_date, end_date, workspace_id, alias="s")
    role_clause = ""
    if role:
        role_clause = " AND t.role = :role"
        params["role"] = role
    params["lim"] = limit
    return await run_qi(db, f"""
        SELECT t.fully_qualified AS "table", t.catalog, t.schema, t.table_name,
               COUNT(DISTINCT t.statement_id) AS statements,
               COUNT(DISTINCT s.executed_by) AS users
        FROM qi_statement_tables t
        JOIN qi_statements s ON s.statement_id = t.statement_id
        WHERE 1=1 {role_clause} {where}
        GROUP BY t.fully_qualified, t.catalog, t.schema, t.table_name
        ORDER BY COUNT(DISTINCT t.statement_id) DESC LIMIT :lim
    """, params)


@router.get("/catalog/top-columns")
async def top_columns(
    limit: int = Query(20),
    role: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    params: dict[str, Any] = {"lim": limit}
    role_clause = ""
    if role:
        role_clause = " AND role = :role"
        params["role"] = role
    return await run_qi(db, f"""
        SELECT column_name, role,
               COUNT(DISTINCT statement_id) AS statements
        FROM qi_statement_columns
        WHERE 1=1 {role_clause}
        GROUP BY column_name, role
        ORDER BY COUNT(DISTINCT statement_id) DESC LIMIT :lim
    """, params)


@router.get("/catalog/partitioning-candidates")
async def partitioning_candidates(limit: int = Query(20), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT t.fully_qualified AS "table",
               AVG(s.pruning_ratio) AS avg_pruning,
               SUM(s.read_bytes) AS read_bytes,
               COUNT(DISTINCT t.statement_id) AS statements
        FROM qi_statement_tables t
        JOIN qi_statements s ON s.statement_id = t.statement_id
        WHERE t.role = 'read' AND s.pruning_ratio IS NOT NULL
        GROUP BY t.fully_qualified
        HAVING COUNT(DISTINCT t.statement_id) >= 5
        ORDER BY AVG(s.pruning_ratio) ASC LIMIT :lim
    """, {"lim": limit})


@router.get("/catalog/zombie-tables")
async def zombie_tables(limit: int = Query(20), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT t.fully_qualified AS "table",
               COUNT(DISTINCT t.statement_id) AS write_count
        FROM qi_statement_tables t
        WHERE t.role = 'write'
          AND t.fully_qualified NOT IN (
              SELECT DISTINCT fully_qualified FROM qi_statement_tables WHERE role = 'read'
          )
        GROUP BY t.fully_qualified
        ORDER BY COUNT(DISTINCT t.statement_id) DESC LIMIT :lim
    """, {"lim": limit})


# ---------------------------------------------------------------------------
# FinOps
# ---------------------------------------------------------------------------

@router.get("/finops/tag-coverage")
async def tag_coverage(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    workspace_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    where, params = _date_filter_sql(start_date, end_date, workspace_id)
    rows = await run_qi(db, f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN is_parameterized THEN 1 ELSE 0 END) AS parameterized
        FROM qi_statements
        WHERE 1=1 {where}
    """, params)
    r = rows[0] if rows else {"total": 0, "parameterized": 0}
    total = int(r.get("total") or 0)
    parameterized = int(r.get("parameterized") or 0)
    return {
        "total": total,
        "parameterized": parameterized,
        "unparameterized": total - parameterized,
    }


@router.get("/finops/failed-cost")
async def failed_cost(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    workspace_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    where, params = _date_filter_sql(start_date, end_date, workspace_id)
    rows = await run_qi(db, f"""
        SELECT
          SUM(total_duration_ms) AS total_ms,
          SUM(CASE WHEN execution_status = 'FAILED'   THEN total_duration_ms ELSE 0 END) AS failed_ms,
          SUM(CASE WHEN execution_status = 'CANCELED' THEN total_duration_ms ELSE 0 END) AS canceled_ms
        FROM qi_statements WHERE 1=1 {where}
    """, params)
    r = rows[0] if rows else {}
    total_ms = int(r.get("total_ms") or 0)
    failed_ms = int(r.get("failed_ms") or 0)
    canceled_ms = int(r.get("canceled_ms") or 0)
    return {
        "total_ms": total_ms,
        "failed_ms": failed_ms,
        "canceled_ms": canceled_ms,
        "wasted_share": round((failed_ms + canceled_ms) / total_ms, 4) if total_ms else 0,
    }


@router.get("/finops/source-attribution")
async def source_attribution(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    workspace_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    where, params = _date_filter_sql(start_date, end_date, workspace_id)
    return await run_qi(db, f"""
        SELECT source_category AS category,
               COUNT(*) AS statements,
               SUM(total_duration_ms) AS total_ms,
               AVG(total_duration_ms) AS avg_ms
        FROM qi_statements WHERE 1=1 {where}
        GROUP BY source_category
        ORDER BY SUM(total_duration_ms) DESC
    """, params)


@router.get("/finops/project-search")
async def project_search(
    keyword: str = Query(..., description="keyword to find across catalogs, schemas, tables"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    where, base_params = _date_filter_sql(start_date, end_date, None)
    params = {**base_params, "kw": f"%{keyword.lower()}%"}
    # Statements that touch the keyword (via any field of qi_statement_tables).
    summary_sql = f"""
        SELECT COUNT(*) AS statements,
               COUNT(DISTINCT s.executed_by) AS users,
               COUNT(DISTINCT s.workspace_id) AS workspaces,
               SUM(s.total_duration_ms) AS total_ms,
               SUM(s.read_bytes) AS read_bytes,
               SUM(CASE WHEN s.execution_status = 'FAILED' THEN 1 ELSE 0 END) AS failed
        FROM qi_statements s
        WHERE s.statement_id IN (
            SELECT DISTINCT statement_id FROM qi_statement_tables
            WHERE LOWER(catalog) LIKE :kw
               OR LOWER(schema) LIKE :kw
               OR LOWER(table_name) LIKE :kw
               OR LOWER(fully_qualified) LIKE :kw
        ) {where}
    """
    series_sql = f"""
        SELECT s.start_date AS d,
               COUNT(*) AS statements,
               SUM(s.total_duration_ms) AS total_ms
        FROM qi_statements s
        WHERE s.statement_id IN (
            SELECT DISTINCT statement_id FROM qi_statement_tables
            WHERE LOWER(catalog) LIKE :kw
               OR LOWER(schema) LIKE :kw
               OR LOWER(table_name) LIKE :kw
               OR LOWER(fully_qualified) LIKE :kw
        ) {where}
        GROUP BY s.start_date ORDER BY s.start_date
    """
    top_users_sql = f"""
        SELECT s.executed_by AS "user", COUNT(*) AS statements
        FROM qi_statements s
        WHERE s.statement_id IN (
            SELECT DISTINCT statement_id FROM qi_statement_tables
            WHERE LOWER(catalog) LIKE :kw
               OR LOWER(schema) LIKE :kw
               OR LOWER(table_name) LIKE :kw
               OR LOWER(fully_qualified) LIKE :kw
        ) {where}
        GROUP BY s.executed_by ORDER BY COUNT(*) DESC LIMIT 10
    """
    summary_rows = await run_qi(db, summary_sql, params)
    daily = await run_qi(db, series_sql, params)
    top_users = await run_qi(db, top_users_sql, params)
    s = summary_rows[0] if summary_rows else {}
    return {
        "summary": {
            "statements": int(s.get("statements") or 0),
            "users": int(s.get("users") or 0),
            "workspaces": int(s.get("workspaces") or 0),
            "total_ms": int(s.get("total_ms") or 0),
            "read_bytes": int(s.get("read_bytes") or 0),
            "failed": int(s.get("failed") or 0),
        },
        "daily": daily,
        "top_users": top_users,
    }


# ---------------------------------------------------------------------------
# Executive
# ---------------------------------------------------------------------------
#
# Date-range + grain pattern. Every dashboard endpoint that paints a chart
# should accept these three params:
#   - start_date (YYYY-MM-DD, optional — default open-ended)
#   - end_date   (YYYY-MM-DD, optional — default open-ended)
#   - grain      (one of `_VALID_GRAINS` — interpolated into DATE_TRUNC so
#                 it MUST be safelisted; never a raw user string in SQL)
#
# The safelist is the SQL-injection defence: `grain` ends up baked into the
# query string via f-string because DATE_TRUNC's first argument is a literal,
# not a bindable parameter. `_safe_grain()` clamps it to the enum.

_VALID_GRAINS = ("day", "week", "month", "quarter", "year")


def _safe_grain(grain: Optional[str], default: str = "month") -> str:
    """Clamp a caller-supplied grain to the safelisted enum so it can be
    safely interpolated into DATE_TRUNC. Anything off-list falls back to
    the default."""
    g = (grain or "").strip().lower()
    return g if g in _VALID_GRAINS else default


@router.get("/executive/adoption-trend")
async def adoption_trend(
    start_date: Optional[str] = Query(None),
    end_date:   Optional[str] = Query(None),
    grain:      Optional[str] = Query(None, description=f"One of {_VALID_GRAINS}; default 'month'."),
    db: AsyncSession = Depends(get_db),
):
    """Distinct users / dashboards / jobs / notebooks / Genie spaces per
    grain. Filters on qi_statements.start_date; the returned bucket column
    is always `period` so the frontend doesn't have to switch on grain."""
    g = _safe_grain(grain, "month")
    rows = await run_qi(db, f"""
        SELECT
            DATE_TRUNC('{g}', start_date)::date AS period,
            COUNT(DISTINCT executed_by)    FILTER (WHERE executed_by IS NOT NULL)    AS users,
            COUNT(DISTINCT dashboard_id)   FILTER (WHERE dashboard_id IS NOT NULL)   AS dashboards,
            COUNT(DISTINCT job_id)         FILTER (WHERE job_id IS NOT NULL)         AS jobs,
            COUNT(DISTINCT notebook_id)    FILTER (WHERE notebook_id IS NOT NULL)    AS notebooks,
            COUNT(DISTINCT genie_space_id) FILTER (WHERE genie_space_id IS NOT NULL) AS genie_spaces,
            COUNT(*) AS statements
        FROM qi_statements
        WHERE start_date IS NOT NULL
          AND (:start_date IS NULL OR start_date >= CAST(:start_date AS DATE))
          AND (:end_date   IS NULL OR start_date <= CAST(:end_date   AS DATE))
        GROUP BY DATE_TRUNC('{g}', start_date)
        ORDER BY DATE_TRUNC('{g}', start_date)
    """, {"start_date": start_date, "end_date": end_date})
    return rows


@router.get("/executive/serverless-share")
async def serverless_share(
    start_date: Optional[str] = Query(None),
    end_date:   Optional[str] = Query(None),
    grain:      Optional[str] = Query(None, description=f"One of {_VALID_GRAINS}; default 'day'."),
    db: AsyncSession = Depends(get_db),
):
    """Serverless vs Warehouse query share over time. Bucketed by `grain`
    (default 'day' since the original chart was daily)."""
    g = _safe_grain(grain, "day")
    return await run_qi(db, f"""
        SELECT
            DATE_TRUNC('{g}', start_date)::date AS period,
            SUM(CASE WHEN compute_type = 'SERVERLESS_COMPUTE' THEN 1 ELSE 0 END) AS serverless,
            SUM(CASE WHEN compute_type = 'WAREHOUSE'          THEN 1 ELSE 0 END) AS warehouse,
            COUNT(*) AS total
        FROM qi_statements
        WHERE start_date IS NOT NULL
          AND (:start_date IS NULL OR start_date >= CAST(:start_date AS DATE))
          AND (:end_date   IS NULL OR start_date <= CAST(:end_date   AS DATE))
        GROUP BY DATE_TRUNC('{g}', start_date)
        ORDER BY DATE_TRUNC('{g}', start_date)
    """, {"start_date": start_date, "end_date": end_date})


@router.get("/executive/reliability")
async def reliability(
    start_date: Optional[str] = Query(None),
    end_date:   Optional[str] = Query(None),
    grain:      Optional[str] = Query(None, description=f"One of {_VALID_GRAINS}; default 'week'."),
    db: AsyncSession = Depends(get_db),
):
    """Statement outcome counts + derived success_rate per `grain` (default
    'week')."""
    g = _safe_grain(grain, "week")
    rows = await run_qi(db, f"""
        SELECT
            DATE_TRUNC('{g}', start_date)::date AS period,
            COUNT(*) AS total,
            SUM(CASE WHEN execution_status = 'FINISHED' THEN 1 ELSE 0 END) AS finished,
            SUM(CASE WHEN execution_status = 'FAILED'   THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN execution_status = 'CANCELED' THEN 1 ELSE 0 END) AS canceled
        FROM qi_statements
        WHERE start_date IS NOT NULL
          AND (:start_date IS NULL OR start_date >= CAST(:start_date AS DATE))
          AND (:end_date   IS NULL OR start_date <= CAST(:end_date   AS DATE))
        GROUP BY DATE_TRUNC('{g}', start_date)
        ORDER BY DATE_TRUNC('{g}', start_date)
    """, {"start_date": start_date, "end_date": end_date})
    return [{**r, "success_rate": (int(r["finished"] or 0) / int(r["total"])) if r.get("total") else 0} for r in rows]


# ---------------------------------------------------------------------------
# Data Engineering
# ---------------------------------------------------------------------------

@router.get("/dataeng/job-failure-rates")
async def job_failure_rates(limit: int = Query(20), db: AsyncSession = Depends(get_db)):
    rows = await run_qi(db, """
        SELECT job_id,
               COUNT(*) AS statements,
               SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) AS failed,
               AVG(total_duration_ms) AS avg_duration_ms
        FROM qi_statements WHERE job_id IS NOT NULL
        GROUP BY job_id HAVING COUNT(*) >= 5
        ORDER BY (SUM(CASE WHEN execution_status='FAILED' THEN 1 ELSE 0 END) * 1.0 / COUNT(*)) DESC,
                 COUNT(*) DESC
        LIMIT :lim
    """, {"lim": limit})
    return [{**r, "failure_rate": round(int(r["failed"] or 0) / int(r["statements"] or 1), 4)} for r in rows]


@router.get("/dataeng/slowest-pipelines")
async def slowest_pipelines(limit: int = Query(20), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT pipeline_id,
               COUNT(*) AS statements,
               AVG(total_duration_ms) AS avg_ms,
               MAX(total_duration_ms) AS max_ms,
               SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) AS failed
        FROM qi_statements WHERE pipeline_id IS NOT NULL
        GROUP BY pipeline_id ORDER BY AVG(total_duration_ms) DESC NULLS LAST LIMIT :lim
    """, {"lim": limit})


@router.get("/dataeng/compile-heavy")
async def compile_heavy(limit: int = Query(20), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT statement_id, executed_by, statement_text_excerpt,
               total_duration_ms, compilation_duration_ms, compile_pct
        FROM qi_statements
        WHERE compile_pct > 0.25 AND total_duration_ms > 500
        ORDER BY compile_pct DESC, total_duration_ms DESC LIMIT :lim
    """, {"lim": limit})


# ---------------------------------------------------------------------------
# BI / Analytics
# ---------------------------------------------------------------------------

@router.get("/bi/slowest-dashboards")
async def slowest_dashboards(limit: int = Query(20), db: AsyncSession = Depends(get_db)):
    rows = await run_qi(db, """
        SELECT dashboard_id, COUNT(*) AS query_count,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_duration_ms) AS p50_ms,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_duration_ms) AS p95_ms,
               SUM(CASE WHEN from_result_cache THEN 1 ELSE 0 END) AS cache_hits
        FROM qi_statements WHERE dashboard_id IS NOT NULL
        GROUP BY dashboard_id ORDER BY PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_duration_ms) DESC NULLS LAST LIMIT :lim
    """, {"lim": limit})
    return [{**r, "cache_rate": (int(r["cache_hits"] or 0) / int(r["query_count"] or 1))} for r in rows]


@router.get("/bi/vendor-footprint")
async def vendor_footprint(db: AsyncSession = Depends(get_db)):
    rows = await run_qi(db, """
        SELECT COALESCE(client_application, 'Unknown') AS application,
               COUNT(*) AS statements,
               COUNT(DISTINCT executed_by) AS users,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_duration_ms) AS p50_ms,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_duration_ms) AS p95_ms,
               SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) AS failed
        FROM qi_statements GROUP BY COALESCE(client_application, 'Unknown')
        ORDER BY COUNT(*) DESC LIMIT 20
    """)
    return [{**r, "failure_rate": (int(r["failed"] or 0) / int(r["statements"] or 1))} for r in rows]


@router.get("/bi/select-star-dashboards")
async def select_star_dashboards(limit: int = Query(20), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT dashboard_id, COUNT(*) AS total,
               SUM(CASE WHEN has_select_star THEN 1 ELSE 0 END) AS star_count
        FROM qi_statements WHERE dashboard_id IS NOT NULL
        GROUP BY dashboard_id
        HAVING SUM(CASE WHEN has_select_star THEN 1 ELSE 0 END) > 0
        ORDER BY SUM(CASE WHEN has_select_star THEN 1 ELSE 0 END) DESC, COUNT(*) DESC LIMIT :lim
    """, {"lim": limit})


# ---------------------------------------------------------------------------
# Data Science
# ---------------------------------------------------------------------------

@router.get("/datascience/notebook-activity")
async def notebook_activity(limit: int = Query(20), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT notebook_id, COUNT(*) AS queries,
               COUNT(DISTINCT executed_by) AS users,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_duration_ms) AS p50_ms,
               SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) AS failed
        FROM qi_statements WHERE notebook_id IS NOT NULL
        GROUP BY notebook_id ORDER BY COUNT(*) DESC LIMIT :lim
    """, {"lim": limit})


@router.get("/datascience/genie-adoption")
async def genie_adoption(db: AsyncSession = Depends(get_db)):
    rows = await run_qi(db, """
        SELECT DATE_TRUNC('week', start_date)::date AS week,
               COUNT(*) AS queries,
               COUNT(DISTINCT genie_space_id) AS spaces,
               COUNT(DISTINCT executed_by) AS users,
               SUM(CASE WHEN execution_status = 'FINISHED' THEN 1 ELSE 0 END) AS finished
        FROM qi_statements WHERE genie_space_id IS NOT NULL AND start_date IS NOT NULL
        GROUP BY DATE_TRUNC('week', start_date)
        ORDER BY DATE_TRUNC('week', start_date)
    """)
    return [{**r, "success_rate": (int(r["finished"] or 0) / int(r["queries"] or 1))} for r in rows]


# ---------------------------------------------------------------------------
# Security & Governance
# ---------------------------------------------------------------------------

@router.get("/security/permission-denied")
async def permission_denied(limit: int = Query(50), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT s.executed_by AS "user", e.referenced_object,
               COUNT(*) AS denials,
               MIN(s.start_time) AS first_seen,
               MAX(s.start_time) AS last_seen
        FROM qi_statement_errors e
        JOIN qi_statements s ON s.statement_id = e.statement_id
        WHERE e.error_category = 'PERMISSION'
        GROUP BY s.executed_by, e.referenced_object
        ORDER BY COUNT(*) DESC LIMIT :lim
    """, {"lim": limit})


@router.get("/security/off-hours-pii")
async def off_hours_pii(limit: int = Query(50), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT executed_by AS "user", workspace_id,
               COUNT(*) AS off_hour_queries,
               SUM(read_bytes) AS read_bytes
        FROM qi_statements
        WHERE is_off_hours = TRUE AND principal_kind = 'human'
        GROUP BY executed_by, workspace_id
        HAVING COUNT(*) >= 5
        ORDER BY COUNT(*) DESC LIMIT :lim
    """, {"lim": limit})


@router.get("/security/bulk-export")
async def bulk_export(limit: int = Query(50), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT executed_by AS "user", session_id,
               COUNT(*) AS queries,
               SUM(read_rows) AS read_rows,
               SUM(read_bytes) AS read_bytes
        FROM qi_statements WHERE session_id IS NOT NULL
        GROUP BY executed_by, session_id
        HAVING SUM(read_bytes) > 5368709120
        ORDER BY SUM(read_bytes) DESC LIMIT :lim
    """, {"lim": limit})


@router.get("/security/grant-revoke")
async def grant_revoke(limit: int = Query(50), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT statement_id, executed_by, workspace_id, start_time,
               statement_text_excerpt, execution_status
        FROM qi_statements WHERE is_grant_revoke = TRUE
        ORDER BY start_time DESC NULLS LAST LIMIT :lim
    """, {"lim": limit})


@router.get("/security/driver-versions")
async def driver_versions(db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT COALESCE(client_driver_family, 'Unknown') AS family,
               COALESCE(client_driver_version, '?') AS version,
               COUNT(*) AS statements,
               COUNT(DISTINCT executed_by) AS users
        FROM qi_statements WHERE client_driver IS NOT NULL
        GROUP BY COALESCE(client_driver_family, 'Unknown'), COALESCE(client_driver_version, '?')
        ORDER BY COUNT(*) DESC LIMIT 50
    """)


@router.get("/security/delegated-execution")
async def delegated_execution(limit: int = Query(50), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT executed_by, executed_as,
               COUNT(*) AS statements,
               COUNT(DISTINCT statement_id) AS distinct_stmts
        FROM qi_statements WHERE is_delegated = TRUE
        GROUP BY executed_by, executed_as ORDER BY COUNT(*) DESC LIMIT :lim
    """, {"lim": limit})


# ---------------------------------------------------------------------------
# Developer Experience
# ---------------------------------------------------------------------------

@router.get("/devex/user-footprint")
async def user_footprint(limit: int = Query(30), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT executed_by AS "user", COUNT(*) AS total,
               COUNT(DISTINCT client_application) AS tools,
               SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) AS failed,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_duration_ms) AS p50_ms,
               SUM(read_bytes) AS read_bytes
        FROM qi_statements WHERE executed_by IS NOT NULL
        GROUP BY executed_by ORDER BY COUNT(*) DESC LIMIT :lim
    """, {"lim": limit})


@router.get("/devex/tool-mix")
async def tool_mix(db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT COALESCE(client_application, 'Unknown') AS application,
               COUNT(*) AS queries,
               COUNT(DISTINCT executed_by) AS users
        FROM qi_statements GROUP BY COALESCE(client_application, 'Unknown')
        ORDER BY COUNT(*) DESC
    """)


@router.get("/devex/syntax-errors")
async def syntax_errors(limit: int = Query(20), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT s.executed_by AS "user", e.error_category, COUNT(*) AS errors
        FROM qi_statement_errors e
        JOIN qi_statements s ON s.statement_id = e.statement_id
        WHERE e.error_category IN ('PARSE', 'NOT_FOUND', 'ANALYSIS')
        GROUP BY s.executed_by, e.error_category
        ORDER BY COUNT(*) DESC LIMIT :lim
    """, {"lim": limit})


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------

@router.get("/cross/sql-feature-mix")
async def sql_feature_mix(db: AsyncSession = Depends(get_db)):
    rows = await run_qi(db, """
        SELECT
            SUM(CASE WHEN has_cte THEN 1 ELSE 0 END) AS cte,
            SUM(CASE WHEN has_subquery THEN 1 ELSE 0 END) AS subquery,
            SUM(CASE WHEN has_window THEN 1 ELSE 0 END) AS "window",
            SUM(CASE WHEN has_select_star THEN 1 ELSE 0 END) AS select_star,
            SUM(CASE WHEN has_cross_join THEN 1 ELSE 0 END) AS cross_join,
            SUM(CASE WHEN is_parameterized THEN 1 ELSE 0 END) AS parameterized,
            SUM(CASE WHEN is_describe_or_show THEN 1 ELSE 0 END) AS describe_show,
            COUNT(*) AS total
        FROM qi_statements WHERE is_sql = TRUE
    """)
    return rows[0] if rows else {}


@router.get("/cross/hour-of-day")
async def hour_of_day(db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT start_hour AS hour,
               COUNT(*) AS queries,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_duration_ms) AS p50_ms
        FROM qi_statements WHERE start_hour IS NOT NULL
        GROUP BY start_hour ORDER BY start_hour
    """)


@router.get("/cross/duplicate-queries")
async def duplicate_queries(limit: int = Query(20), db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT normalized_sql_hash,
               COUNT(*) AS runs,
               MIN(statement_text_excerpt) AS sample_excerpt,
               AVG(total_duration_ms) AS avg_ms,
               SUM(total_duration_ms) AS total_ms,
               COUNT(DISTINCT executed_by) AS users
        FROM qi_statements WHERE normalized_sql_hash IS NOT NULL
        GROUP BY normalized_sql_hash
        HAVING COUNT(*) >= 5
        ORDER BY COUNT(*) DESC, SUM(total_duration_ms) DESC LIMIT :lim
    """, {"lim": limit})


@router.get("/cross/statement-type-mix")
async def statement_type_mix(db: AsyncSession = Depends(get_db)):
    return await run_qi(db, """
        SELECT COALESCE(statement_type, 'UNKNOWN') AS statement_type,
               COUNT(*) AS n
        FROM qi_statements
        GROUP BY COALESCE(statement_type, 'UNKNOWN')
        ORDER BY COUNT(*) DESC
    """)
