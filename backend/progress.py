"""
In-process progress tracker for long-running synchronous endpoints.

The Data Management page kicks off operations that take seconds to minutes —
Databricks extracts, parquet loads, demo seeding, Query Profiler ETL, lineage
rollups. Until this module existed, the UI showed only a spinner with no
information about *where* in the pipeline the work currently was.

Design:
  * One module-level `_STATE` dict keyed by operation "kind"
    (e.g. `extract`, `ingest-parquet`, `seed-demo`, `query-intel-real`,
    `transform-lineage-demo`). Operations of the same kind share a slot —
    starting a new run overwrites the previous one. The UI polls the GET
    endpoint and renders whichever kinds are 'running'.
  * Async-safe via a single `asyncio.Lock` — every mutation goes through
    the lock so concurrent endpoint handlers can't corrupt state. Reads
    are lock-free (dict copy) since they're only used by the polling UI
    and a stale read is acceptable.
  * Auto-eviction: completed/failed entries linger for `_TTL_SECONDS` so
    the UI has a chance to display the final state, then drop off.

Usage from a handler:

    tracker = progress.start("transform-lineage-real",
                             label="Lineage rollups (real)",
                             total_steps=4)
    tracker.step("Aggregating sources …")
    ...
    tracker.step("Aggregating targets …")
    ...
    tracker.finish(summary={"rollup_rows": 1234})
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TTL_SECONDS = 300          # how long finished/failed entries stay visible
_LOCK = asyncio.Lock()


@dataclass
class ProgressEntry:
    kind: str
    label: str
    status: str = "running"                 # running | success | failed | cancelled
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    current_step: int = 0
    total_steps: int = 0
    last_message: str = ""
    error: Optional[str] = None
    summary: Optional[dict[str, Any]] = None
    # Cooperative cancellation flag. Set via `request_cancel(kind)` and
    # polled by the running handler; the watcher coroutine reads
    # `is_cancel_requested(kind)` between steps and aborts the in-flight
    # work task. Stays True after the run is finalized so the UI can show
    # "Cancelled by user" rather than a generic error.
    cancel_requested: bool = False

    def as_public_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Add a UI-friendly elapsed time so the polling client doesn't need
        # to know server-side timestamps.
        end = self.finished_at or time.time()
        d["elapsed_seconds"] = round(end - self.started_at, 2)
        return d


_STATE: dict[str, ProgressEntry] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class _Handle:
    """Returned by start(). Methods are coroutines so callers `await` them."""

    def __init__(self, kind: str):
        self.kind = kind

    async def step(self, message: str, advance: int = 1) -> None:
        async with _LOCK:
            entry = _STATE.get(self.kind)
            if entry is None or entry.status != "running":
                return
            entry.current_step = min(entry.current_step + advance, entry.total_steps or entry.current_step + advance)
            entry.last_message = message
        logger.info("[progress:%s] %d/%d %s", self.kind, entry.current_step, entry.total_steps, message)

    async def set_total(self, total: int) -> None:
        async with _LOCK:
            entry = _STATE.get(self.kind)
            if entry is None:
                return
            entry.total_steps = max(0, total)

    async def message(self, message: str) -> None:
        """Update last_message without advancing the step counter."""
        async with _LOCK:
            entry = _STATE.get(self.kind)
            if entry is None or entry.status != "running":
                return
            entry.last_message = message
        logger.info("[progress:%s] %s", self.kind, message)

    async def finish(self, summary: Optional[dict[str, Any]] = None) -> None:
        async with _LOCK:
            entry = _STATE.get(self.kind)
            if entry is None:
                return
            entry.status = "success"
            entry.finished_at = time.time()
            if entry.total_steps:
                entry.current_step = entry.total_steps
            if summary:
                entry.summary = summary
            entry.last_message = entry.last_message or "Done."
        logger.info("[progress:%s] DONE in %.2fs", self.kind, (entry.finished_at - entry.started_at))

    async def fail(self, error: str) -> None:
        async with _LOCK:
            entry = _STATE.get(self.kind)
            if entry is None:
                return
            entry.status = "failed"
            entry.finished_at = time.time()
            entry.error = error
            entry.last_message = f"Failed: {error}"
        logger.warning("[progress:%s] FAILED: %s", self.kind, error)

    async def cancelled(self, reason: str = "Cancelled by user.") -> None:
        """Mark the run as cancelled. Distinct terminal status from 'failed'
        so the UI can render it neutrally instead of with the red error
        palette."""
        async with _LOCK:
            entry = _STATE.get(self.kind)
            if entry is None:
                return
            entry.status = "cancelled"
            entry.finished_at = time.time()
            entry.last_message = reason
        logger.info("[progress:%s] CANCELLED — %s", self.kind, reason)


async def start(kind: str, *, label: str, total_steps: int = 0) -> _Handle:
    """Begin tracking a new run of `kind`. Overwrites any previous entry."""
    async with _LOCK:
        _STATE[kind] = ProgressEntry(kind=kind, label=label, total_steps=total_steps)
    logger.info("[progress:%s] START — %s (target %d steps)", kind, label, total_steps)
    return _Handle(kind)


async def snapshot() -> dict[str, dict[str, Any]]:
    """Return the public view of every tracked entry, evicting stale finished ones."""
    now = time.time()
    out: dict[str, dict[str, Any]] = {}
    async with _LOCK:
        stale: list[str] = []
        for k, e in _STATE.items():
            if e.finished_at and (now - e.finished_at) > _TTL_SECONDS:
                stale.append(k)
                continue
            out[k] = e.as_public_dict()
        for k in stale:
            _STATE.pop(k, None)
    return out


async def clear(kind: str) -> None:
    """Forcibly drop an entry — used when tests need a clean slate."""
    async with _LOCK:
        _STATE.pop(kind, None)


# ---------------------------------------------------------------------------
# Cooperative cancellation
# ---------------------------------------------------------------------------
#
# A running handler that wants to be cancellable should:
#   1. Wrap its long-running awaitable in `asyncio.create_task` so it can
#      be cancelled externally.
#   2. Run a watcher coroutine alongside that task which polls
#      `is_cancel_requested(kind)` every ~0.5s; on True, `task.cancel()`.
#   3. In its CancelledError handler, call `tracker.cancelled(...)` to
#      mark the entry as the 'cancelled' terminal status.
#
# The flag is also a sync read (no lock) — the watcher polls it frequently
# and we want the read path to be cheap.

async def request_cancel(kind: str) -> bool:
    """Mark a running entry as cancel-requested. Returns True if the entry
    existed AND was still running; False otherwise (so the cancel endpoint
    can return 404 / 409 appropriately)."""
    async with _LOCK:
        entry = _STATE.get(kind)
        if entry is None or entry.status != "running":
            return False
        entry.cancel_requested = True
        entry.last_message = "Cancellation requested — stopping…"
    logger.info("[progress:%s] cancel requested", kind)
    return True


def is_cancel_requested(kind: str) -> bool:
    """Cheap, lock-free read used by the watcher coroutine. A stale read
    is acceptable — the next poll catches up within ~0.5s."""
    entry = _STATE.get(kind)
    return bool(entry and entry.cancel_requested)
