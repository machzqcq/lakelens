"""Meta Explorer > Node Pool — dashboards over system.compute.node_timeline,
warehouse_events, node_types, instance_events, instance_pools.

Backs the `/api/meta/node-pool/*` endpoints used by the Node Pool page
under Meta Explorer. View-mode scoped + soft-delete filtered like every
other Meta Explorer endpoint.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import AuthedUser, get_current_user
from database import get_db
from models import (
    InstanceEvent, InstancePool, NodeTimeline, NodeType, WarehouseEvent,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meta/node-pool", tags=["meta-explorer"])


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------

class BreakdownEntry(BaseModel):
    label: str
    count: int


class NodePoolStats(BaseModel):
    node_timeline_rows: int
    warehouse_event_rows: int
    instance_event_rows: int
    node_type_rows: int
    instance_pool_rows: int

    distinct_clusters_in_timeline: int
    distinct_instances_in_timeline: int
    distinct_warehouses_in_events: int
    distinct_pools_referenced: int
    last_node_timeline: Optional[str] = None
    last_warehouse_event: Optional[str] = None
    last_instance_event: Optional[str] = None

    # Headline breakdowns for chart strips on the dashboard.
    by_warehouse_event_type: list[BreakdownEntry] = []
    by_instance_event_type:  list[BreakdownEntry] = []
    by_node_type_category:   list[BreakdownEntry] = []


class UtilizationRow(BaseModel):
    cluster_id: Optional[str]
    sample_count: int
    avg_cpu_user_percent: Optional[float] = None
    avg_cpu_system_percent: Optional[float] = None
    avg_mem_used_percent: Optional[float] = None
    max_cpu_user_percent: Optional[float] = None
    max_mem_used_percent: Optional[float] = None
    last_sample: Optional[datetime] = None


class WarehouseEventOut(BaseModel):
    event_time: Optional[datetime]
    warehouse_id: Optional[str]
    event_type: Optional[str]
    cluster_count: Optional[int]
    workspace_id: Optional[str]


class InstanceEventOut(BaseModel):
    event_time: Optional[datetime]
    cluster_id: Optional[str]
    instance_id: Optional[str]
    instance_pool_id: Optional[str]
    event_type: Optional[str]
    node_type: Optional[str]
    workspace_id: Optional[str]


class NodeTypeOut(BaseModel):
    node_type: Optional[str]
    core_count: Optional[float] = None
    memory_mb: Optional[int] = None
    gpu_count: Optional[int] = None
    category: Optional[str] = None


class InstancePoolOut(BaseModel):
    instance_pool_id: Optional[str]
    instance_pool_name: Optional[str]
    node_type: Optional[str]
    min_idle_instances: Optional[int] = None
    max_capacity: Optional[int] = None
    idle_instance_autotermination_minutes: Optional[int] = None
    enable_elastic_disk: Optional[bool] = None
    workspace_id: Optional[str] = None
    create_time: Optional[datetime] = None
    change_time: Optional[datetime] = None


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

@router.get("/stats", response_model=NodePoolStats)
async def node_pool_stats(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Counters + breakdown bars for the Node Pool dashboard header."""
    total_tl = (await db.execute(
        _scoped(select(func.count()).select_from(NodeTimeline), user, NodeTimeline)
    )).scalar() or 0
    total_we = (await db.execute(
        _scoped(select(func.count()).select_from(WarehouseEvent), user, WarehouseEvent)
    )).scalar() or 0
    total_ie = (await db.execute(
        _scoped(select(func.count()).select_from(InstanceEvent), user, InstanceEvent)
    )).scalar() or 0
    total_nt = (await db.execute(
        _scoped(select(func.count()).select_from(NodeType), user, NodeType)
    )).scalar() or 0
    total_ip = (await db.execute(
        _scoped(select(func.count()).select_from(InstancePool), user, InstancePool)
    )).scalar() or 0

    distinct_clusters = (await db.execute(
        _scoped(select(func.count(distinct(NodeTimeline.cluster_id))), user, NodeTimeline)
        .where(NodeTimeline.cluster_id.isnot(None))
    )).scalar() or 0
    distinct_instances = (await db.execute(
        _scoped(select(func.count(distinct(NodeTimeline.instance_id))), user, NodeTimeline)
        .where(NodeTimeline.instance_id.isnot(None))
    )).scalar() or 0
    distinct_warehouses = (await db.execute(
        _scoped(select(func.count(distinct(WarehouseEvent.warehouse_id))), user, WarehouseEvent)
        .where(WarehouseEvent.warehouse_id.isnot(None))
    )).scalar() or 0
    distinct_pools = (await db.execute(
        _scoped(select(func.count(distinct(InstanceEvent.instance_pool_id))), user, InstanceEvent)
        .where(InstanceEvent.instance_pool_id.isnot(None))
    )).scalar() or 0

    last_tl = (await db.execute(
        _scoped(select(func.max(NodeTimeline.start_time)), user, NodeTimeline)
    )).scalar()
    last_we = (await db.execute(
        _scoped(select(func.max(WarehouseEvent.event_time)), user, WarehouseEvent)
    )).scalar()
    last_ie = (await db.execute(
        _scoped(select(func.max(InstanceEvent.event_time)), user, InstanceEvent)
    )).scalar()

    by_we_type = (await db.execute(
        _scoped(
            select(
                func.coalesce(WarehouseEvent.event_type, "(none)").label("k"),
                func.count().label("c"),
            ),
            user, WarehouseEvent,
        ).group_by("k").order_by(func.count().desc()).limit(20)
    )).all()
    by_ie_type = (await db.execute(
        _scoped(
            select(
                func.coalesce(InstanceEvent.event_type, "(none)").label("k"),
                func.count().label("c"),
            ),
            user, InstanceEvent,
        ).group_by("k").order_by(func.count().desc()).limit(20)
    )).all()
    by_nt_cat = (await db.execute(
        _scoped(
            select(
                func.coalesce(NodeType.category, "(none)").label("k"),
                func.count().label("c"),
            ),
            user, NodeType,
        ).group_by("k").order_by(func.count().desc()).limit(20)
    )).all()

    return NodePoolStats(
        node_timeline_rows=int(total_tl),
        warehouse_event_rows=int(total_we),
        instance_event_rows=int(total_ie),
        node_type_rows=int(total_nt),
        instance_pool_rows=int(total_ip),
        distinct_clusters_in_timeline=int(distinct_clusters),
        distinct_instances_in_timeline=int(distinct_instances),
        distinct_warehouses_in_events=int(distinct_warehouses),
        distinct_pools_referenced=int(distinct_pools),
        last_node_timeline=last_tl.isoformat() if last_tl else None,
        last_warehouse_event=last_we.isoformat() if last_we else None,
        last_instance_event=last_ie.isoformat() if last_ie else None,
        by_warehouse_event_type=[BreakdownEntry(label=r.k, count=int(r.c)) for r in by_we_type],
        by_instance_event_type=[BreakdownEntry(label=r.k, count=int(r.c)) for r in by_ie_type],
        by_node_type_category=[BreakdownEntry(label=r.k, count=int(r.c)) for r in by_nt_cat],
    )


