"""Billing usage endpoints.

Cost calculation strategy:
  - If usage_usd is populated (real Databricks extraction), use it directly.
    This column is pre-calculated using Databricks' own formula:
    COALESCE(usage_quantity * pricing.effective_list.default, 0)
  - If usage_usd is NULL (seed/demo data), fall back to joining list_prices.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import AuthedUser, get_current_user
from database import get_db
from models import BillingUsage, Cluster, ListPrice, Warehouse
from rbac_filters import apply_billing_filters, resolve_effective_filters
from schemas import (
    BreakdownResponse,
    DailyTrendResponse,
    SkuUserCostItem,
    SkuUserMatrixResponse,
    TopSkuResponse,
    UsageSummaryBySkuItem,
    UsageSummaryBySkuResponse,
    UsageSummaryResponse,
    UserCostResponse,
    UserResourceUsage,
    UserSkuUsage,
    UserUtilizationResponse,
)

router = APIRouter(
    prefix="/api/billing",
    tags=["billing"],
    dependencies=[Depends(get_current_user)],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Price join for fallback when usage_usd is not available (seed data).
# Matches Databricks reference: sku_name + usage_unit + time range.
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

# Cost expression: prefer pre-calculated usage_usd, fall back to price join
_COST_EXPR = func.coalesce(
    func.sum(BillingUsage.usage_usd),
    func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price),
    0,
)
_USAGE_EXPR = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)


async def _has_usage_usd(session: AsyncSession) -> bool:
    """Check if the data has pre-calculated usage_usd (real Databricks data)."""
    result = await session.execute(
        select(func.count()).select_from(BillingUsage).where(BillingUsage.usage_usd.isnot(None)).limit(1)
    )
    return (result.scalar() or 0) > 0


def _date_filters(stmt, start_date: Optional[date], end_date: Optional[date]):
    if start_date:
        stmt = stmt.where(BillingUsage.usage_date >= start_date)
    if end_date:
        stmt = stmt.where(BillingUsage.usage_date <= end_date)
    return stmt


def _cost_query(select_cols, group_col=None, has_usd: bool = False):
    """Build a cost query using either usage_usd or price join."""
    if has_usd:
        # Real data: use pre-calculated usage_usd directly, no join needed
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_usd), 0)
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        stmt = select(*select_cols, usage_expr.label("total_usage"), cost_expr.label("total_cost"))
        if group_col is not None:
            stmt = stmt.group_by(group_col).order_by(cost_expr.desc())
        return stmt
    else:
        # Seed data: join with list_prices
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price), 0)
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        stmt = (
            select(*select_cols, usage_expr.label("total_usage"), cost_expr.label("total_cost"))
            .join(ListPrice, _PRICE_JOIN)
        )
        if group_col is not None:
            stmt = stmt.group_by(group_col).order_by(cost_expr.desc())
        return stmt


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/usage-summary", response_model=UsageSummaryResponse)
async def usage_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    group_by: str = Query("day", regex="^(day|week|month)$"),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Aggregated usage quantity and estimated cost grouped by time period."""
    has_usd = await _has_usage_usd(db)

    if group_by == "day":
        period_expr = func.to_char(BillingUsage.usage_date, "YYYY-MM-DD")
    elif group_by == "week":
        period_expr = func.to_char(func.date_trunc("week", BillingUsage.usage_date), "YYYY-MM-DD")
    else:
        period_expr = func.to_char(BillingUsage.usage_date, "YYYY-MM")

    if has_usd:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_usd), 0)
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        stmt = (
            select(period_expr.label("period"), usage_expr.label("total_usage"), cost_expr.label("total_cost"))
            .group_by(period_expr)
            .order_by(period_expr)
        )
    else:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price), 0)
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        stmt = (
            select(period_expr.label("period"), usage_expr.label("total_usage"), cost_expr.label("total_cost"))
            .join(ListPrice, _PRICE_JOIN)
            .group_by(period_expr)
            .order_by(period_expr)
        )

    stmt = _date_filters(stmt, start_date, end_date)
    stmt = apply_billing_filters(stmt, resolve_effective_filters(authed), view_mode=authed.viewing_data_mode)
    result = await db.execute(stmt)
    return UsageSummaryResponse(
        data=[
            {"period": r.period, "total_usage": r.total_usage, "total_cost": r.total_cost}
            for r in result.all()
        ]
    )


