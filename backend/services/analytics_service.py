"""Business logic for analytics endpoints (anomaly detection, forecasting, growth).

Uses pre-calculated usage_usd when available (real data), falls back to price join (seed data).
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import BillingUsage, ListPrice
from rbac_filters import apply_billing_filters

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


async def _daily_costs(
    session: AsyncSession,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    filters: Optional[dict[str, Any]] = None,
    view_mode: Optional[str] = None,
) -> list[tuple[date, Decimal]]:
    """Return (usage_date, total_cost) ordered by date."""
    has_usd = await _has_usage_usd(session)

    if has_usd:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_usd), 0)
        stmt = (
            select(BillingUsage.usage_date, cost_expr.label("total_cost"))
            .group_by(BillingUsage.usage_date)
            .order_by(BillingUsage.usage_date)
        )
    else:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price), 0)
        stmt = (
            select(BillingUsage.usage_date, cost_expr.label("total_cost"))
            .join(ListPrice, _PRICE_JOIN)
            .group_by(BillingUsage.usage_date)
            .order_by(BillingUsage.usage_date)
        )

    if start_date:
        stmt = stmt.where(BillingUsage.usage_date >= start_date)
    if end_date:
        stmt = stmt.where(BillingUsage.usage_date <= end_date)
    stmt = apply_billing_filters(stmt, filters, view_mode=view_mode)
    result = await session.execute(stmt)
    return [(row.usage_date, row.total_cost) for row in result.all()]


async def detect_anomalies(
    session: AsyncSession,
    window: int = 30,
    threshold: float = 2.0,
    filters: Optional[dict[str, Any]] = None,
    view_mode: Optional[str] = None,
) -> list[dict]:
    """Detect days where cost exceeds *threshold* standard deviations from the rolling average."""
    rows = await _daily_costs(session, filters=filters, view_mode=view_mode)
    if len(rows) < window:
        return []

    dates = [r[0] for r in rows]
    costs = np.array([float(r[1]) for r in rows], dtype=np.float64)

    anomalies: list[dict] = []
    for i in range(window, len(costs)):
        window_slice = costs[i - window : i]
        mean = float(np.mean(window_slice))
        std = float(np.std(window_slice))
        if std == 0:
            continue
        z = (costs[i] - mean) / std
        if abs(z) >= threshold:
            anomalies.append(
                {
                    "usage_date": dates[i],
                    "actual_cost": Decimal(str(round(costs[i], 2))),
                    "expected_cost": Decimal(str(round(mean, 2))),
                    "std_dev": Decimal(str(round(std, 2))),
                    "z_score": round(z, 3),
                }
            )
    return anomalies


async def forecast_costs(
    session: AsyncSession,
    history_days: int = 90,
    forecast_days: int = 30,
    filters: Optional[dict[str, Any]] = None,
    view_mode: Optional[str] = None,
) -> list[dict]:
    """Simple linear-trend forecast based on the last *history_days* of data."""
    end = date.today()
    start = end - timedelta(days=history_days)
    rows = await _daily_costs(session, start_date=start, end_date=end, filters=filters, view_mode=view_mode)
    if len(rows) < 2:
        return []

    x = np.arange(len(rows), dtype=np.float64)
    y = np.array([float(r[1]) for r in rows], dtype=np.float64)
    coeffs = np.polyfit(x, y, 1)
    slope, intercept = coeffs

    last_date = rows[-1][0]
    forecasts: list[dict] = []
    for day_offset in range(1, forecast_days + 1):
        x_val = len(rows) - 1 + day_offset
        predicted = slope * x_val + intercept
        predicted = max(predicted, 0)
        forecasts.append(
            {
                "forecast_date": last_date + timedelta(days=day_offset),
                "forecasted_cost": Decimal(str(round(predicted, 2))),
            }
        )
    return forecasts


async def month_over_month_growth(
    session: AsyncSession,
    filters: Optional[dict[str, Any]] = None,
    view_mode: Optional[str] = None,
) -> list[dict]:
    """Calculate month-over-month cost growth rates."""
    has_usd = await _has_usage_usd(session)
    month_expr = func.to_char(BillingUsage.usage_date, "YYYY-MM")

    if has_usd:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_usd), 0)
        stmt = (
            select(month_expr.label("month"), cost_expr.label("total_cost"))
            .group_by(month_expr)
            .order_by(month_expr)
        )
    else:
        cost_expr = func.coalesce(func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price), 0)
        stmt = (
            select(month_expr.label("month"), cost_expr.label("total_cost"))
            .join(ListPrice, _PRICE_JOIN)
            .group_by(month_expr)
            .order_by(month_expr)
        )

    stmt = apply_billing_filters(stmt, filters, view_mode=view_mode)
    result = await session.execute(stmt)
    rows = result.all()

    growth: list[dict] = []
    for i, row in enumerate(rows):
        prior = rows[i - 1].total_cost if i > 0 else None
        pct = None
        if prior and float(prior) != 0:
            pct = round((float(row.total_cost) - float(prior)) / float(prior) * 100, 2)
        growth.append(
            {
                "month": row.month,
                "total_cost": row.total_cost,
                "prior_month_cost": prior,
                "growth_pct": pct,
            }
        )
    return growth
