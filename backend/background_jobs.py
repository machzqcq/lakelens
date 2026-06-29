"""Background job runner — long-running operations (extracts, loads, deletes,
incremental updates, query intel ETL) execute asynchronously and their
progress is persisted in the `background_jobs` Postgres table.

Why this exists:
  * Long ops shouldn't hold an HTTP request open. The endpoint enqueues
    a job and returns immediately with the `job_id`.
  * Progress survives the user closing the browser or navigating away —
    the frontend notifications bell re-fetches the job rows from Postgres.
  * On a container restart, the lifespan hook marks orphaned `running`
    rows as `lost` so the UI doesn't show a phantom in-flight job.

Usage from an endpoint:

    job_id = await enqueue(
        db, kind="hard-delete", started_by=user.id,
        params={"data_origin": "demo"},
        coro=lambda db, report: _do_hard_delete(db, report, "demo"),
    )
    return {"job_id": job_id}

The runner gives the coroutine a `report(progress_pct, message, current, total)`
helper. The coroutine should call it periodically; the runner persists each
update. The coroutine should also check `await is_cancel_requested(db, job_id)`
between steps to bail cleanly when the user clicks Cancel.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session
from models import BackgroundJob

logger = logging.getLogger(__name__)

JobCoro = Callable[[AsyncSession, "ProgressReporter"], Awaitable[Any]]


class ProgressReporter:
    """Helper passed to job coroutines. Persists progress to the job row."""

    def __init__(self, job_id: int):
        self.job_id = job_id
        self._last_persist = datetime.utcnow()
        # Avoid hammering the DB on every row — coalesce to ~1 update/sec.
        self._min_interval = timedelta(milliseconds=750)

    async def __call__(
        self,
        pct: Optional[float] = None,
        message: Optional[str] = None,
        current: Optional[int] = None,
        total: Optional[int] = None,
        force: bool = False,
    ) -> None:
        now = datetime.utcnow()
        if not force and (now - self._last_persist) < self._min_interval:
            return
        self._last_persist = now
        values: dict[str, Any] = {}
        if pct is not None:
            values["progress_pct"] = max(0.0, min(100.0, float(pct)))
        if message is not None:
            values["message"] = message[:4000]
        if current is not None:
            values["current_step"] = current
        if total is not None:
            values["total_steps"] = total
        if not values:
            return
        async with async_session() as db:
            await db.execute(
                update(BackgroundJob).where(BackgroundJob.id == self.job_id).values(**values)
            )
            await db.commit()


async def is_cancel_requested(job_id: int) -> bool:
    async with async_session() as db:
        row = (await db.execute(
            select(BackgroundJob.cancel_requested).where(BackgroundJob.id == job_id)
        )).scalar_one_or_none()
        return bool(row)


async def enqueue(
    db: AsyncSession,
    kind: str,
    started_by: Optional[int],
    params: Optional[dict[str, Any]],
    coro: JobCoro,
) -> int:
    """Insert a job row + fire the coroutine via asyncio.create_task.

    The coroutine receives a fresh session (not the caller's `db`).
    Returns the job id for the client to track.
    """
    job = BackgroundJob(
        kind=kind,
        status="queued",
        params_json=params or {},
        started_by_user_id=started_by,
        progress_pct=0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    job_id = job.id

    asyncio.create_task(_run(job_id, coro))
    logger.info("[jobs] enqueued kind=%s id=%d by=%s", kind, job_id, started_by)
    return job_id


async def _run(job_id: int, coro: JobCoro) -> None:
    """Background task: open a session, mark running, invoke coro, update terminal status."""
    started = datetime.utcnow()
    async with async_session() as db:
        await db.execute(
            update(BackgroundJob).where(BackgroundJob.id == job_id).values(
                status="running", started_at=started,
            )
        )
        await db.commit()

    report = ProgressReporter(job_id)
    final_status = "success"
    error_message: Optional[str] = None
    result: Any = None

    try:
        async with async_session() as db:
            result = await coro(db, report)
    except asyncio.CancelledError:
        final_status = "canceled"
        error_message = "task canceled"
        raise
    except Exception as e:  # noqa: BLE001
        final_status = "failed"
        error_message = str(e)
        logger.exception("[jobs] id=%d failed: %s", job_id, e)
    finally:
        # Always update terminal status in its own session — even on CancelledError.
        try:
            async with async_session() as db2:
                values: dict[str, Any] = {
                    "status": final_status,
                    "ended_at": datetime.utcnow(),
                }
                if final_status == "success":
                    values["progress_pct"] = 100
                    values["result_json"] = result if isinstance(result, dict) else {"value": result}
                elif final_status in ("failed", "canceled"):
                    values["error_message"] = error_message
                await db2.execute(
                    update(BackgroundJob).where(BackgroundJob.id == job_id).values(**values)
                )
                await db2.commit()
            logger.info("[jobs] id=%d terminal status=%s", job_id, final_status)
        except Exception:  # noqa: BLE001
            logger.exception("[jobs] id=%d failed to write terminal status", job_id)


async def reap_orphan_jobs() -> int:
    """Called at app startup. Anything still marked 'running' from a previous
    container life is now 'lost'."""
    async with async_session() as db:
        result = await db.execute(
            update(BackgroundJob)
            .where(BackgroundJob.status.in_(["running", "queued"]))
            .values(
                status="lost",
                ended_at=datetime.utcnow(),
                error_message="Container restarted while this job was in flight.",
            )
        )
        await db.commit()
        n = result.rowcount or 0
        if n:
            logger.warning("[jobs] reaped %d orphaned job(s) at startup", n)
        return n


async def request_cancel(db: AsyncSession, job_id: int) -> bool:
    """Mark the job for cancellation. The coroutine sees it on the next
    is_cancel_requested() check and exits."""
    result = await db.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == job_id, BackgroundJob.status.in_(["queued", "running"]))
        .values(cancel_requested=True)
    )
    await db.commit()
    return (result.rowcount or 0) > 0
