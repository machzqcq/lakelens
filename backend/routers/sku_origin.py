"""SKU & Billing-Origin analytics endpoints.

Pivots cost on the two natural primary dimensions of `billing_usage`:
sku_name and billing_origin_product. Everything goes through the same
RBAC data-scope filter as the rest of the billing API.

Cost expression mirrors analytics.py: prefer pre-calculated usage_usd,
fall back to (usage_quantity * effective_list_price).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_utils import AuthedUser, get_current_user
from database import get_db
from models import BillingUsage, Cluster, Job, ListPrice, Warehouse
from rbac_filters import apply_billing_filters, resolve_effective_filters
from schemas import (
    ConcentrationResponse,
    ConcentrationRow,
    DrillOwnerItem,
    DrillResponse,
    DrillTopItem,
    OriginLeaderboardItem,
    OriginLeaderboardResponse,
    PivotCell,
    PivotResponse,
    ServerlessShareItem,
    ServerlessShareResponse,
    SkuLeaderboardItem,
    SkuLeaderboardResponse,
    SkuOriginTreemapItem,
    SkuOriginTreemapResponse,
    TrendResponse,
    TrendSeriesPoint,
    TrendStackedPoint,
)

router = APIRouter(
    prefix="/api/analytics/sku-origin",
    tags=["sku-origin"],
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
        select(func.count())
        .select_from(BillingUsage)
        .where(BillingUsage.usage_usd.isnot(None))
        .limit(1)
    )
    return (result.scalar() or 0) > 0


def _cost_expr(has_usd: bool):
    """Return the column expression to SUM for cost."""
    if has_usd:
        return func.coalesce(func.sum(BillingUsage.usage_usd), 0)
    return func.coalesce(
        func.sum(BillingUsage.usage_quantity * ListPrice.effective_list_price), 0
    )


def _maybe_price_join(stmt, has_usd: bool):
    if has_usd:
        return stmt
    return stmt.join(ListPrice, _PRICE_JOIN)


def _apply_dates(stmt, start_date: Optional[date], end_date: Optional[date]):
    if start_date:
        stmt = stmt.where(BillingUsage.usage_date >= start_date)
    if end_date:
        stmt = stmt.where(BillingUsage.usage_date <= end_date)
    return stmt


def _default_window(start_date: Optional[date], end_date: Optional[date]) -> tuple[date, date]:
    end = end_date or date.today()
    start = start_date or (end - timedelta(days=89))
    if start > end:
        start, end = end, start
    return start, end


# ---------------------------------------------------------------------------
# Panel 1: Treemap (SKU x Billing-Origin grid)
# ---------------------------------------------------------------------------


@router.get("/treemap", response_model=SkuOriginTreemapResponse)
async def treemap(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(200, ge=10, le=1000),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    has_usd = await _has_usage_usd(db)
    cost_expr = _cost_expr(has_usd)
    stmt = select(
        BillingUsage.sku_name,
        BillingUsage.billing_origin_product,
        cost_expr.label("total_cost"),
        func.coalesce(func.sum(BillingUsage.usage_quantity), 0).label("total_usage"),
    ).group_by(BillingUsage.sku_name, BillingUsage.billing_origin_product)
    stmt = _maybe_price_join(stmt, has_usd)
    stmt = _apply_dates(stmt, start_date, end_date)
    stmt = apply_billing_filters(stmt, resolve_effective_filters(authed), view_mode=authed.viewing_data_mode)
    stmt = stmt.order_by(cost_expr.desc()).limit(limit)

    result = await db.execute(stmt)
    items = [
        SkuOriginTreemapItem(
            sku_name=r.sku_name,
            billing_origin_product=r.billing_origin_product,
            total_cost=r.total_cost or Decimal(0),
            total_usage=r.total_usage or Decimal(0),
        )
        for r in result.all()
    ]
    return SkuOriginTreemapResponse(items=items)


# ---------------------------------------------------------------------------
# Panels 2 & 3: Leaderboards (sparkline-aware)
# ---------------------------------------------------------------------------


def _bucket_index(d: date, start: date, step_days: float, n_buckets: int) -> int:
    delta = (d - start).days
    if delta < 0:
        return 0
    idx = int(delta / step_days)
    if idx >= n_buckets:
        return n_buckets - 1
    return idx


@router.get("/sku-leaderboard", response_model=SkuLeaderboardResponse)
async def sku_leaderboard(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(15, ge=1, le=100),
    buckets: int = Query(30, ge=5, le=120),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    start, end = _default_window(start_date, end_date)
    has_usd = await _has_usage_usd(db)
    cost_expr = _cost_expr(has_usd)
    rbac = resolve_effective_filters(authed)

    # Aggregate per-SKU
    stmt = select(
        BillingUsage.sku_name,
        cost_expr.label("total_cost"),
        func.coalesce(func.sum(BillingUsage.usage_quantity), 0).label("total_usage"),
        func.count(func.distinct(BillingUsage.workspace_id)).label("workspace_count"),
    ).group_by(BillingUsage.sku_name)
    stmt = _maybe_price_join(stmt, has_usd)
    stmt = _apply_dates(stmt, start, end)
    stmt = apply_billing_filters(stmt, rbac, view_mode=authed.viewing_data_mode)
    stmt = stmt.order_by(cost_expr.desc()).limit(limit)
    top = (await db.execute(stmt)).all()
    sku_names = [r.sku_name for r in top]
    if not sku_names:
        return SkuLeaderboardResponse(period_start=start, period_end=end, buckets=buckets, data=[])

    # Primary billing origin per SKU (cheap follow-up; one tiny scan, one row per sku)
    origin_stmt = select(
        BillingUsage.sku_name,
        BillingUsage.billing_origin_product,
        cost_expr.label("c"),
    ).group_by(BillingUsage.sku_name, BillingUsage.billing_origin_product)
    origin_stmt = _maybe_price_join(origin_stmt, has_usd)
    origin_stmt = _apply_dates(origin_stmt, start, end)
    origin_stmt = apply_billing_filters(origin_stmt, rbac, view_mode=authed.viewing_data_mode)
    origin_stmt = origin_stmt.where(BillingUsage.sku_name.in_(sku_names))
    primary_origin: dict[str, str] = {}
    best_cost: dict[str, Decimal] = {}
    for r in (await db.execute(origin_stmt)).all():
        if r.c is None:
            continue
        if r.sku_name not in best_cost or r.c > best_cost[r.sku_name]:
            best_cost[r.sku_name] = r.c
            primary_origin[r.sku_name] = r.billing_origin_product

    # Sparkline buckets — one query, group by sku + usage_date, fold into buckets in Python.
    daily_stmt = select(
        BillingUsage.sku_name,
        BillingUsage.usage_date,
        cost_expr.label("c"),
    ).group_by(BillingUsage.sku_name, BillingUsage.usage_date)
    daily_stmt = _maybe_price_join(daily_stmt, has_usd)
    daily_stmt = _apply_dates(daily_stmt, start, end)
    daily_stmt = apply_billing_filters(daily_stmt, rbac, view_mode=authed.viewing_data_mode)
    daily_stmt = daily_stmt.where(BillingUsage.sku_name.in_(sku_names))

    days_total = max((end - start).days + 1, 1)
    n_buckets = max(1, min(buckets, days_total))
    step = days_total / n_buckets
    sparkline_map: dict[str, list[Decimal]] = {n: [Decimal(0)] * n_buckets for n in sku_names}
    for r in (await db.execute(daily_stmt)).all():
        if r.c is None:
            continue
        idx = _bucket_index(r.usage_date, start, step, n_buckets)
        sparkline_map[r.sku_name][idx] += Decimal(r.c)

    data = []
    for r in top:
        usage = r.total_usage or Decimal(0)
        cost = r.total_cost or Decimal(0)
        cpu = (cost / usage) if usage and usage != 0 else None
        data.append(SkuLeaderboardItem(
            sku_name=r.sku_name,
            total_cost=cost,
            total_usage=usage,
            cost_per_unit=cpu,
            workspace_count=int(r.workspace_count or 0),
            primary_billing_origin=primary_origin.get(r.sku_name),
            sparkline=sparkline_map[r.sku_name],
        ))
    return SkuLeaderboardResponse(
        period_start=start, period_end=end, buckets=n_buckets, data=data,
    )


@router.get("/origin-leaderboard", response_model=OriginLeaderboardResponse)
async def origin_leaderboard(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(15, ge=1, le=100),
    buckets: int = Query(30, ge=5, le=120),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    start, end = _default_window(start_date, end_date)
    has_usd = await _has_usage_usd(db)
    cost_expr = _cost_expr(has_usd)
    rbac = resolve_effective_filters(authed)

    stmt = select(
        BillingUsage.billing_origin_product,
        cost_expr.label("total_cost"),
        func.coalesce(func.sum(BillingUsage.usage_quantity), 0).label("total_usage"),
        func.count(func.distinct(BillingUsage.sku_name)).label("sku_count"),
        func.count(func.distinct(BillingUsage.workspace_id)).label("workspace_count"),
    ).group_by(BillingUsage.billing_origin_product)
    stmt = _maybe_price_join(stmt, has_usd)
    stmt = _apply_dates(stmt, start, end)
    stmt = apply_billing_filters(stmt, rbac, view_mode=authed.viewing_data_mode)
    stmt = stmt.order_by(cost_expr.desc()).limit(limit)
    top = (await db.execute(stmt)).all()
    origins = [r.billing_origin_product for r in top]
    if not origins:
        return OriginLeaderboardResponse(period_start=start, period_end=end, buckets=buckets, data=[])

    # Serverless share per origin — three CASE-summed cost slices.
    if has_usd:
        cost_col = func.coalesce(BillingUsage.usage_usd, 0)
    else:
        cost_col = BillingUsage.usage_quantity * ListPrice.effective_list_price
    sl_stmt = select(
        BillingUsage.billing_origin_product,
        func.sum(case((BillingUsage.is_serverless.is_(True), cost_col), else_=0)).label("sl"),
        func.sum(case((BillingUsage.is_serverless.is_(False), cost_col), else_=0)).label("cl"),
    ).group_by(BillingUsage.billing_origin_product)
    sl_stmt = _maybe_price_join(sl_stmt, has_usd)
    sl_stmt = _apply_dates(sl_stmt, start, end)
    sl_stmt = apply_billing_filters(sl_stmt, rbac, view_mode=authed.viewing_data_mode)
    sl_stmt = sl_stmt.where(BillingUsage.billing_origin_product.in_(origins))
    sl_share: dict[str, Optional[float]] = {}
    for r in (await db.execute(sl_stmt)).all():
        sl_v = float(r.sl or 0)
        cl_v = float(r.cl or 0)
        denom = sl_v + cl_v
        sl_share[r.billing_origin_product] = (sl_v / denom * 100.0) if denom > 0 else None

    # Sparkline buckets
    daily_stmt = select(
        BillingUsage.billing_origin_product,
        BillingUsage.usage_date,
        cost_expr.label("c"),
    ).group_by(BillingUsage.billing_origin_product, BillingUsage.usage_date)
    daily_stmt = _maybe_price_join(daily_stmt, has_usd)
    daily_stmt = _apply_dates(daily_stmt, start, end)
    daily_stmt = apply_billing_filters(daily_stmt, rbac, view_mode=authed.viewing_data_mode)
    daily_stmt = daily_stmt.where(BillingUsage.billing_origin_product.in_(origins))

    days_total = max((end - start).days + 1, 1)
    n_buckets = max(1, min(buckets, days_total))
    step = days_total / n_buckets
    sparkline_map: dict[str, list[Decimal]] = {n: [Decimal(0)] * n_buckets for n in origins}
    for r in (await db.execute(daily_stmt)).all():
        if r.c is None:
            continue
        idx = _bucket_index(r.usage_date, start, step, n_buckets)
        sparkline_map[r.billing_origin_product][idx] += Decimal(r.c)

    data = [
        OriginLeaderboardItem(
            billing_origin_product=r.billing_origin_product,
            total_cost=r.total_cost or Decimal(0),
            total_usage=r.total_usage or Decimal(0),
            sku_count=int(r.sku_count or 0),
            workspace_count=int(r.workspace_count or 0),
            serverless_share_pct=sl_share.get(r.billing_origin_product),
            sparkline=sparkline_map[r.billing_origin_product],
        )
        for r in top
    ]
    return OriginLeaderboardResponse(
        period_start=start, period_end=end, buckets=n_buckets, data=data,
    )


# ---------------------------------------------------------------------------
# Generic top-N x top-N pivot helper
# ---------------------------------------------------------------------------


async def _top_n_pivot(
    db: AsyncSession,
    *,
    row_col,
    col_col,
    start_date: Optional[date],
    end_date: Optional[date],
    rbac: Optional[dict[str, Any]],
    view_mode: str,
    top_rows: int,
    top_cols: int,
    skip_null_col: bool = False,
) -> tuple[list[str], list[str], list[PivotCell], Optional[Decimal]]:
    """Return (rows_top, cols_top, cells, null_col_total)."""
    has_usd = await _has_usage_usd(db)
    cost_expr = _cost_expr(has_usd)

    def base_select(*cols):
        s = select(*cols)
        s = _maybe_price_join(s, has_usd)
        s = _apply_dates(s, start_date, end_date)
        s = apply_billing_filters(s, rbac, view_mode=view_mode)
        return s

    # Top rows by total cost
    row_stmt = (
        base_select(row_col.label("row"), cost_expr.label("c"))
        .group_by(row_col)
        .order_by(cost_expr.desc())
        .limit(top_rows)
    )
    row_rs = (await db.execute(row_stmt)).all()
    rows = [r.row for r in row_rs if r.row is not None]
    if not rows:
        return [], [], [], None

    # Top columns by total cost (optionally drop NULL)
    col_stmt = base_select(col_col.label("col"), cost_expr.label("c"))
    if skip_null_col:
        col_stmt = col_stmt.where(col_col.isnot(None))
    col_stmt = col_stmt.group_by(col_col).order_by(cost_expr.desc()).limit(top_cols)
    col_rs = (await db.execute(col_stmt)).all()
    cols = [c.col for c in col_rs if c.col is not None]
    if not cols:
        return rows, [], [], None

    # Cells limited to the chosen rows + cols
    cell_stmt = (
        base_select(row_col.label("row"), col_col.label("col"), cost_expr.label("c"))
        .where(row_col.in_(rows))
        .where(col_col.in_(cols))
        .group_by(row_col, col_col)
    )
    cells = []
    for r in (await db.execute(cell_stmt)).all():
        if r.c is None:
            continue
        cells.append(PivotCell(row=r.row, col=r.col, total_cost=r.c))

    null_col_total: Optional[Decimal] = None
    if skip_null_col:
        null_stmt = base_select(cost_expr.label("c")).where(col_col.is_(None))
        nv = (await db.execute(null_stmt)).scalar()
        null_col_total = Decimal(nv) if nv is not None else Decimal(0)

    return rows, cols, cells, null_col_total


# ---------------------------------------------------------------------------
# Panels 4 & 5: heatmaps
# ---------------------------------------------------------------------------


@router.get("/sku-workspace-matrix", response_model=PivotResponse)
async def sku_workspace_matrix(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    top_skus: int = Query(15, ge=1, le=100),
    top_workspaces: int = Query(15, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    rows, cols, cells, _ = await _top_n_pivot(
        db,
        row_col=BillingUsage.sku_name,
        col_col=BillingUsage.workspace_id,
        start_date=start_date,
        end_date=end_date,
        rbac=resolve_effective_filters(authed),
        view_mode=authed.viewing_data_mode,
        top_rows=top_skus,
        top_cols=top_workspaces,
    )
    return PivotResponse(rows=rows, cols=cols, cells=cells)


@router.get("/origin-workspace-matrix", response_model=PivotResponse)
async def origin_workspace_matrix(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    top_origins: int = Query(15, ge=1, le=100),
    top_workspaces: int = Query(15, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    rows, cols, cells, _ = await _top_n_pivot(
        db,
        row_col=BillingUsage.billing_origin_product,
        col_col=BillingUsage.workspace_id,
        start_date=start_date,
        end_date=end_date,
        rbac=resolve_effective_filters(authed),
        view_mode=authed.viewing_data_mode,
        top_rows=top_origins,
        top_cols=top_workspaces,
    )
    return PivotResponse(rows=rows, cols=cols, cells=cells)


# ---------------------------------------------------------------------------
# Panels 6 & 7: identity pivots (run_as)
# ---------------------------------------------------------------------------


@router.get("/sku-identity", response_model=PivotResponse)
async def sku_identity(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    top_skus: int = Query(15, ge=1, le=100),
    top_identities: int = Query(15, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    rows, cols, cells, null_total = await _top_n_pivot(
        db,
        row_col=BillingUsage.sku_name,
        col_col=BillingUsage.run_as,
        start_date=start_date,
        end_date=end_date,
        rbac=resolve_effective_filters(authed),
        view_mode=authed.viewing_data_mode,
        top_rows=top_skus,
        top_cols=top_identities,
        skip_null_col=True,
    )
    return PivotResponse(rows=rows, cols=cols, cells=cells, null_identity_cost=null_total)


@router.get("/origin-identity", response_model=PivotResponse)
async def origin_identity(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    top_origins: int = Query(15, ge=1, le=100),
    top_identities: int = Query(15, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    rows, cols, cells, null_total = await _top_n_pivot(
        db,
        row_col=BillingUsage.billing_origin_product,
        col_col=BillingUsage.run_as,
        start_date=start_date,
        end_date=end_date,
        rbac=resolve_effective_filters(authed),
        view_mode=authed.viewing_data_mode,
        top_rows=top_origins,
        top_cols=top_identities,
        skip_null_col=True,
    )
    return PivotResponse(rows=rows, cols=cols, cells=cells, null_identity_cost=null_total)


# ---------------------------------------------------------------------------
# Panel 8: concentration / Pareto
# ---------------------------------------------------------------------------


def _top_pct(totals: list[Decimal], n: int) -> Optional[float]:
    if not totals:
        return None
    total = float(sum(totals))
    if total <= 0:
        return None
    top = float(sum(totals[:n]))
    return top / total * 100.0


@router.get("/concentration", response_model=ConcentrationResponse)
async def concentration(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    top: int = Query(8, ge=1, le=25, description="How many SKUs / origins to summarize."),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    has_usd = await _has_usage_usd(db)
    cost_expr = _cost_expr(has_usd)
    rbac = resolve_effective_filters(authed)

    def base_select(*cols):
        s = select(*cols)
        s = _maybe_price_join(s, has_usd)
        s = _apply_dates(s, start_date, end_date)
        s = apply_billing_filters(s, rbac, view_mode=authed.viewing_data_mode)
        return s

    async def fetch_groups(group_col, child_col):
        stmt = (
            base_select(group_col.label("g"), child_col.label("c"), cost_expr.label("v"))
            .group_by(group_col, child_col)
        )
        out: dict[str, list[Decimal]] = defaultdict(list)
        for r in (await db.execute(stmt)).all():
            if r.g is None or r.v is None:
                continue
            out[r.g].append(Decimal(r.v))
        for k in out:
            out[k].sort(reverse=True)
        return out

    # --- BY ORIGIN ---
    origin_totals = (
        await db.execute(
            base_select(
                BillingUsage.billing_origin_product.label("g"),
                cost_expr.label("v"),
            )
            .group_by(BillingUsage.billing_origin_product)
            .order_by(cost_expr.desc())
            .limit(top)
        )
    ).all()
    top_origins = [r.g for r in origin_totals if r.g is not None]
    origin_total_map = {r.g: Decimal(r.v or 0) for r in origin_totals}

    by_origin_skus = await fetch_groups(BillingUsage.billing_origin_product, BillingUsage.sku_name)
    by_origin_ws = await fetch_groups(BillingUsage.billing_origin_product, BillingUsage.workspace_id)

    by_origin: list[ConcentrationRow] = []
    for o in top_origins:
        sku_vals = by_origin_skus.get(o, [])
        ws_vals = by_origin_ws.get(o, [])
        by_origin.append(ConcentrationRow(
            label=o,
            total_cost=origin_total_map.get(o, Decimal(0)),
            top1_sku_pct=_top_pct(sku_vals, 1),
            top3_sku_pct=_top_pct(sku_vals, 3),
            top5_sku_pct=_top_pct(sku_vals, 5),
            top1_workspace_pct=_top_pct(ws_vals, 1),
            top3_workspace_pct=_top_pct(ws_vals, 3),
            top5_workspace_pct=_top_pct(ws_vals, 5),
        ))

    # --- BY SKU ---
    sku_totals = (
        await db.execute(
            base_select(
                BillingUsage.sku_name.label("g"),
                cost_expr.label("v"),
            )
            .group_by(BillingUsage.sku_name)
            .order_by(cost_expr.desc())
            .limit(top)
        )
    ).all()
    top_skus = [r.g for r in sku_totals if r.g is not None]
    sku_total_map = {r.g: Decimal(r.v or 0) for r in sku_totals}

    by_sku_origins = await fetch_groups(BillingUsage.sku_name, BillingUsage.billing_origin_product)
    by_sku_ws = await fetch_groups(BillingUsage.sku_name, BillingUsage.workspace_id)

    by_sku: list[ConcentrationRow] = []
    for s in top_skus:
        origin_vals = by_sku_origins.get(s, [])
        ws_vals = by_sku_ws.get(s, [])
        by_sku.append(ConcentrationRow(
            label=s,
            total_cost=sku_total_map.get(s, Decimal(0)),
            top1_origin_pct=_top_pct(origin_vals, 1),
            top3_origin_pct=_top_pct(origin_vals, 3),
            top5_origin_pct=_top_pct(origin_vals, 5),
            top1_workspace_pct=_top_pct(ws_vals, 1),
            top3_workspace_pct=_top_pct(ws_vals, 3),
            top5_workspace_pct=_top_pct(ws_vals, 5),
        ))

    return ConcentrationResponse(by_origin=by_origin, by_sku=by_sku)


# ---------------------------------------------------------------------------
# Panel 9: trend (daily, stacked by workspace)
# ---------------------------------------------------------------------------


@router.get("/trend", response_model=TrendResponse)
async def trend(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sku_name: Optional[str] = Query(None),
    billing_origin: Optional[str] = Query(None),
    top_workspaces: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    start, end = _default_window(start_date, end_date)
    has_usd = await _has_usage_usd(db)
    cost_expr = _cost_expr(has_usd)
    rbac = resolve_effective_filters(authed)

    def base_select(*cols):
        s = select(*cols)
        s = _maybe_price_join(s, has_usd)
        s = s.where(BillingUsage.usage_date >= start, BillingUsage.usage_date <= end)
        if sku_name:
            s = s.where(BillingUsage.sku_name == sku_name)
        if billing_origin:
            s = s.where(BillingUsage.billing_origin_product == billing_origin)
        s = apply_billing_filters(s, rbac, view_mode=authed.viewing_data_mode)
        return s

    # Find top workspaces in this slice
    ws_stmt = (
        base_select(BillingUsage.workspace_id.label("g"), cost_expr.label("c"))
        .group_by(BillingUsage.workspace_id)
        .order_by(cost_expr.desc())
        .limit(top_workspaces)
    )
    top_ws = [r.g for r in (await db.execute(ws_stmt)).all() if r.g is not None]

    # Per-day per-workspace, bucketing non-top workspaces as 'other'
    daily_stmt = (
        base_select(
            BillingUsage.usage_date.label("d"),
            BillingUsage.workspace_id.label("w"),
            cost_expr.label("c"),
        )
        .group_by(BillingUsage.usage_date, BillingUsage.workspace_id)
    )
    rows = (await db.execute(daily_stmt)).all()

    per_day: dict[date, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    other_per_day: dict[date, Decimal] = defaultdict(Decimal)
    top_set = set(top_ws)
    for r in rows:
        if r.c is None:
            continue
        v = Decimal(r.c)
        if r.w in top_set:
            per_day[r.d][r.w] += v
        else:
            other_per_day[r.d] += v

    all_dates = sorted({r.d for r in rows})
    stacked: list[TrendStackedPoint] = []
    total_series: list[TrendSeriesPoint] = []
    for d in all_dates:
        values = {w: per_day[d].get(w, Decimal(0)) for w in top_ws}
        oth = other_per_day.get(d, Decimal(0))
        stacked.append(TrendStackedPoint(usage_date=d, values=values, other_cost=oth))
        total_series.append(
            TrendSeriesPoint(usage_date=d, total_cost=sum(values.values()) + oth)
        )

    return TrendResponse(
        workspaces=top_ws,
        points=stacked,
        total=total_series,
        filter_sku=sku_name,
        filter_origin=billing_origin,
    )


# ---------------------------------------------------------------------------
# Panel 10: serverless vs classic share per billing origin
# ---------------------------------------------------------------------------


@router.get("/serverless-share", response_model=ServerlessShareResponse)
async def serverless_share(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    has_usd = await _has_usage_usd(db)
    if has_usd:
        cost_col = func.coalesce(BillingUsage.usage_usd, 0)
    else:
        cost_col = BillingUsage.usage_quantity * ListPrice.effective_list_price

    rbac = resolve_effective_filters(authed)
    stmt = (
        select(
            BillingUsage.billing_origin_product.label("o"),
            func.sum(case((BillingUsage.is_serverless.is_(True), cost_col), else_=0)).label("sl"),
            func.sum(case((BillingUsage.is_serverless.is_(False), cost_col), else_=0)).label("cl"),
            func.sum(case((BillingUsage.is_serverless.is_(None), cost_col), else_=0)).label("un"),
        )
        .group_by(BillingUsage.billing_origin_product)
    )
    stmt = _maybe_price_join(stmt, has_usd)
    stmt = _apply_dates(stmt, start_date, end_date)
    stmt = apply_billing_filters(stmt, rbac, view_mode=authed.viewing_data_mode)
    rows = (await db.execute(stmt)).all()

    data: list[ServerlessShareItem] = []
    for r in rows:
        sl = Decimal(r.sl or 0)
        cl = Decimal(r.cl or 0)
        un = Decimal(r.un or 0)
        total = sl + cl + un
        denom = sl + cl
        pct = float(sl / denom * 100) if denom > 0 else None
        data.append(ServerlessShareItem(
            billing_origin_product=r.o,
            serverless_cost=sl,
            classic_cost=cl,
            unknown_cost=un,
            total_cost=total,
            serverless_pct=pct,
        ))
    data.sort(key=lambda x: x.total_cost, reverse=True)
    return ServerlessShareResponse(data=data[:limit])


# ---------------------------------------------------------------------------
# Drill drawer
# ---------------------------------------------------------------------------


@router.get("/drilldown", response_model=DrillResponse)
async def drilldown(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sku_name: Optional[str] = Query(None),
    billing_origin: Optional[str] = Query(None),
    top_workspaces: int = Query(10, ge=1, le=50),
    top_identities: int = Query(10, ge=1, le=50),
    top_owners: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    authed: AuthedUser = Depends(get_current_user),
):
    if bool(sku_name) == bool(billing_origin):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of sku_name or billing_origin.",
        )
    target_kind = "sku" if sku_name else "billing_origin"
    target = sku_name or billing_origin or ""

    start, end = _default_window(start_date, end_date)
    has_usd = await _has_usage_usd(db)
    cost_expr = _cost_expr(has_usd)
    rbac = resolve_effective_filters(authed)

    def base_select(*cols):
        s = select(*cols)
        s = _maybe_price_join(s, has_usd)
        s = s.where(BillingUsage.usage_date >= start, BillingUsage.usage_date <= end)
        if sku_name:
            s = s.where(BillingUsage.sku_name == sku_name)
        if billing_origin:
            s = s.where(BillingUsage.billing_origin_product == billing_origin)
        s = apply_billing_filters(s, rbac, view_mode=authed.viewing_data_mode)
        return s

    # Totals
    totals_stmt = base_select(
        cost_expr.label("c"),
        func.coalesce(func.sum(BillingUsage.usage_quantity), 0).label("u"),
    )
    tot = (await db.execute(totals_stmt)).one()
    total_cost = Decimal(tot.c or 0)
    total_usage = Decimal(tot.u or 0)

    # Trend (single daily series)
    trend_stmt = (
        base_select(BillingUsage.usage_date.label("d"), cost_expr.label("c"))
        .group_by(BillingUsage.usage_date)
        .order_by(BillingUsage.usage_date)
    )
    trend_rows = (await db.execute(trend_stmt)).all()
    trend = [
        TrendSeriesPoint(usage_date=r.d, total_cost=Decimal(r.c or 0))
        for r in trend_rows
        if r.c is not None
    ]

    # Top workspaces
    ws_stmt = (
        base_select(
            BillingUsage.workspace_id.label("g"),
            cost_expr.label("c"),
            func.coalesce(func.sum(BillingUsage.usage_quantity), 0).label("u"),
        )
        .group_by(BillingUsage.workspace_id)
        .order_by(cost_expr.desc())
        .limit(top_workspaces)
    )
    top_ws = [
        DrillTopItem(label=r.g, total_cost=Decimal(r.c or 0), total_usage=Decimal(r.u or 0))
        for r in (await db.execute(ws_stmt)).all() if r.g is not None
    ]

    # Top identities (non-null run_as)
    id_stmt = (
        base_select(
            BillingUsage.run_as.label("g"),
            cost_expr.label("c"),
            func.coalesce(func.sum(BillingUsage.usage_quantity), 0).label("u"),
        )
        .where(BillingUsage.run_as.isnot(None))
        .group_by(BillingUsage.run_as)
        .order_by(cost_expr.desc())
        .limit(top_identities)
    )
    top_ids = [
        DrillTopItem(label=r.g, total_cost=Decimal(r.c or 0), total_usage=Decimal(r.u or 0))
        for r in (await db.execute(id_stmt)).all()
    ]
    null_id_total = Decimal((await db.execute(base_select(cost_expr.label("c")).where(BillingUsage.run_as.is_(None)))).scalar() or 0)

    # Related compute owners — join via cluster_id / warehouse_id / job_id.
    # Each owner appears once per source, with the count of distinct resources.
    cluster_stmt = (
        base_select(
            Cluster.owned_by.label("g"),
            cost_expr.label("c"),
            func.count(func.distinct(BillingUsage.cluster_id)).label("n"),
        )
        .join(Cluster, Cluster.cluster_id == BillingUsage.cluster_id)
        .where(Cluster.owned_by.isnot(None))
        .group_by(Cluster.owned_by)
        .order_by(cost_expr.desc())
        .limit(top_owners)
    )
    cluster_owners = [
        DrillOwnerItem(
            owner=r.g,
            source="cluster",
            resource_count=int(r.n or 0),
            total_cost=Decimal(r.c or 0),
        )
        for r in (await db.execute(cluster_stmt)).all()
    ]

    warehouse_stmt = (
        base_select(
            Warehouse.created_by.label("g"),
            cost_expr.label("c"),
            func.count(func.distinct(BillingUsage.warehouse_id)).label("n"),
        )
        .join(Warehouse, Warehouse.warehouse_id == BillingUsage.warehouse_id)
        .where(Warehouse.created_by.isnot(None))
        .group_by(Warehouse.created_by)
        .order_by(cost_expr.desc())
        .limit(top_owners)
    )
    warehouse_owners = [
        DrillOwnerItem(
            owner=r.g,
            source="warehouse",
            resource_count=int(r.n or 0),
            total_cost=Decimal(r.c or 0),
        )
        for r in (await db.execute(warehouse_stmt)).all()
    ]

    job_stmt = (
        base_select(
            Job.creator_id.label("g"),
            cost_expr.label("c"),
            func.count(func.distinct(BillingUsage.job_id)).label("n"),
        )
        .join(Job, Job.job_id == BillingUsage.job_id)
        .where(Job.creator_id.isnot(None))
        .group_by(Job.creator_id)
        .order_by(cost_expr.desc())
        .limit(top_owners)
    )
    job_owners = [
        DrillOwnerItem(
            owner=r.g,
            source="job",
            resource_count=int(r.n or 0),
            total_cost=Decimal(r.c or 0),
        )
        for r in (await db.execute(job_stmt)).all()
    ]

    return DrillResponse(
        target_kind=target_kind,
        target=target,
        total_cost=total_cost,
        total_usage=total_usage,
        trend=trend,
        top_workspaces=top_ws,
        top_identities=top_ids,
        null_identity_cost=null_id_total,
        related_owners=cluster_owners + warehouse_owners + job_owners,
    )
