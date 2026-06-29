"""Analytics endpoints: anomalies, forecasting, growth, utilization, KPIs.

Uses pre-calculated usage_usd when available (real data), falls back to price join (seed data).
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import AuthedUser, get_current_user
from database import get_db
from models import BillingUsage, ListPrice
from rbac_filters import apply_billing_filters, resolve_effective_filters
from schemas import (
    CostAnomalyResponse,
    CostMatrixResponse,
    ForecastResponse,
    KPISummary,
    MoMGrowthResponse,
    UtilizationSummaryResponse,
)
from services.analytics_service import detect_anomalies, forecast_costs, month_over_month_growth

router = APIRouter(
    prefix="/api/analytics",
    tags=["analytics"],
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


async def _has_usage_usd(session: AsyncSession) -> bool:
    result = await session.execute(
        select(func.count()).select_from(BillingUsage).where(BillingUsage.usage_usd.isnot(None)).limit(1)
    )
    return (result.scalar() or 0) > 0


@router.get("/cost-anomalies", response_model=CostAnomalyResponse)
async def cost_anomalies(
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Detect days where cost exceeds 2 standard deviations from the 30-day rolling average."""
    items = await detect_anomalies(db, window=30, threshold=2.0, filters=resolve_effective_filters(authed), view_mode=authed.viewing_data_mode)
    return CostAnomalyResponse(data=items)


