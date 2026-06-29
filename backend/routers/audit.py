"""Meta Explorer > Audit — dashboards over system.access.audit and
system.access.assistant_events.

Backs the `/api/meta/audit/*` endpoints used by the new Audit page under
Meta Explorer. View-mode scoped + soft-delete filtered like every other
Meta Explorer endpoint.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import AuthedUser, get_current_user
from database import get_db
from models import AssistantEvent, AuditEvent

logger = logging.getLogger(__name__)

# Hosted under the existing Meta Explorer prefix so the frontend's
# `/api/meta/...` namespace stays cohesive.
router = APIRouter(prefix="/api/meta/audit", tags=["meta-explorer"])


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------

class AuditBreakdownEntry(BaseModel):
    label: str
    count: int


class AuditStats(BaseModel):
    audit_events: int
    assistant_events: int
    distinct_users: int
    distinct_actions: int
    distinct_services: int
    error_events: int     # response_status_code >= 400
    last_event: Optional[str] = None

    by_service: list[AuditBreakdownEntry] = []
    by_audit_level: list[AuditBreakdownEntry] = []   # ACCOUNT_LEVEL / WORKSPACE_LEVEL
    by_status_class: list[AuditBreakdownEntry] = []  # 2xx / 4xx / 5xx / other
    top_actions: list[AuditBreakdownEntry] = []      # service:action
    top_users: list[AuditBreakdownEntry] = []        # user_identity_email
    top_assistant_users: list[AuditBreakdownEntry] = []  # initiated_by
    assistant_distinct_users: int = 0
    assistant_last_event: Optional[str] = None


class AuditEventOut(BaseModel):
    event_time: Optional[datetime]
    user_identity_email: Optional[str]
    service_name: Optional[str]
    action_name: Optional[str]
    audit_level: Optional[str]
    response_status_code: Optional[int]
    response_error_message: Optional[str]
    source_ip_address: Optional[str]
    workspace_id: Optional[str]
    request_id: Optional[str]
    event_id: Optional[str]


class AuditSearchHit(AuditEventOut):
    matched_in: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scoped(stmt, user: AuthedUser, model):
    return (
        stmt
        .where(model.data_origin == user.viewing_data_mode)
        .where(model.deleted_at.is_(None))
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=AuditStats)
async def audit_stats(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(15, ge=1, le=100),
):
    """Headline counters + the four primary breakdown bars for the
    Audit dashboard."""
    total_audit = (await db.execute(
        _scoped(select(func.count()).select_from(AuditEvent), user, AuditEvent)
    )).scalar() or 0
    total_assistant = (await db.execute(
        _scoped(select(func.count()).select_from(AssistantEvent), user, AssistantEvent)
    )).scalar() or 0
    distinct_users = (await db.execute(
        _scoped(
            select(func.count(distinct(AuditEvent.user_identity_email))),
            user, AuditEvent,
        ).where(AuditEvent.user_identity_email.isnot(None))
    )).scalar() or 0
    distinct_actions = (await db.execute(
        _scoped(
            select(func.count(distinct(
                func.concat(
                    func.coalesce(AuditEvent.service_name, "?"), ":",
                    func.coalesce(AuditEvent.action_name, "?"),
                )
            ))),
            user, AuditEvent,
        )
    )).scalar() or 0
    distinct_services = (await db.execute(
        _scoped(
            select(func.count(distinct(AuditEvent.service_name))),
            user, AuditEvent,
        ).where(AuditEvent.service_name.isnot(None))
    )).scalar() or 0
    error_events = (await db.execute(
        _scoped(select(func.count()).select_from(AuditEvent), user, AuditEvent)
        .where(AuditEvent.response_status_code.isnot(None))
        .where(AuditEvent.response_status_code >= 400)
    )).scalar() or 0
    last_event = (await db.execute(
        _scoped(select(func.max(AuditEvent.event_time)), user, AuditEvent)
    )).scalar()

    # Breakdown bars.
    by_service_rows = (await db.execute(
        _scoped(
            select(
                func.coalesce(AuditEvent.service_name, "(none)").label("k"),
                func.count().label("c"),
            ),
            user, AuditEvent,
        ).group_by("k").order_by(func.count().desc()).limit(20)
    )).all()
    by_level_rows = (await db.execute(
        _scoped(
            select(
                func.coalesce(AuditEvent.audit_level, "(none)").label("k"),
                func.count().label("c"),
            ),
            user, AuditEvent,
        ).group_by("k").order_by(func.count().desc()).limit(5)
    )).all()
    status_class = case(
        (AuditEvent.response_status_code.is_(None), "(none)"),
        (AuditEvent.response_status_code < 300, "2xx"),
        (AuditEvent.response_status_code < 400, "3xx"),
        (AuditEvent.response_status_code < 500, "4xx"),
        else_="5xx",
    )
    by_status_rows = (await db.execute(
        _scoped(
            select(status_class.label("k"), func.count().label("c")),
            user, AuditEvent,
        ).group_by("k").order_by(func.count().desc()).limit(10)
    )).all()
    top_actions_rows = (await db.execute(
        _scoped(
            select(
                func.concat(
                    func.coalesce(AuditEvent.service_name, "?"), ":",
                    func.coalesce(AuditEvent.action_name, "?"),
                ).label("k"),
                func.count().label("c"),
            ),
            user, AuditEvent,
        ).group_by("k").order_by(func.count().desc()).limit(limit)
    )).all()
    top_users_rows = (await db.execute(
        _scoped(
            select(
                AuditEvent.user_identity_email.label("k"),
                func.count().label("c"),
            ),
            user, AuditEvent,
        ).where(AuditEvent.user_identity_email.isnot(None))
         .group_by(AuditEvent.user_identity_email)
         .order_by(func.count().desc())
         .limit(limit)
    )).all()
    top_assistant_rows = (await db.execute(
        _scoped(
            select(
                AssistantEvent.initiated_by.label("k"),
                func.count().label("c"),
            ),
            user, AssistantEvent,
        ).where(AssistantEvent.initiated_by.isnot(None))
         .group_by(AssistantEvent.initiated_by)
         .order_by(func.count().desc())
         .limit(limit)
    )).all()
    assistant_distinct = (await db.execute(
        _scoped(
            select(func.count(distinct(AssistantEvent.initiated_by))),
            user, AssistantEvent,
        ).where(AssistantEvent.initiated_by.isnot(None))
    )).scalar() or 0
    assistant_last = (await db.execute(
        _scoped(select(func.max(AssistantEvent.event_time)), user, AssistantEvent)
    )).scalar()

    return AuditStats(
        audit_events=int(total_audit),
        assistant_events=int(total_assistant),
        distinct_users=int(distinct_users),
        distinct_actions=int(distinct_actions),
        distinct_services=int(distinct_services),
        error_events=int(error_events),
        last_event=str(last_event) if last_event is not None else None,
        by_service=[AuditBreakdownEntry(label=r.k, count=int(r.c)) for r in by_service_rows],
        by_audit_level=[AuditBreakdownEntry(label=r.k, count=int(r.c)) for r in by_level_rows],
        by_status_class=[AuditBreakdownEntry(label=r.k, count=int(r.c)) for r in by_status_rows],
        top_actions=[AuditBreakdownEntry(label=r.k, count=int(r.c)) for r in top_actions_rows],
        top_users=[AuditBreakdownEntry(label=r.k, count=int(r.c)) for r in top_users_rows],
        top_assistant_users=[AuditBreakdownEntry(label=r.k, count=int(r.c)) for r in top_assistant_rows],
        assistant_distinct_users=int(assistant_distinct),
        assistant_last_event=str(assistant_last) if assistant_last is not None else None,
    )


@router.get("/recent", response_model=list[AuditEventOut])
async def audit_recent(
    limit: int = Query(50, ge=1, le=500),
    errors_only: bool = Query(False),
    service: Optional[str] = Query(None, description="Optional service_name filter (e.g., 'unityCatalog')"),
    user_email: Optional[str] = Query(None, description="Optional user_identity_email filter"),
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Most-recent audit rows, newest first. Supports a few common filters."""
    stmt = _scoped(
        select(
            AuditEvent.event_time, AuditEvent.user_identity_email,
            AuditEvent.service_name, AuditEvent.action_name,
            AuditEvent.audit_level, AuditEvent.response_status_code,
            AuditEvent.response_error_message,
            AuditEvent.source_ip_address, AuditEvent.workspace_id,
            AuditEvent.request_id, AuditEvent.event_id,
        ),
        user, AuditEvent,
    )
    if errors_only:
        stmt = stmt.where(AuditEvent.response_status_code.isnot(None))
        stmt = stmt.where(AuditEvent.response_status_code >= 400)
    if service:
        stmt = stmt.where(AuditEvent.service_name == service)
    if user_email:
        stmt = stmt.where(AuditEvent.user_identity_email == user_email)
    stmt = stmt.order_by(AuditEvent.event_time.desc()).limit(limit)
    rows = (await db.execute(stmt)).mappings().all()
    return [AuditEventOut(**dict(r)) for r in rows]


