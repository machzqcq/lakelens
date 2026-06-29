"""Compute resource endpoints (clusters and warehouses) with pagination."""

import math
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import AuthedUser, get_current_user
from database import get_db
from models import BillingUsage, Cluster, ListPrice, Warehouse
from rbac_filters import apply_billing_filters, apply_cluster_filters, apply_warehouse_filters, resolve_effective_filters
from node_specs import (
    KNOWN_FAMILIES,
    all_specs,
    family_map,
    get_spec,
    gpu_node_types,
    memory_map,
    vcpus_map,
)
from schemas import (
    ClusterDetail,
    ClusterFullDetail,
    ClusterSkuUsage,
    ComputeCostResponse,
    NodeSpecModel,
    PaginatedClusterResponse,
    PaginatedWarehouseResponse,
    WarehouseDetail,
    WarehouseFullDetail,
    WarehouseSizeSpecModel,
    WarehouseSkuUsage,
)
from warehouse_specs import get_size_spec

router = APIRouter(
    prefix="/api/compute",
    tags=["compute"],
    dependencies=[Depends(get_current_user)],
)

_PRICE_JOIN = (
    (BillingUsage.sku_name == ListPrice.sku_name)
    & (BillingUsage.cloud == ListPrice.cloud)
    & (BillingUsage.usage_unit == ListPrice.usage_unit)
    & (BillingUsage.usage_end_time >= ListPrice.price_start_time)
    & (
        (ListPrice.price_end_time.is_(None))
        | (BillingUsage.usage_end_time < ListPrice.price_end_time)
    )
)


# ---------------------------------------------------------------------------
# Cluster CASE expressions (node_type -> spec lookup, executed in SQL)
# ---------------------------------------------------------------------------
# Built once at import. Each maps a cluster column (driver/worker node type)
# to a hardware attribute via a SQL CASE WHEN. Unknown node types -> NULL.

_DRIVER_VCPUS = case(vcpus_map(), value=Cluster.driver_node_type, else_=None)
_DRIVER_MEMORY = case(memory_map(), value=Cluster.driver_node_type, else_=None)
_DRIVER_FAMILY = case(family_map(), value=Cluster.driver_node_type, else_=None)
_DRIVER_HAS_GPU = Cluster.driver_node_type.in_(gpu_node_types())

_WORKER_VCPUS = case(vcpus_map(), value=Cluster.worker_node_type, else_=None)
_WORKER_MEMORY = case(memory_map(), value=Cluster.worker_node_type, else_=None)

# For autoscaling clusters use max as the upper bound; coalesce missing to 0
_EFFECTIVE_WORKERS = func.coalesce(
    Cluster.max_autoscale_workers, Cluster.worker_count, 0
)

# Total cluster vCPUs/memory: driver + (workers * worker_count). NULL when
# driver type is unknown so the row sorts/filters consistently. Worker term
# defaults to 0 when the worker type is unknown so we still surface drivers.
_TOTAL_VCPUS = _DRIVER_VCPUS + func.coalesce(_WORKER_VCPUS * _EFFECTIVE_WORKERS, 0)
_TOTAL_MEMORY = _DRIVER_MEMORY + func.coalesce(_WORKER_MEMORY * _EFFECTIVE_WORKERS, 0)


_SORT_COLUMNS = {
    "name": Cluster.cluster_name,
    "created": Cluster.create_time,
    "workers": _EFFECTIVE_WORKERS,
    "driver_vcpus": _DRIVER_VCPUS,
    "driver_memory_gb": _DRIVER_MEMORY,
    "total_vcpus": _TOTAL_VCPUS,
    "total_memory_gb": _TOTAL_MEMORY,
}