@router.get("/utilization", response_model=list[UtilizationRow])
async def cluster_utilization(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(25, ge=1, le=200),
):
    """Per-cluster aggregate utilization across the resident node_timeline
    window. We deliberately avoid time-bucketed series here — that lives in
    the Spark SQL Editor / chatbot — and surface a compact "top clusters by
    sample count" table for the dashboard tile."""
    rows = (await db.execute(
        _scoped(
            select(
                NodeTimeline.cluster_id.label("cid"),
                func.count().label("samples"),
                func.avg(NodeTimeline.cpu_user_percent).label("avg_cpu_u"),
                func.avg(NodeTimeline.cpu_system_percent).label("avg_cpu_s"),
                func.avg(NodeTimeline.mem_used_percent).label("avg_mem"),
                func.max(NodeTimeline.cpu_user_percent).label("max_cpu"),
                func.max(NodeTimeline.mem_used_percent).label("max_mem"),
                func.max(NodeTimeline.start_time).label("last_sample"),
            ),
            user, NodeTimeline,
        )
        .group_by(NodeTimeline.cluster_id)
        .order_by(func.count().desc())
        .limit(limit)
    )).all()

    def _f(v: Any) -> Optional[float]:
        return None if v is None else float(v)

    return [
        UtilizationRow(
            cluster_id=r.cid,
            sample_count=int(r.samples),
            avg_cpu_user_percent=_f(r.avg_cpu_u),
            avg_cpu_system_percent=_f(r.avg_cpu_s),
            avg_mem_used_percent=_f(r.avg_mem),
            max_cpu_user_percent=_f(r.max_cpu),
            max_mem_used_percent=_f(r.max_mem),
            last_sample=r.last_sample,
        )
        for r in rows
    ]