@router.get("/search", response_model=list[AuditSearchHit])
async def audit_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(50, ge=1, le=200),
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Substring search across user, service, action, IP, error message."""
    needle = f"%{q.lower()}%"
    stmt = _scoped(
        select(
            AuditEvent.event_time, AuditEvent.user_identity_email,
            AuditEvent.service_name, AuditEvent.action_name,
            AuditEvent.audit_level, AuditEvent.response_status_code,
            AuditEvent.response_error_message,
            AuditEvent.source_ip_address, AuditEvent.workspace_id,
            AuditEvent.request_id, AuditEvent.event_id,
        ),
        user, AuditEvent,
    ).where(
        or_(
            func.lower(AuditEvent.user_identity_email).like(needle),
            func.lower(AuditEvent.service_name).like(needle),
            func.lower(AuditEvent.action_name).like(needle),
            func.lower(AuditEvent.source_ip_address).like(needle),
            func.lower(AuditEvent.response_error_message).like(needle),
        )
    ).order_by(AuditEvent.event_time.desc()).limit(limit)
    rows = (await db.execute(stmt)).mappings().all()
    out: list[AuditSearchHit] = []
    for r in rows:
        d = dict(r)
        for col, label in (
            ("user_identity_email", "user"),
            ("service_name", "service"),
            ("action_name", "action"),
            ("source_ip_address", "ip"),
            ("response_error_message", "error"),
        ):
            v = d.get(col)
            if isinstance(v, str) and q.lower() in v.lower():
                matched = label
                break
        else:
            matched = "other"
        out.append(AuditSearchHit(matched_in=matched, **d))
    return out