@router.get("/usage-summary-by-sku", response_model=UsageSummaryBySkuResponse)
async def usage_summary_by_sku(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    group_by: str = Query("day", regex="^(day|week|month)$"),
    top_skus: int = Query(5, ge=1, le=20, description="Number of top-cost SKUs to include"),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Per-period per-SKU usage and cost, restricted to the top-N SKUs by total cost.

    Used to overlay per-SKU cost-per-DBU curves on the aggregate trend chart.
    Long-form rows; the consumer pivots into wide-form for charting.
    """
    has_usd = await _has_usage_usd(db)

    if group_by == "day":
        period_expr = func.to_char(BillingUsage.usage_date, "YYYY-MM-DD")
    elif group_by == "week":
        period_expr = func.to_char(func.date_trunc("week", BillingUsage.usage_date), "YYYY-MM-DD")
    else:
        period_expr = func.to_char(BillingUsage.usage_date, "YYYY-MM")

    if has_usd:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_usd), 0)
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        from_clause = lambda s: s
    else:
        cost_expr = func.coalesce(
            func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price), 0
        )
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        from_clause = lambda s: s.join(ListPrice, _PRICE_JOIN)

    eff = resolve_effective_filters(authed)

    # Top-N SKUs by total cost across the whole window
    top_stmt = apply_billing_filters(_date_filters(
        from_clause(
            select(
                BillingUsage.sku_name.label("sku_name"),
                cost_expr.label("total_cost"),
            )
        )
        .group_by(BillingUsage.sku_name)
        .order_by(cost_expr.desc())
        .limit(top_skus),
        start_date,
        end_date,
    ), eff, view_mode=authed.viewing_data_mode)
    top_sku_names = [r.sku_name for r in (await db.execute(top_stmt)).all()]

    if not top_sku_names:
        return UsageSummaryBySkuResponse(skus=[], data=[])

    # Per-period per-SKU breakdown for those SKUs
    detail_stmt = apply_billing_filters(_date_filters(
        from_clause(
            select(
                period_expr.label("period"),
                BillingUsage.sku_name.label("sku_name"),
                usage_expr.label("total_usage"),
                cost_expr.label("total_cost"),
            )
        )
        .where(BillingUsage.sku_name.in_(top_sku_names))
        .group_by(period_expr, BillingUsage.sku_name)
        .order_by(period_expr, BillingUsage.sku_name),
        start_date,
        end_date,
    ), eff, view_mode=authed.viewing_data_mode)
    rows = (await db.execute(detail_stmt)).all()

    return UsageSummaryBySkuResponse(
        skus=top_sku_names,
        data=[
            UsageSummaryBySkuItem(
                period=r.period,
                sku_name=r.sku_name,
                total_usage=r.total_usage or 0,
                total_cost=r.total_cost or 0,
            )
            for r in rows
        ],
    )


async def _breakdown(
    session: AsyncSession,
    group_col,
    start_date: Optional[date],
    end_date: Optional[date],
    authed: Optional[AuthedUser] = None,
) -> BreakdownResponse:
    has_usd = await _has_usage_usd(session)
    stmt = _cost_query([group_col.label("label")], group_col, has_usd=has_usd)
    stmt = _date_filters(stmt, start_date, end_date)
    if authed is not None:
        stmt = apply_billing_filters(stmt, resolve_effective_filters(authed), view_mode=authed.viewing_data_mode)
    result = await session.execute(stmt)
    return BreakdownResponse(
        data=[
            {"label": str(r.label), "total_usage": r.total_usage, "total_cost": r.total_cost}
            for r in result.all()
        ]
    )


@router.get("/by-sku", response_model=BreakdownResponse)
async def by_sku(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Usage and cost broken down by SKU name."""
    return await _breakdown(db, BillingUsage.sku_name, start_date, end_date, authed=authed)


@router.get("/by-workspace", response_model=BreakdownResponse)
async def by_workspace(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Usage and cost broken down by workspace ID."""
    return await _breakdown(db, BillingUsage.workspace_id, start_date, end_date, authed=authed)


@router.get("/by-origin", response_model=BreakdownResponse)
async def by_origin(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Usage and cost broken down by billing origin product."""
    return await _breakdown(db, BillingUsage.billing_origin_product, start_date, end_date, authed=authed)


@router.get("/by-usage-type", response_model=BreakdownResponse)
async def by_usage_type(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Usage and cost broken down by usage type."""
    return await _breakdown(db, BillingUsage.usage_type, start_date, end_date, authed=authed)


@router.get("/by-cloud", response_model=BreakdownResponse)
async def by_cloud(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Usage and cost broken down by cloud provider."""
    return await _breakdown(db, BillingUsage.cloud, start_date, end_date, authed=authed)


@router.get("/by-user", response_model=UserCostResponse)
async def by_user(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Top users ranked by total cost (from run_as identity)."""
    has_usd = await _has_usage_usd(db)

    if has_usd:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_usd), 0)
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        stmt = (
            select(BillingUsage.run_as.label("user"), usage_expr.label("total_usage"), cost_expr.label("total_cost"))
            .where(BillingUsage.run_as.isnot(None))
            .group_by(BillingUsage.run_as)
            .order_by(cost_expr.desc())
            .limit(limit)
        )
    else:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price), 0)
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        stmt = (
            select(BillingUsage.run_as.label("user"), usage_expr.label("total_usage"), cost_expr.label("total_cost"))
            .join(ListPrice, _PRICE_JOIN)
            .where(BillingUsage.run_as.isnot(None))
            .group_by(BillingUsage.run_as)
            .order_by(cost_expr.desc())
            .limit(limit)
        )

    stmt = apply_billing_filters(_date_filters(stmt, start_date, end_date), resolve_effective_filters(authed), view_mode=authed.viewing_data_mode)
    result = await db.execute(stmt)
    return UserCostResponse(
        data=[
            {"user": r.user, "total_usage": r.total_usage, "total_cost": r.total_cost}
            for r in result.all()
        ]
    )


@router.get("/daily-trend", response_model=DailyTrendResponse)
async def daily_trend(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sku_name: Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None),
    run_as: Optional[str] = Query(None, description="Filter by run_as user identity"),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Daily usage and cost with optional SKU / workspace / user filtering."""
    has_usd = await _has_usage_usd(db)

    if has_usd:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_usd), 0)
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        stmt = (
            select(BillingUsage.usage_date, usage_expr.label("total_usage"), cost_expr.label("total_cost"))
            .group_by(BillingUsage.usage_date)
            .order_by(BillingUsage.usage_date)
        )
    else:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price), 0)
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        stmt = (
            select(BillingUsage.usage_date, usage_expr.label("total_usage"), cost_expr.label("total_cost"))
            .join(ListPrice, _PRICE_JOIN)
            .group_by(BillingUsage.usage_date)
            .order_by(BillingUsage.usage_date)
        )

    stmt = _date_filters(stmt, start_date, end_date)
    if sku_name:
        stmt = stmt.where(BillingUsage.sku_name == sku_name)
    if workspace_id:
        stmt = stmt.where(BillingUsage.workspace_id == workspace_id)
    if run_as:
        stmt = stmt.where(BillingUsage.run_as == run_as)
    stmt = apply_billing_filters(stmt, resolve_effective_filters(authed), view_mode=authed.viewing_data_mode)
    result = await db.execute(stmt)
    return DailyTrendResponse(
        data=[
            {"usage_date": r.usage_date, "total_usage": r.total_usage, "total_cost": r.total_cost}
            for r in result.all()
        ]
    )


