"""Data-isolation operations + background job tracking.

Endpoints in this router:

  Engine / view-mode toggles
      GET    /api/data-ops/me/view-mode
      PATCH  /api/data-ops/me/view-mode

  Long-running data ops — all return a `{job_id}` and run as background jobs.
  Progress is visible via the NotificationsBell (which polls /jobs).
      POST   /api/data-ops/soft-delete            body: {origin: 'demo'|'real'}
      POST   /api/data-ops/hard-delete            body: {origin: 'demo'|'real'}
      POST   /api/data-ops/restore                body: {origin: 'demo'|'real'}
      POST   /api/data-ops/incremental-load       body: {file_prefix: ''|'demo_'}

  Background job control
      GET    /api/data-ops/jobs                   list current user's recent jobs
      GET    /api/data-ops/jobs/{id}              one job
      POST   /api/data-ops/jobs/{id}/cancel
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import AuthedUser, get_current_user, require_admin
from background_jobs import enqueue, is_cancel_requested, request_cancel
from database import get_db
from models import (
    AssistantEvent,
    AuditEvent,
    BackgroundJob,
    BillingUsage,
    Cluster,
    ColumnLineage,
    DatabricksMeta,
    IngestCursor,
    InstanceEvent,
    InstancePool,
    Job,
    ListPrice,
    NodeTimeline,
    NodeType,
    QiStatement,
    QiStatementColumn,
    QiStatementError,
    QiStatementParameter,
    QiStatementTable,
    QiStatementTag,
    QueryHistory,
    TableLineage,
    User,
    Warehouse,
    WarehouseEvent,
    Workspace,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data-ops", tags=["data-ops"])


# Tables in the domain scope. Two lists because the soft/restore semantics
# require a `deleted_at` tombstone column, while hard-delete only needs
# `data_origin` — and the qi_* family was deliberately built without
# `deleted_at` (every QI ETL run rebuilds its partition wholesale, so a
# soft-delete tombstone has no meaning there).
#
#   _SOFT_DELETE_MODELS — has both data_origin AND deleted_at.
#                         Used by soft-delete, restore, and the
#                         per-table counts view (which groups on
#                         deleted_at IS NULL).
#   _HARD_DELETE_MODELS — every model that has data_origin.
#                         Used by hard-delete so admins can wipe a
#                         partition end-to-end (including qi_*, audit_*,
#                         lineage, node-pool, meta — all of which were
#                         absent from the old list and were the reason
#                         "Hard delete" silently leaked qi_* and the
#                         later additions).
_SOFT_DELETE_MODELS = [
    BillingUsage, ListPrice, Cluster, Warehouse, Job, Workspace, QueryHistory,
    DatabricksMeta, TableLineage, ColumnLineage,
    AuditEvent, AssistantEvent,
    NodeTimeline, WarehouseEvent, NodeType, InstanceEvent, InstancePool,
]
_ORIGIN_ONLY_MODELS = [
    QiStatement, QiStatementTable, QiStatementColumn,
    QiStatementTag, QiStatementParameter, QiStatementError,
]
_HARD_DELETE_MODELS = _SOFT_DELETE_MODELS + _ORIGIN_ONLY_MODELS

# Back-compat alias — kept so any downstream import doesn't break, but new
# code should reach for the explicit list above.
_DOMAIN_MODELS = _SOFT_DELETE_MODELS
_DOMAIN_MODEL_NAMES = {m.__tablename__: m for m in _SOFT_DELETE_MODELS}


# ---------------------------------------------------------------------------
# View mode (per-user sticky setting)
# ---------------------------------------------------------------------------

class ViewMode(BaseModel):
    mode: Literal["real", "demo"]


@router.get("/me/view-mode", response_model=ViewMode)
async def get_my_view_mode(user: AuthedUser = Depends(get_current_user)):
    return ViewMode(mode=user.viewing_data_mode)  # type: ignore[arg-type]


@router.patch("/me/view-mode", response_model=ViewMode)
async def set_my_view_mode(
    body: ViewMode,
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(User).where(User.id == user.user.id).values(viewing_data_mode=body.mode)
    )
    await db.commit()
    return body


# ---------------------------------------------------------------------------
# Background jobs API
# ---------------------------------------------------------------------------

class JobOut(BaseModel):
    id: int
    kind: str
    status: str
    progress_pct: float
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    message: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    error_message: Optional[str] = None
    result_json: Optional[dict[str, Any]] = None
    params_json: Optional[dict[str, Any]] = None
    cancel_requested: bool = False


def _job_to_dto(job: BackgroundJob) -> JobOut:
    return JobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        progress_pct=float(job.progress_pct or 0),
        current_step=job.current_step,
        total_steps=job.total_steps,
        message=job.message,
        started_at=job.started_at,
        ended_at=job.ended_at,
        error_message=job.error_message,
        result_json=job.result_json,
        params_json=job.params_json,
        cancel_requested=bool(job.cancel_requested),
    )


@router.get("/progress")
async def progress_snapshot(_user: AuthedUser = Depends(get_current_user)):
    """Live progress map for synchronous Data Management operations.

    Keys are operation kinds (e.g. `extract`, `ingest-parquet`, `seed-demo`,
    `query-intel-real`, `transform-lineage-demo`). Values include the current
    step, last message, status, elapsed time, and (on completion) a summary
    dict. Polled by the frontend every ~1s while any mutation is pending.
    """
    import progress as progress_module
    return await progress_module.snapshot()


@router.post("/progress/{kind}/cancel")
async def progress_cancel(
    kind: str,
    _user: AuthedUser = Depends(get_current_user),
):
    """Request cancellation of a running progress entry. The endpoint that
    started the entry must be cooperatively wrapping its work in a Task
    that watches for the cancel flag — see backend/progress.py docstring.

    Returns 404 if no such entry; 409 if the entry is no longer running
    (already finished/failed/cancelled)."""
    import progress as progress_module
    snapshot = await progress_module.snapshot()
    entry = snapshot.get(kind)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No progress entry for kind={kind!r}")
    if entry.get("status") != "running":
        raise HTTPException(
            status_code=409,
            detail=f"Progress entry {kind!r} is not running (status={entry.get('status')})",
        )
    ok = await progress_module.request_cancel(kind)
    if not ok:
        # Race — the entry finished between our snapshot and the flag set.
        raise HTTPException(status_code=409, detail=f"Progress entry {kind!r} just finished.")
    return {"kind": kind, "cancel_requested": True}


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    hours: int = 24,
    limit: int = 50,
):
    """Return the current user's jobs in the last `hours` hours, newest first.
    Admins see every user's jobs."""
    since = datetime.utcnow() - timedelta(hours=hours)
    q = select(BackgroundJob).where(BackgroundJob.started_at >= since).order_by(BackgroundJob.id.desc()).limit(limit)
    if not user.is_admin:
        q = q.where(BackgroundJob.started_by_user_id == user.user.id)
    rows = (await db.execute(q)).scalars().all()
    return [_job_to_dto(r) for r in rows]


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(
    job_id: int,
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(BackgroundJob).where(BackgroundJob.id == job_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not user.is_admin and row.started_by_user_id != user.user.id:
        raise HTTPException(status_code=403, detail="Not your job")
    return _job_to_dto(row)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    job_id: int,
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(BackgroundJob).where(BackgroundJob.id == job_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not user.is_admin and row.started_by_user_id != user.user.id:
        raise HTTPException(status_code=403, detail="Not your job")
    await request_cancel(db, job_id)
    # Refresh
    row = (await db.execute(select(BackgroundJob).where(BackgroundJob.id == job_id))).scalar_one()
    return _job_to_dto(row)


# ---------------------------------------------------------------------------
# Soft / hard delete + restore (background jobs)
# ---------------------------------------------------------------------------

class OriginBody(BaseModel):
    origin: Literal["real", "demo"]


async def _do_soft_delete(db: AsyncSession, report, origin: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    total = len(_SOFT_DELETE_MODELS)
    now = datetime.utcnow()
    for i, model in enumerate(_SOFT_DELETE_MODELS, start=1):
        await report(pct=(i - 1) * 100 / total, message=f"Soft-deleting {model.__tablename__} (origin={origin})",
                     current=i - 1, total=total, force=True)
        result = await db.execute(
            update(model)
            .where(model.data_origin == origin)
            .where(model.deleted_at.is_(None))
            .values(deleted_at=now)
        )
        counts[model.__tablename__] = result.rowcount or 0
    await db.commit()
    await report(pct=100, message=f"Soft delete complete ({origin})", current=total, total=total, force=True)
    return counts


async def _do_hard_delete(db: AsyncSession, report, origin: str) -> dict[str, int]:
    """Wipe every row whose data_origin matches `origin`, across the full
    set of isolation-aware tables (including qi_*, audit_*, lineage,
    node-pool, meta — all of which the old list omitted)."""
    counts: dict[str, int] = {}
    total = len(_HARD_DELETE_MODELS)
    for i, model in enumerate(_HARD_DELETE_MODELS, start=1):
        await report(pct=(i - 1) * 100 / total, message=f"Hard-deleting {model.__tablename__} (origin={origin})",
                     current=i - 1, total=total, force=True)
        result = await db.execute(sa_delete(model).where(model.data_origin == origin))
        counts[model.__tablename__] = result.rowcount or 0
    await db.commit()
    await report(pct=100, message=f"Hard delete complete ({origin})", current=total, total=total, force=True)
    return counts


async def _do_restore(db: AsyncSession, report, origin: str) -> dict[str, int]:
    """Clear deleted_at for rows matching the origin. Only the soft-delete
    models qualify — restore is meaningless for the qi_* family which has
    no tombstone column."""
    counts: dict[str, int] = {}
    total = len(_SOFT_DELETE_MODELS)
    for i, model in enumerate(_SOFT_DELETE_MODELS, start=1):
        await report(pct=(i - 1) * 100 / total, message=f"Restoring {model.__tablename__} (origin={origin})",
                     current=i - 1, total=total, force=True)
        result = await db.execute(
            update(model)
            .where(model.data_origin == origin)
            .where(model.deleted_at.isnot(None))
            .values(deleted_at=None)
        )
        counts[model.__tablename__] = result.rowcount or 0
    await db.commit()
    await report(pct=100, message=f"Restore complete ({origin})", current=total, total=total, force=True)
    return counts


@router.post("/soft-delete")
async def soft_delete(
    body: OriginBody,
    user: AuthedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    origin = body.origin
    job_id = await enqueue(
        db,
        kind=f"soft-delete:{origin}",
        started_by=user.user.id,
        params={"origin": origin},
        coro=lambda db2, report: _do_soft_delete(db2, report, origin),
    )
    return {"job_id": job_id}


@router.post("/hard-delete")
async def hard_delete(
    body: OriginBody,
    user: AuthedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    origin = body.origin
    job_id = await enqueue(
        db,
        kind=f"hard-delete:{origin}",
        started_by=user.user.id,
        params={"origin": origin},
        coro=lambda db2, report: _do_hard_delete(db2, report, origin),
    )
    return {"job_id": job_id}


@router.post("/restore")
async def restore(
    body: OriginBody,
    user: AuthedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    origin = body.origin
    job_id = await enqueue(
        db,
        kind=f"restore:{origin}",
        started_by=user.user.id,
        params={"origin": origin},
        coro=lambda db2, report: _do_restore(db2, report, origin),
    )
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Incremental load (cursor-based)
# ---------------------------------------------------------------------------

class IncrementalLoadBody(BaseModel):
    file_prefix: str = Field("", description="'' for real, 'demo_' for demo")
    data_origin: Literal["real", "demo"] = "real"


_CURSOR_COLUMNS = {
    "billing_usage":  ("usage_end_time", "record_id"),
    "list_prices":    ("price_start_time", None),
    "clusters":       ("change_time", "cluster_id"),
    "warehouses":     ("change_time", "warehouse_id"),
    "jobs":           ("change_time", "job_id"),
    "workspaces":     ("create_time", "workspace_id"),
    "query_history":  ("update_time", "statement_id"),
}


async def _get_or_create_cursor(db: AsyncSession, table: str, origin: str) -> IngestCursor:
    cur = (await db.execute(
        select(IngestCursor).where(
            IngestCursor.table_name == table,
            IngestCursor.data_origin == origin,
        )
    )).scalar_one_or_none()
    if cur is None:
        cur = IngestCursor(table_name=table, data_origin=origin)
        db.add(cur)
        await db.commit()
        await db.refresh(cur)
    return cur


async def _do_incremental_load(
    db: AsyncSession,
    report,
    file_prefix: str,
    data_origin: str,
) -> dict[str, Any]:
    """Read latest parquet per table, filter rows newer than the per-table
    cursor, append, advance cursor. Each table is one step in the progress bar.
    """
    data_path = Path("data")
    tables = list(_CURSOR_COLUMNS.keys())
    counts: dict[str, int] = {}
    total = len(tables)

    for i, table in enumerate(tables, start=1):
        await report(pct=(i - 1) * 100 / total, message=f"Incremental load: {table}",
                     current=i - 1, total=total, force=True)
        pattern = f"{file_prefix}{table}_*.parquet"
        files = sorted(data_path.glob(pattern), reverse=True)
        if not file_prefix:
            files = [f for f in files if not f.name.startswith("demo_")]
        if not files:
            counts[table] = 0
            continue

        try:
            df = pd.read_parquet(files[0])
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not read %s: %s", files[0], e)
            counts[table] = 0
            continue

        time_col, key_col = _CURSOR_COLUMNS[table]
        cur = await _get_or_create_cursor(db, table, data_origin)

        if time_col in df.columns and cur.max_update_time is not None:
            df = df[df[time_col] > cur.max_update_time]
        if df.empty:
            counts[table] = 0
            continue

        # Use the existing ingest path (append, scoped to origin, dedupes on PK).
        from extract.ingest import (
            ingest_clusters, ingest_jobs, ingest_list_prices, ingest_query_history,
            ingest_usage, ingest_warehouses, ingest_workspaces,
        )

        ingest_funcs = {
            "billing_usage":  lambda d: ingest_usage(db, d, replace=False, data_origin=data_origin),
            "list_prices":    lambda d: ingest_list_prices(db, d, replace=False, data_origin=data_origin),
            "clusters":       lambda d: ingest_clusters(db, d, replace=False, data_origin=data_origin),
            "warehouses":     lambda d: ingest_warehouses(db, d, replace=False, data_origin=data_origin),
            "jobs":           lambda d: ingest_jobs(db, d, replace=False, data_origin=data_origin),
            "workspaces":     lambda d: ingest_workspaces(db, d, data_origin=data_origin),
            "query_history":  lambda d: ingest_query_history(db, d, replace=False, data_origin=data_origin),
        }
        n = await ingest_funcs[table](df)
        counts[table] = n

        # Advance cursor
        if time_col in df.columns:
            new_max = df[time_col].max()
            if pd.notna(new_max):
                cur.max_update_time = new_max.to_pydatetime() if hasattr(new_max, "to_pydatetime") else new_max
        if key_col and key_col in df.columns:
            new_key_max = df[key_col].max()
            if pd.notna(new_key_max):
                cur.max_record_id = str(new_key_max)
        cur.last_run_at = datetime.utcnow()
        cur.rows_ingested = (cur.rows_ingested or 0) + n
        await db.commit()

        if await is_cancel_requested(0):  # not strictly correct — see runner
            break

    await report(pct=100, message="Incremental load complete", current=total, total=total, force=True)
    return {"counts": counts, "data_origin": data_origin}


@router.post("/incremental-load")
async def incremental_load(
    body: IncrementalLoadBody,
    user: AuthedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    job_id = await enqueue(
        db,
        kind=f"incremental-load:{body.data_origin}",
        started_by=user.user.id,
        params={"file_prefix": body.file_prefix, "data_origin": body.data_origin},
        coro=lambda db2, report: _do_incremental_load(db2, report, body.file_prefix, body.data_origin),
    )
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Stats — counts per origin / deleted state, for the Data Management page
# ---------------------------------------------------------------------------

@router.get("/stats")
async def data_origin_stats(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-table counts split by (data_origin, deleted) so the UI can show
    'Demo: 50k live / 0 deleted; Real: 372k live / 0 deleted' tiles.

    Two query shapes:
      * tables with deleted_at  → group by (origin, deleted_at IS NULL)
      * tables without (qi_*)   → group by origin only; every row counts
                                  as 'live' (no soft-delete tombstone).
    """
    out: dict[str, dict[str, dict[str, int]]] = {}
    soft_table_names = {m.__tablename__ for m in _SOFT_DELETE_MODELS}
    for model in _HARD_DELETE_MODELS:
        tbl = model.__tablename__
        has_deleted_at = tbl in soft_table_names
        if has_deleted_at:
            sql = f"""
                SELECT data_origin AS origin,
                       CASE WHEN deleted_at IS NULL THEN 'live' ELSE 'deleted' END AS state,
                       COUNT(*) AS n
                FROM {tbl}
                GROUP BY 1, 2
            """
        else:
            sql = f"""
                SELECT data_origin AS origin,
                       'live' AS state,
                       COUNT(*) AS n
                FROM {tbl}
                GROUP BY 1
            """
        row = (await db.execute(text(sql))).mappings().all()
        per: dict[str, dict[str, int]] = {"demo": {"live": 0, "deleted": 0},
                                          "real": {"live": 0, "deleted": 0}}
        for r in row:
            origin = r["origin"] or "real"
            state = r["state"]
            if origin in per and state in per[origin]:
                per[origin][state] = int(r["n"])
        out[tbl] = per
    return out