@router.get("/clusters", response_model=PaginatedClusterResponse)
async def list_clusters(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by cluster name, ID, or owner"),
    workspace_id: Optional[str] = Query(None, description="Filter by workspace ID"),
    cluster_source: Optional[str] = Query(None, description="Filter by source (JOB, UI, PIPELINE)"),
    data_security_mode: Optional[str] = Query(None, description="Filter by security mode"),
    node_family: Optional[str] = Query(None, description=f"Filter driver node by family: one of {KNOWN_FAMILIES}"),
    has_gpu: Optional[bool] = Query(None, description="Only clusters whose driver is a known GPU node type"),
    min_vcpus: Optional[int] = Query(None, ge=0, description="Minimum total cluster vCPUs"),
    min_memory_gb: Optional[float] = Query(None, ge=0, description="Minimum total cluster memory (GiB)"),
    sort_by: str = Query("name", description=f"Sort field: one of {list(_SORT_COLUMNS)}"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$", description="asc or desc"),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """List clusters with pagination, filtering, and sorting.

    CPU / memory based filters and sorts use a SQL CASE expression that maps
    `driver_node_type` and `worker_node_type` to hardware specs from the
    static node_specs lookup. Rows whose driver node type is unknown have
    NULL totals and are pushed to the end of CPU/memory sorts.
    """
    base = select(
        Cluster,
        _DRIVER_VCPUS.label("driver_vcpus"),
        _DRIVER_MEMORY.label("driver_memory_gb"),
        _DRIVER_FAMILY.label("driver_family"),
        _DRIVER_HAS_GPU.label("driver_has_gpu"),
        _TOTAL_VCPUS.label("total_vcpus"),
        _TOTAL_MEMORY.label("total_memory_gb"),
    )

    if search:
        term = f"%{search}%"
        base = base.where(
            or_(
                Cluster.cluster_name.ilike(term),
                Cluster.cluster_id.ilike(term),
                Cluster.owned_by.ilike(term),
            )
        )
    if workspace_id:
        base = base.where(Cluster.workspace_id == workspace_id)
    if cluster_source:
        base = base.where(Cluster.cluster_source == cluster_source)
    if data_security_mode:
        base = base.where(Cluster.data_security_mode == data_security_mode)
    if node_family:
        if node_family not in KNOWN_FAMILIES:
            raise HTTPException(
                status_code=400,
                detail=f"node_family must be one of {KNOWN_FAMILIES}",
            )
        base = base.where(_DRIVER_FAMILY == node_family)
    if has_gpu is True:
        base = base.where(_DRIVER_HAS_GPU)
    elif has_gpu is False:
        base = base.where(~_DRIVER_HAS_GPU)
    if min_vcpus is not None:
        base = base.where(_TOTAL_VCPUS >= min_vcpus)
    if min_memory_gb is not None:
        base = base.where(_TOTAL_MEMORY >= literal(min_memory_gb))

    # Apply role-based data scoping
    base = apply_cluster_filters(base, resolve_effective_filters(authed), view_mode=authed.viewing_data_mode)

    # Count
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0
    total_pages = max(math.ceil(total / page_size), 1)

    # Sort
    if sort_by not in _SORT_COLUMNS:
        raise HTTPException(
            status_code=400,
            detail=f"sort_by must be one of {list(_SORT_COLUMNS)}",
        )
    sort_col = _SORT_COLUMNS[sort_by]
    sort_expr = sort_col.desc() if sort_order == "desc" else sort_col.asc()
    # Push NULLs to the end so unknown specs don't dominate the first page
    sort_expr = sort_expr.nullslast()
    # Stable secondary order by name
    stmt = (
        base.order_by(sort_expr, Cluster.cluster_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(stmt)
    rows = result.all()

    return PaginatedClusterResponse(
        data=[
            ClusterDetail(
                cluster_id=row[0].cluster_id,
                cluster_name=row[0].cluster_name,
                workspace_id=row[0].workspace_id,
                owned_by=row[0].owned_by,
                driver_node_type=row[0].driver_node_type,
                worker_node_type=row[0].worker_node_type,
                worker_count=row[0].worker_count,
                min_autoscale_workers=row[0].min_autoscale_workers,
                max_autoscale_workers=row[0].max_autoscale_workers,
                dbr_version=row[0].dbr_version,
                cluster_source=row[0].cluster_source,
                data_security_mode=row[0].data_security_mode,
                create_time=row[0].create_time,
                delete_time=row[0].delete_time,
                driver_vcpus=row.driver_vcpus,
                driver_memory_gb=float(row.driver_memory_gb) if row.driver_memory_gb is not None else None,
                driver_family=row.driver_family,
                driver_has_gpu=row.driver_has_gpu,
                total_vcpus=int(row.total_vcpus) if row.total_vcpus is not None else None,
                total_memory_gb=float(row.total_memory_gb) if row.total_memory_gb is not None else None,
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/warehouses", response_model=PaginatedWarehouseResponse)
async def list_warehouses(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """List warehouses with pagination and search."""
    base = select(Warehouse)
    base = apply_warehouse_filters(base, resolve_effective_filters(authed), view_mode=authed.viewing_data_mode)

    if search:
        term = f"%{search}%"
        base = base.where(
            or_(
                Warehouse.warehouse_name.ilike(term),
                Warehouse.warehouse_id.ilike(term),
            )
        )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0
    total_pages = max(math.ceil(total / page_size), 1)

    stmt = base.order_by(Warehouse.warehouse_name).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    warehouses = result.scalars().all()

    return PaginatedWarehouseResponse(
        data=[
            WarehouseDetail(
                warehouse_id=w.warehouse_id,
                warehouse_name=w.warehouse_name,
                workspace_id=w.workspace_id,
                warehouse_type=w.warehouse_type,
                warehouse_size=w.warehouse_size,
                min_clusters=w.min_clusters,
                max_clusters=w.max_clusters,
                auto_stop_minutes=w.auto_stop_minutes,
                created_by=w.created_by,
                change_time=w.change_time,
                delete_time=w.delete_time,
            )
            for w in warehouses
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/node-specs", response_model=list[NodeSpecModel])
async def list_node_specs():
    """Return the static lookup of every known cloud VM node-type spec."""
    return [NodeSpecModel(**s) for s in all_specs()]


@router.get("/clusters/{cluster_id}", response_model=ClusterFullDetail)
async def cluster_detail(
    cluster_id: str,
    authed: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full detail view for a single cluster.

    Returns the latest config row (the clusters table contains one row per
    change event), node-type hardware specs from the static lookup, and
    lifetime billing aggregates joined from billing_usage.
    """
    vm = authed.viewing_data_mode
    # Latest config row for this cluster_id (within the active view mode)
    cfg_stmt = (
        select(Cluster)
        .where(Cluster.cluster_id == cluster_id)
        .where(Cluster.data_origin == vm)
        .where(Cluster.deleted_at.is_(None))
        .order_by(Cluster.change_time.desc().nullslast(), Cluster.create_time.desc().nullslast())
        .limit(1)
    )
    cluster = (await db.execute(cfg_stmt)).scalar_one_or_none()
    if cluster is None:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")

    # Lifetime billing aggregates (scoped to the same view mode)
    agg_stmt = (
        select(
            func.sum(BillingUsage.usage_quantity).label("total_usage"),
            func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price).label("total_cost"),
            func.max(BillingUsage.usage_date).label("last_usage_date"),
            func.bool_or(BillingUsage.is_photon).label("is_photon"),
            func.bool_or(BillingUsage.is_serverless).label("is_serverless"),
        )
        .join(ListPrice, _PRICE_JOIN)
        .where(BillingUsage.cluster_id == cluster_id)
        .where(BillingUsage.data_origin == vm)
        .where(BillingUsage.deleted_at.is_(None))
    )
    agg = (await db.execute(agg_stmt)).one()

    # Per-SKU breakdown
    sku_stmt = (
        select(
            BillingUsage.sku_name,
            func.sum(BillingUsage.usage_quantity).label("total_usage"),
            func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price).label("total_cost"),
        )
        .join(ListPrice, _PRICE_JOIN)
        .where(BillingUsage.cluster_id == cluster_id)
        .group_by(BillingUsage.sku_name)
        .order_by(func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price).desc())
    )
    sku_rows = (await db.execute(sku_stmt)).all()

    # Node-spec lookup + total CPU/memory across the cluster
    driver = get_spec(cluster.driver_node_type)
    worker = get_spec(cluster.worker_node_type)

    # For autoscaling clusters use the upper bound so users see max capacity
    effective_workers: Optional[int] = None
    if cluster.max_autoscale_workers is not None:
        effective_workers = cluster.max_autoscale_workers
    elif cluster.worker_count is not None:
        effective_workers = cluster.worker_count

    total_vcpus = total_memory_gb = None
    if driver is not None:
        total_vcpus = driver["vcpus"]
        total_memory_gb = driver["memory_gb"]
        if worker is not None and effective_workers is not None:
            total_vcpus += worker["vcpus"] * effective_workers
            total_memory_gb += worker["memory_gb"] * effective_workers

    return ClusterFullDetail(
        cluster_id=cluster.cluster_id,
        cluster_name=cluster.cluster_name,
        account_id=cluster.account_id,
        workspace_id=cluster.workspace_id,
        owned_by=cluster.owned_by,
        driver_node_type=cluster.driver_node_type,
        worker_node_type=cluster.worker_node_type,
        worker_count=cluster.worker_count,
        min_autoscale_workers=cluster.min_autoscale_workers,
        max_autoscale_workers=cluster.max_autoscale_workers,
        dbr_version=cluster.dbr_version,
        cluster_source=cluster.cluster_source,
        data_security_mode=cluster.data_security_mode,
        create_time=cluster.create_time,
        change_time=cluster.change_time,
        delete_time=cluster.delete_time,
        driver_spec=NodeSpecModel(**driver) if driver else None,
        worker_spec=NodeSpecModel(**worker) if worker else None,
        total_vcpus=total_vcpus,
        total_memory_gb=total_memory_gb,
        total_cost=agg.total_cost or 0,
        total_usage=agg.total_usage or 0,
        last_usage_date=agg.last_usage_date,
        is_photon_observed=bool(agg.is_photon),
        is_serverless_observed=bool(agg.is_serverless),
        sku_breakdown=[
            ClusterSkuUsage(
                sku_name=r.sku_name,
                total_usage=r.total_usage or 0,
                total_cost=r.total_cost or 0,
            )
            for r in sku_rows
        ],
    )