@router.get("/user-utilization", response_model=UserUtilizationResponse)
async def user_utilization(
    run_as: str = Query(..., description="The run_as identity to pivot on"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """All spend attributed to a single user, broken down by SKU, cluster, and warehouse.

    Cluster and warehouse names are resolved to the most recent config row
    (DISTINCT ON change_time/create_time) so renames don't multiply rows.
    """
    has_usd = await _has_usage_usd(db)

    if has_usd:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_usd), 0)
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        from_clause = lambda s: s
    else:
        cost_expr = func.coalesce(
            func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price), 0
        )
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        from_clause = lambda s: s.join(ListPrice, _PRICE_JOIN)

    eff = resolve_effective_filters(authed)
    base_filter = lambda s: apply_billing_filters(
        _date_filters(s, start_date, end_date).where(BillingUsage.run_as == run_as), eff,
        view_mode=authed.viewing_data_mode,
    )

    # Lifetime totals for the user (in the chosen window)
    totals_stmt = base_filter(
        from_clause(select(usage_expr.label("total_usage"), cost_expr.label("total_cost")))
    )
    totals = (await db.execute(totals_stmt)).one()

    # SKU breakdown
    sku_stmt = base_filter(
        from_clause(
            select(
                BillingUsage.sku_name.label("sku_name"),
                usage_expr.label("total_usage"),
                cost_expr.label("total_cost"),
            )
        )
        .group_by(BillingUsage.sku_name)
        .order_by(cost_expr.desc())
    )
    sku_rows = (await db.execute(sku_stmt)).all()

    # Cluster breakdown — group by cluster_id, then resolve latest cluster_name
    cluster_latest = (
        select(
            Cluster.cluster_id,
            Cluster.cluster_name,
        )
        .distinct(Cluster.cluster_id)
        .order_by(
            Cluster.cluster_id,
            Cluster.change_time.desc().nullslast(),
            Cluster.create_time.desc().nullslast(),
        )
        .subquery()
    )
    cluster_stmt = base_filter(
        from_clause(
            select(
                BillingUsage.cluster_id.label("resource_id"),
                cluster_latest.c.cluster_name.label("resource_name"),
                usage_expr.label("total_usage"),
                cost_expr.label("total_cost"),
            )
        )
        .where(BillingUsage.cluster_id.isnot(None))
        .outerjoin(cluster_latest, cluster_latest.c.cluster_id == BillingUsage.cluster_id)
        .group_by(BillingUsage.cluster_id, cluster_latest.c.cluster_name)
        .order_by(cost_expr.desc())
    )
    cluster_rows = (await db.execute(cluster_stmt)).all()

    # Warehouse breakdown.
    #
    # Databricks' system.billing.usage rarely populates identity_metadata.run_as
    # for SQL warehouse rows, so filtering by BillingUsage.run_as = user yields
    # nothing. We instead attribute warehouses by ownership (Warehouse.created_by)
    # and aggregate all billing on those warehouses in the date window. The
    # semantics shift from "warehouses the user ran on" to "warehouses the user
    # owns" — which is the actionable question for cost allocation.
    warehouse_owned = (
        select(
            Warehouse.warehouse_id,
            Warehouse.warehouse_name,
        )
        .distinct(Warehouse.warehouse_id)
        .where(Warehouse.created_by == run_as)
        .order_by(
            Warehouse.warehouse_id,
            Warehouse.change_time.desc().nullslast(),
        )
        .subquery()
    )
    warehouse_stmt = (
        apply_billing_filters(_date_filters(
            from_clause(
                select(
                    warehouse_owned.c.warehouse_id.label("resource_id"),
                    warehouse_owned.c.warehouse_name.label("resource_name"),
                    usage_expr.label("total_usage"),
                    cost_expr.label("total_cost"),
                )
                .select_from(warehouse_owned)
                .join(BillingUsage, BillingUsage.warehouse_id == warehouse_owned.c.warehouse_id)
            ),
            start_date,
            end_date,
        ), eff, view_mode=authed.viewing_data_mode)
        .group_by(warehouse_owned.c.warehouse_id, warehouse_owned.c.warehouse_name)
        .order_by(cost_expr.desc())
    )
    warehouse_rows = (await db.execute(warehouse_stmt)).all()

    return UserUtilizationResponse(
        user=run_as,
        total_usage=totals.total_usage or 0,
        total_cost=totals.total_cost or 0,
        skus=[
            UserSkuUsage(
                sku_name=r.sku_name,
                total_usage=r.total_usage or 0,
                total_cost=r.total_cost or 0,
            )
            for r in sku_rows
        ],
        clusters=[
            UserResourceUsage(
                resource_id=r.resource_id,
                resource_name=r.resource_name,
                total_usage=r.total_usage or 0,
                total_cost=r.total_cost or 0,
            )
            for r in cluster_rows
        ],
        warehouses=[
            UserResourceUsage(
                resource_id=r.resource_id,
                resource_name=r.resource_name,
                total_usage=r.total_usage or 0,
                total_cost=r.total_cost or 0,
            )
            for r in warehouse_rows
        ],
    )