@router.get("/forecast", response_model=ForecastResponse)
async def forecast(
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Simple linear-trend forecast for the next 30 days based on the last 90 days."""
    items = await forecast_costs(db, history_days=90, forecast_days=30, filters=resolve_effective_filters(authed), view_mode=authed.viewing_data_mode)
    return ForecastResponse(data=items)


@router.get("/mom-growth", response_model=MoMGrowthResponse)
async def mom_growth(
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Month-over-month growth rates for total cost."""
    items = await month_over_month_growth(db, filters=resolve_effective_filters(authed), view_mode=authed.viewing_data_mode)
    return MoMGrowthResponse(data=items)


@router.get("/cost-breakdown-matrix", response_model=CostMatrixResponse)
async def cost_breakdown_matrix(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Cost matrix of workspace (rows) x billing_origin (columns) for a heatmap."""
    has_usd = await _has_usage_usd(db)

    if has_usd:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_usd), 0)
        stmt = (
            select(
                BillingUsage.workspace_id,
                BillingUsage.billing_origin_product.label("billing_origin"),
                cost_expr.label("total_cost"),
            )
            .group_by(BillingUsage.workspace_id, BillingUsage.billing_origin_product)
            .order_by(BillingUsage.workspace_id, BillingUsage.billing_origin_product)
        )
    else:
        cost_expr = func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price)
        stmt = (
            select(
                BillingUsage.workspace_id,
                BillingUsage.billing_origin_product.label("billing_origin"),
                cost_expr.label("total_cost"),
            )
            .join(ListPrice, _PRICE_JOIN)
            .group_by(BillingUsage.workspace_id, BillingUsage.billing_origin_product)
            .order_by(BillingUsage.workspace_id, BillingUsage.billing_origin_product)
        )

    if start_date:
        stmt = stmt.where(BillingUsage.usage_date >= start_date)
    if end_date:
        stmt = stmt.where(BillingUsage.usage_date <= end_date)
    stmt = apply_billing_filters(stmt, resolve_effective_filters(authed), view_mode=authed.viewing_data_mode)

    result = await db.execute(stmt)
    rows = result.all()

    workspaces = sorted({r.workspace_id for r in rows})
    origins = sorted({r.billing_origin for r in rows})
    cells = [
        {"workspace_id": r.workspace_id, "billing_origin": r.billing_origin, "total_cost": r.total_cost}
        for r in rows
    ]
    return CostMatrixResponse(workspaces=workspaces, billing_origins=origins, cells=cells)


@router.get("/utilization-summary", response_model=UtilizationSummaryResponse)
async def utilization_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Compute utilization metrics per workspace: avg DBU/day, peak DBU/day, total cost."""
    has_usd = await _has_usage_usd(db)

    if has_usd:
        sub = (
            select(
                BillingUsage.workspace_id,
                BillingUsage.usage_date,
                func.sum(BillingUsage.usage_quantity).label("daily_usage"),
                func.coalesce(func.sum(BillingUsage.usage_usd), 0).label("daily_cost"),
            )
            .group_by(BillingUsage.workspace_id, BillingUsage.usage_date)
        )
    else:
        sub = (
            select(
                BillingUsage.workspace_id,
                BillingUsage.usage_date,
                func.sum(BillingUsage.usage_quantity).label("daily_usage"),
                func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price).label("daily_cost"),
            )
            .join(ListPrice, _PRICE_JOIN)
            .group_by(BillingUsage.workspace_id, BillingUsage.usage_date)
        )

    if start_date:
        sub = sub.where(BillingUsage.usage_date >= start_date)
    if end_date:
        sub = sub.where(BillingUsage.usage_date <= end_date)
    sub = apply_billing_filters(sub, resolve_effective_filters(authed), view_mode=authed.viewing_data_mode)
    sub = sub.subquery()

    stmt = select(
        sub.c.workspace_id,
        func.avg(sub.c.daily_usage).label("avg_dbu_per_day"),
        func.max(sub.c.daily_usage).label("peak_dbu_per_day"),
        func.sum(sub.c.daily_cost).label("total_cost"),
    ).group_by(sub.c.workspace_id)

    result = await db.execute(stmt)
    return UtilizationSummaryResponse(
        data=[
            {
                "workspace_id": r.workspace_id,
                "avg_dbu_per_day": round(r.avg_dbu_per_day, 2),
                "peak_dbu_per_day": r.peak_dbu_per_day,
                "total_cost": r.total_cost,
            }
            for r in result.all()
        ]
    )


@router.get("/kpi-summary", response_model=KPISummary)
async def kpi_summary(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    """Key performance indicators for the selected period."""
    has_usd = await _has_usage_usd(db)

    if has_usd:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_usd), 0)
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        stmt = (
            select(
                cost_expr.label("total_cost"),
                usage_expr.label("total_dbus"),
                func.count(func.distinct(BillingUsage.workspace_id)).label("active_workspaces"),
                func.count(func.distinct(BillingUsage.sku_name)).label("active_skus"),
            )
            .where(BillingUsage.usage_date >= start_date)
            .where(BillingUsage.usage_date <= end_date)
        )
    else:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price), 0)
        usage_expr = func.coalesce(func.sum(BillingUsage.usage_quantity), 0)
        stmt = (
            select(
                cost_expr.label("total_cost"),
                usage_expr.label("total_dbus"),
                func.count(func.distinct(BillingUsage.workspace_id)).label("active_workspaces"),
                func.count(func.distinct(BillingUsage.sku_name)).label("active_skus"),
            )
            .join(ListPrice, _PRICE_JOIN)
            .where(BillingUsage.usage_date >= start_date)
            .where(BillingUsage.usage_date <= end_date)
        )

    eff = resolve_effective_filters(authed)
    stmt = apply_billing_filters(stmt, eff, view_mode=authed.viewing_data_mode)
    result = await db.execute(stmt)
    row = result.one()

    total_cost = row.total_cost or Decimal("0")
    total_dbus = row.total_dbus or Decimal("0")
    num_days = max((end_date - start_date).days, 1)
    avg_daily = total_cost / num_days

    # Prior period of equal length
    period_length = end_date - start_date
    prior_end = start_date - timedelta(days=1)
    prior_start = prior_end - period_length

    if has_usd:
        prior_cost_expr = func.coalesce(func.sum(BillingUsage.usage_usd), 0)
        prior_stmt = (
            select(prior_cost_expr.label("total_cost"))
            .where(BillingUsage.usage_date >= prior_start)
            .where(BillingUsage.usage_date <= prior_end)
        )
    else:
        prior_cost_expr = func.coalesce(func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price), 0)
        prior_stmt = (
            select(prior_cost_expr.label("total_cost"))
            .join(ListPrice, _PRICE_JOIN)
            .where(BillingUsage.usage_date >= prior_start)
            .where(BillingUsage.usage_date <= prior_end)
        )

    prior_stmt = apply_billing_filters(prior_stmt, eff, view_mode=authed.viewing_data_mode)
    prior_result = await db.execute(prior_stmt)
    prior_row = prior_result.one()
    prior_cost = prior_row.total_cost or Decimal("0")

    cost_trend_pct = None
    if prior_cost and float(prior_cost) != 0:
        cost_trend_pct = round(
            (float(total_cost) - float(prior_cost)) / float(prior_cost) * 100, 2
        )

    return KPISummary(
        total_cost=total_cost,
        total_dbus=total_dbus,
        avg_daily_cost=round(avg_daily, 2),
        active_workspaces=row.active_workspaces,
        active_skus=row.active_skus,
        cost_trend_pct=cost_trend_pct,
    )