@router.get("/warehouses/{warehouse_id}", response_model=WarehouseFullDetail)
async def warehouse_detail(
    warehouse_id: str,
    authed: AuthedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full detail view for a single SQL warehouse.

    Returns the latest config row, t-shirt size capacity specs, and lifetime
    billing aggregates joined from billing_usage on warehouse_id.
    """
    vm = authed.viewing_data_mode
    cfg_stmt = (
        select(Warehouse)
        .where(Warehouse.warehouse_id == warehouse_id)
        .where(Warehouse.data_origin == vm)
        .where(Warehouse.deleted_at.is_(None))
        .order_by(Warehouse.change_time.desc().nullslast())
        .limit(1)
    )
    warehouse = (await db.execute(cfg_stmt)).scalar_one_or_none()
    if warehouse is None:
        raise HTTPException(status_code=404, detail=f"Warehouse {warehouse_id} not found")

    # Lifetime billing aggregates (scoped to the same view mode)
    agg_stmt = (
        select(
            func.sum(BillingUsage.usage_quantity).label("total_usage"),
            func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price).label("total_cost"),
            func.max(BillingUsage.usage_date).label("last_usage_date"),
            func.bool_or(BillingUsage.is_photon).label("is_photon"),
            func.bool_or(BillingUsage.is_serverless).label("is_serverless"),
        )
        .join(ListPrice, _PRICE_JOIN)
        .where(BillingUsage.warehouse_id == warehouse_id)
        .where(BillingUsage.data_origin == vm)
        .where(BillingUsage.deleted_at.is_(None))
    )
    agg = (await db.execute(agg_stmt)).one()

    # Per-SKU breakdown
    sku_stmt = (
        select(
            BillingUsage.sku_name,
            func.sum(BillingUsage.usage_quantity).label("total_usage"),
            func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price).label("total_cost"),
        )
        .join(ListPrice, _PRICE_JOIN)
        .where(BillingUsage.warehouse_id == warehouse_id)
        .group_by(BillingUsage.sku_name)
        .order_by(func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price).desc())
    )
    sku_rows = (await db.execute(sku_stmt)).all()

    # T-shirt size lookup + peak DBU/hr at max scale
    spec = get_size_spec(warehouse.warehouse_size)
    max_dbu_per_hour: Optional[int] = None
    if spec is not None:
        scale = warehouse.max_clusters or 1
        max_dbu_per_hour = spec["max_dbu_per_hour"] * scale

    return WarehouseFullDetail(
        warehouse_id=warehouse.warehouse_id,
        warehouse_name=warehouse.warehouse_name,
        account_id=warehouse.account_id,
        workspace_id=warehouse.workspace_id,
        warehouse_type=warehouse.warehouse_type,
        warehouse_size=warehouse.warehouse_size,
        min_clusters=warehouse.min_clusters,
        max_clusters=warehouse.max_clusters,
        auto_stop_minutes=warehouse.auto_stop_minutes,
        created_by=warehouse.created_by,
        change_time=warehouse.change_time,
        delete_time=warehouse.delete_time,
        size_spec=WarehouseSizeSpecModel(**spec) if spec else None,
        max_dbu_per_hour=max_dbu_per_hour,
        total_cost=agg.total_cost or 0,
        total_usage=agg.total_usage or 0,
        last_usage_date=agg.last_usage_date,
        is_photon_observed=bool(agg.is_photon),
        is_serverless_observed=bool(agg.is_serverless),
        sku_breakdown=[
            WarehouseSkuUsage(
                sku_name=r.sku_name,
                total_usage=r.total_usage or 0,
                total_cost=r.total_cost or 0,
            )
            for r in sku_rows
        ],
    )


@router.get("/cluster-cost", response_model=ComputeCostResponse)
async def cluster_cost(
    cluster_id: str = Query(..., description="Cluster ID"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Total usage and cost for a specific cluster within a date range."""
    stmt = (
        select(
            func.sum(BillingUsage.usage_quantity).label("total_usage"),
            func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price).label(
                "total_cost"
            ),
        )
        .join(ListPrice, _PRICE_JOIN)
        .where(BillingUsage.cluster_id == cluster_id)
    )
    if start_date:
        stmt = stmt.where(BillingUsage.usage_date >= start_date)
    if end_date:
        stmt = stmt.where(BillingUsage.usage_date <= end_date)
    result = await db.execute(stmt)
    row = result.one()
    return ComputeCostResponse(
        resource_id=cluster_id,
        total_usage=row.total_usage or 0,
        total_cost=row.total_cost or 0,
        start_date=start_date or date(2000, 1, 1),
        end_date=end_date or date(2099, 12, 31),
    )


@router.get("/warehouse-cost", response_model=ComputeCostResponse)
async def warehouse_cost(
    warehouse_id: str = Query(..., description="Warehouse ID"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Total usage and cost for a specific SQL warehouse within a date range."""
    stmt = (
        select(
            func.sum(BillingUsage.usage_quantity).label("total_usage"),
            func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price).label(
                "total_cost"
            ),
        )
        .join(ListPrice, _PRICE_JOIN)
        .where(BillingUsage.warehouse_id == warehouse_id)
    )
    if start_date:
        stmt = stmt.where(BillingUsage.usage_date >= start_date)
    if end_date:
        stmt = stmt.where(BillingUsage.usage_date <= end_date)
    result = await db.execute(stmt)
    row = result.one()
    return ComputeCostResponse(
        resource_id=warehouse_id,
        total_usage=row.total_usage or 0,
        total_cost=row.total_cost or 0,
        start_date=start_date or date(2000, 1, 1),
        end_date=end_date or date(2099, 12, 31),
    )