@router.get("/by-sku-user", response_model=SkuUserMatrixResponse)
async def by_sku_user(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    top_skus: int = Query(10, ge=1, le=50, description="Number of top-cost SKUs to include"),
    top_users: int = Query(10, ge=1, le=50, description="Number of top-cost users to include"),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Cost breakdown across top-N SKUs x top-N users for a date range.

    The response gives both ordered axis lists (SKUs and users sorted by their
    respective lifetime cost in the period) and a sparse list of populated
    (sku_name, run_as) cells. Pairs with zero cost are omitted, so the
    consumer can render unpopulated cells as empty.
    """
    has_usd = await _has_usage_usd(db)

    eff = resolve_effective_filters(authed)

    def _cost(stmt_):
        return apply_billing_filters(
            _date_filters(stmt_, start_date, end_date).where(BillingUsage.run_as.isnot(None)), eff,
            view_mode=authed.viewing_data_mode,
        )

    if has_usd:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_usd), 0)
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        from_clause = lambda s: s
    else:
        cost_expr = func.coalesce(
            func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price), 0
        )
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        from_clause = lambda s: s.join(ListPrice, _PRICE_JOIN)

    # Top N SKUs by cost in the period (filtered to rows with a user attached)
    sku_stmt = _cost(
        from_clause(
            select(
                BillingUsage.sku_name.label("sku_name"),
                cost_expr.label("total_cost"),
            )
        )
        .group_by(BillingUsage.sku_name)
        .order_by(cost_expr.desc())
        .limit(top_skus)
    )
    skus = [r.sku_name for r in (await db.execute(sku_stmt)).all()]

    # Top N users by cost in the same period
    user_stmt = _cost(
        from_clause(
            select(
                BillingUsage.run_as.label("run_as"),
                cost_expr.label("total_cost"),
            )
        )
        .group_by(BillingUsage.run_as)
        .order_by(cost_expr.desc())
        .limit(top_users)
    )
    users = [r.run_as for r in (await db.execute(user_stmt)).all()]

    if not skus or not users:
        return SkuUserMatrixResponse(skus=skus, users=users, cells=[])

    # Cells for the cross-product (sku in top, user in top)
    cells_stmt = _cost(
        from_clause(
            select(
                BillingUsage.sku_name.label("sku_name"),
                BillingUsage.run_as.label("run_as"),
                usage_expr.label("total_usage"),
                cost_expr.label("total_cost"),
            )
        )
        .where(BillingUsage.sku_name.in_(skus))
        .where(BillingUsage.run_as.in_(users))
        .group_by(BillingUsage.sku_name, BillingUsage.run_as)
    )
    cells = [
        SkuUserCostItem(
            sku_name=r.sku_name,
            run_as=r.run_as,
            total_usage=r.total_usage or 0,
            total_cost=r.total_cost or 0,
        )
        for r in (await db.execute(cells_stmt)).all()
        if (r.total_cost or 0) > 0
    ]
    return SkuUserMatrixResponse(skus=skus, users=users, cells=cells)


@router.get("/top-skus", response_model=TopSkuResponse)
async def top_skus(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Top SKUs ranked by total estimated cost."""
    has_usd = await _has_usage_usd(db)
    stmt = _cost_query([BillingUsage.sku_name], BillingUsage.sku_name, has_usd=has_usd)
    stmt = apply_billing_filters(_date_filters(stmt, start_date, end_date), resolve_effective_filters(authed), view_mode=authed.viewing_data_mode).limit(limit)
    result = await db.execute(stmt)
    return TopSkuResponse(
        data=[
            {"sku_name": r.sku_name, "total_usage": r.total_usage, "total_cost": r.total_cost, "rank": idx}
            for idx, r in enumerate(result.all(), start=1)
        ]
    )