@router.get("/warehouse-events", response_model=list[WarehouseEventOut])
async def recent_warehouse_events(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
):
    rows = (await db.execute(
        _scoped(
            select(
                WarehouseEvent.event_time,
                WarehouseEvent.warehouse_id,
                WarehouseEvent.event_type,
                WarehouseEvent.cluster_count,
                WarehouseEvent.workspace_id,
            ),
            user, WarehouseEvent,
        )
        .order_by(WarehouseEvent.event_time.desc().nullslast())
        .limit(limit)
    )).all()
    return [
        WarehouseEventOut(
            event_time=r.event_time, warehouse_id=r.warehouse_id,
            event_type=r.event_type, cluster_count=r.cluster_count,
            workspace_id=r.workspace_id,
        ) for r in rows
    ]


@router.get("/instance-events", response_model=list[InstanceEventOut])
async def recent_instance_events(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
):
    rows = (await db.execute(
        _scoped(
            select(
                InstanceEvent.event_time,
                InstanceEvent.cluster_id,
                InstanceEvent.instance_id,
                InstanceEvent.instance_pool_id,
                InstanceEvent.event_type,
                InstanceEvent.node_type,
                InstanceEvent.workspace_id,
            ),
            user, InstanceEvent,
        )
        .order_by(InstanceEvent.event_time.desc().nullslast())
        .limit(limit)
    )).all()
    return [
        InstanceEventOut(
            event_time=r.event_time, cluster_id=r.cluster_id,
            instance_id=r.instance_id, instance_pool_id=r.instance_pool_id,
            event_type=r.event_type, node_type=r.node_type,
            workspace_id=r.workspace_id,
        ) for r in rows
    ]


@router.get("/node-types", response_model=list[NodeTypeOut])
async def list_node_types(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full reference catalog — small enough to ship in one response."""
    rows = (await db.execute(
        _scoped(
            select(
                NodeType.node_type, NodeType.core_count, NodeType.memory_mb,
                NodeType.gpu_count, NodeType.category,
            ),
            user, NodeType,
        ).order_by(NodeType.category.nullslast(), NodeType.node_type.nullslast())
    )).all()
    return [
        NodeTypeOut(
            node_type=r.node_type,
            core_count=None if r.core_count is None else float(r.core_count),
            memory_mb=r.memory_mb, gpu_count=r.gpu_count, category=r.category,
        ) for r in rows
    ]


@router.get("/instance-pools", response_model=list[InstancePoolOut])
async def list_instance_pools(
    user: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full pool catalog — typically a small handful of rows per account."""
    rows = (await db.execute(
        _scoped(
            select(
                InstancePool.instance_pool_id, InstancePool.instance_pool_name,
                InstancePool.node_type, InstancePool.min_idle_instances,
                InstancePool.max_capacity,
                InstancePool.idle_instance_autotermination_minutes,
                InstancePool.enable_elastic_disk,
                InstancePool.workspace_id,
                InstancePool.create_time, InstancePool.change_time,
            ),
            user, InstancePool,
        ).order_by(InstancePool.instance_pool_name.nullslast())
    )).all()
    return [
        InstancePoolOut(
            instance_pool_id=r.instance_pool_id,
            instance_pool_name=r.instance_pool_name,
            node_type=r.node_type,
            min_idle_instances=r.min_idle_instances,
            max_capacity=r.max_capacity,
            idle_instance_autotermination_minutes=r.idle_instance_autotermination_minutes,
            enable_elastic_disk=r.enable_elastic_disk,
            workspace_id=r.workspace_id,
            create_time=r.create_time, change_time=r.change_time,
        ) for r in rows
    ]
