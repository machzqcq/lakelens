"""Pydantic response models for the Databricks Billing Analytics API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------

class UsageSummaryItem(BaseModel):
    """Single row in the aggregated usage-summary response."""
    period: str = Field(description="Time-period label (ISO date or week/month string)")
    total_usage: Decimal = Field(description="Sum of usage_quantity for the period")
    total_cost: Decimal = Field(description="Estimated cost (quantity * effective_list_price)")


class UsageSummaryResponse(BaseModel):
    data: list[UsageSummaryItem]


class UsageSummaryBySkuItem(BaseModel):
    period: str
    sku_name: str
    total_usage: Decimal
    total_cost: Decimal


class UsageSummaryBySkuResponse(BaseModel):
    skus: list[str] = Field(description="SKUs in display order (top by cost desc)")
    data: list[UsageSummaryBySkuItem]


class BreakdownItem(BaseModel):
    """Generic breakdown row used for by-sku, by-workspace, etc."""
    label: str = Field(description="Grouping key value (SKU name, workspace ID, etc.)")
    total_usage: Decimal = Field(description="Sum of usage_quantity")
    total_cost: Decimal = Field(description="Estimated cost")


class BreakdownResponse(BaseModel):
    data: list[BreakdownItem]


class UserCostItem(BaseModel):
    """Top user row."""
    user: str = Field(description="run_as identity")
    total_usage: Decimal
    total_cost: Decimal


class UserCostResponse(BaseModel):
    data: list[UserCostItem]


class DailyTrendItem(BaseModel):
    usage_date: date
    total_usage: Decimal
    total_cost: Decimal


class DailyTrendResponse(BaseModel):
    data: list[DailyTrendItem]


class TopSkuItem(BaseModel):
    sku_name: str
    total_usage: Decimal
    total_cost: Decimal
    rank: int


class TopSkuResponse(BaseModel):
    data: list[TopSkuItem]


class SkuUserCostItem(BaseModel):
    """Single (SKU, user) cost cell."""
    sku_name: str
    run_as: str
    total_usage: Decimal
    total_cost: Decimal


class SkuUserMatrixResponse(BaseModel):
    """Top SKUs x top users matrix. Cells are sparse — pairs with zero cost are omitted."""
    skus: list[str] = Field(description="SKUs ordered by total cost desc")
    users: list[str] = Field(description="Users ordered by total cost desc")
    cells: list[SkuUserCostItem]


class UserSkuUsage(BaseModel):
    sku_name: str
    total_usage: Decimal
    total_cost: Decimal


class UserResourceUsage(BaseModel):
    resource_id: str
    resource_name: Optional[str] = None
    total_usage: Decimal
    total_cost: Decimal


class UserUtilizationResponse(BaseModel):
    """Single-user pivot: SKU + cluster + warehouse breakdowns for one run_as identity."""
    user: str
    total_usage: Decimal
    total_cost: Decimal
    skus: list[UserSkuUsage]
    clusters: list[UserResourceUsage]
    warehouses: list[UserResourceUsage]


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------

class ClusterDetail(BaseModel):
    cluster_id: str
    cluster_name: str
    workspace_id: str
    owned_by: Optional[str] = None
    driver_node_type: Optional[str] = None
    worker_node_type: Optional[str] = None
    worker_count: Optional[int] = None
    min_autoscale_workers: Optional[int] = None
    max_autoscale_workers: Optional[int] = None
    dbr_version: Optional[str] = None
    cluster_source: Optional[str] = None
    data_security_mode: Optional[str] = None
    create_time: Optional[datetime] = None
    delete_time: Optional[datetime] = None

    # Derived from node-specs lookup (NULL when node_type is unknown)
    driver_vcpus: Optional[int] = None
    driver_memory_gb: Optional[float] = None
    driver_family: Optional[str] = None
    driver_has_gpu: Optional[bool] = None
    total_vcpus: Optional[int] = Field(None, description="driver vCPUs + max_workers * worker vCPUs (NULL if driver type unknown)")
    total_memory_gb: Optional[float] = Field(None, description="driver mem + max_workers * worker mem (NULL if driver type unknown)")


class PaginatedClusterResponse(BaseModel):
    data: list[ClusterDetail]
    total: int = Field(description="Total matching records")
    page: int = Field(description="Current page (1-indexed)")
    page_size: int = Field(description="Records per page")
    total_pages: int = Field(description="Total number of pages")


class NodeSpecModel(BaseModel):
    node_type: str
    cloud: str
    family: str
    vcpus: int
    memory_gb: float
    local_disk_gb: Optional[float] = None
    gpu_count: Optional[int] = None
    gpu_type: Optional[str] = None


class ClusterSkuUsage(BaseModel):
    """Per-SKU usage roll-up for a single cluster."""
    sku_name: str
    total_usage: Decimal
    total_cost: Decimal


class ClusterFullDetail(BaseModel):
    """Latest config row for a cluster plus enriched billing aggregates."""

    # Identity / config (all stored fields)
    cluster_id: str
    cluster_name: str
    account_id: str
    workspace_id: str
    owned_by: Optional[str] = None
    driver_node_type: Optional[str] = None
    worker_node_type: Optional[str] = None
    worker_count: Optional[int] = None
    min_autoscale_workers: Optional[int] = None
    max_autoscale_workers: Optional[int] = None
    dbr_version: Optional[str] = None
    cluster_source: Optional[str] = None
    data_security_mode: Optional[str] = None
    create_time: Optional[datetime] = None
    change_time: Optional[datetime] = None
    delete_time: Optional[datetime] = None

    # Derived hardware (from node-spec lookup)
    driver_spec: Optional[NodeSpecModel] = None
    worker_spec: Optional[NodeSpecModel] = None
    total_vcpus: Optional[int] = Field(None, description="driver vCPUs + workers * worker vCPUs (uses max workers if autoscaling)")
    total_memory_gb: Optional[float] = Field(None, description="driver mem + workers * worker mem (uses max workers if autoscaling)")

    # Billing aggregates (lifetime)
    total_cost: Decimal = Field(default=Decimal(0))
    total_usage: Decimal = Field(default=Decimal(0))
    last_usage_date: Optional[date] = None
    is_photon_observed: bool = False
    is_serverless_observed: bool = False
    sku_breakdown: list[ClusterSkuUsage] = Field(default_factory=list)


class WarehouseDetail(BaseModel):
    warehouse_id: str
    warehouse_name: str
    workspace_id: str
    warehouse_type: Optional[str] = None
    warehouse_size: Optional[str] = None
    min_clusters: Optional[int] = None
    max_clusters: Optional[int] = None
    auto_stop_minutes: Optional[int] = None
    created_by: Optional[str] = None
    change_time: Optional[datetime] = None
    delete_time: Optional[datetime] = None


class WarehouseSizeSpecModel(BaseModel):
    size: str
    label: str
    max_dbu_per_hour: int
    cluster_count: int


class WarehouseSkuUsage(BaseModel):
    """Per-SKU usage roll-up for a single warehouse."""
    sku_name: str
    total_usage: Decimal
    total_cost: Decimal


class WarehouseFullDetail(BaseModel):
    """Latest config row for a warehouse plus enriched billing aggregates."""

    # Identity / config
    warehouse_id: str
    warehouse_name: str
    account_id: str
    workspace_id: str
    warehouse_type: Optional[str] = None
    warehouse_size: Optional[str] = None
    min_clusters: Optional[int] = None
    max_clusters: Optional[int] = None
    auto_stop_minutes: Optional[int] = None
    created_by: Optional[str] = None
    change_time: Optional[datetime] = None
    delete_time: Optional[datetime] = None

    # Derived from t-shirt size lookup
    size_spec: Optional[WarehouseSizeSpecModel] = None
    max_dbu_per_hour: Optional[int] = Field(
        None,
        description="Peak DBU/hr at max_clusters (size_spec.max_dbu_per_hour x max_clusters)",
    )

    # Billing aggregates (lifetime)
    total_cost: Decimal = Field(default=Decimal(0))
    total_usage: Decimal = Field(default=Decimal(0))
    last_usage_date: Optional[date] = None
    is_photon_observed: bool = False
    is_serverless_observed: bool = False
    sku_breakdown: list[WarehouseSkuUsage] = Field(default_factory=list)


class PaginatedWarehouseResponse(BaseModel):
    data: list[WarehouseDetail]
    total: int
    page: int
    page_size: int
    total_pages: int


class ComputeCostResponse(BaseModel):
    """Cost response for a single cluster or warehouse."""
    resource_id: str
    total_usage: Decimal
    total_cost: Decimal
    start_date: date
    end_date: date


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class CostAnomalyItem(BaseModel):
    usage_date: date
    actual_cost: Decimal = Field(description="Observed daily cost")
    expected_cost: Decimal = Field(description="30-day rolling average cost")
    std_dev: Decimal = Field(description="Rolling standard deviation")
    z_score: float = Field(description="Number of std deviations from mean")


class CostAnomalyResponse(BaseModel):
    data: list[CostAnomalyItem]


class ForecastItem(BaseModel):
    forecast_date: date
    forecasted_cost: Decimal


class ForecastResponse(BaseModel):
    data: list[ForecastItem]


class MoMGrowthItem(BaseModel):
    month: str = Field(description="YYYY-MM")
    total_cost: Decimal
    prior_month_cost: Optional[Decimal] = None
    growth_pct: Optional[float] = Field(None, description="Month-over-month growth percentage")


class MoMGrowthResponse(BaseModel):
    data: list[MoMGrowthItem]


class CostMatrixCell(BaseModel):
    workspace_id: str
    billing_origin: str
    total_cost: Decimal


class CostMatrixResponse(BaseModel):
    workspaces: list[str]
    billing_origins: list[str]
    cells: list[CostMatrixCell]


class UtilizationItem(BaseModel):
    workspace_id: str
    avg_dbu_per_day: Decimal
    peak_dbu_per_day: Decimal
    total_cost: Decimal


class UtilizationSummaryResponse(BaseModel):
    data: list[UtilizationItem]


class KPISummary(BaseModel):
    total_cost: Decimal = Field(description="Total estimated cost in period")
    total_dbus: Decimal = Field(description="Total usage quantity (DBUs)")
    avg_daily_cost: Decimal = Field(description="Average daily cost")
    active_workspaces: int = Field(description="Count of distinct workspace IDs")
    active_skus: int = Field(description="Count of distinct SKU names")
    cost_trend_pct: Optional[float] = Field(
        None, description="Percentage change vs the prior period of equal length"
    )


class HealthResponse(BaseModel):
    status: str
    version: str


# ---------------------------------------------------------------------------
# SKU & Billing-Origin analytics
# ---------------------------------------------------------------------------


class SkuOriginTreemapItem(BaseModel):
    sku_name: str
    billing_origin_product: str
    total_cost: Decimal
    total_usage: Decimal


class SkuOriginTreemapResponse(BaseModel):
    items: list[SkuOriginTreemapItem]


class SkuLeaderboardItem(BaseModel):
    sku_name: str
    total_cost: Decimal
    total_usage: Decimal
    cost_per_unit: Optional[Decimal] = Field(
        None, description="total_cost / total_usage; null if usage is 0."
    )
    workspace_count: int = Field(description="Distinct workspaces using this SKU.")
    primary_billing_origin: Optional[str] = Field(
        None, description="The billing_origin_product that dominates spend on this SKU."
    )
    sparkline: list[Decimal] = Field(
        default_factory=list, description="Cost per equally-sized time bucket over the period."
    )


class SkuLeaderboardResponse(BaseModel):
    period_start: date
    period_end: date
    buckets: int = Field(description="Number of buckets the sparkline is split into.")
    data: list[SkuLeaderboardItem]


class OriginLeaderboardItem(BaseModel):
    billing_origin_product: str
    total_cost: Decimal
    total_usage: Decimal
    sku_count: int
    workspace_count: int
    serverless_share_pct: Optional[float] = Field(
        None, description="0-100, share of this origin's spend that ran on serverless. Null if unknown."
    )
    sparkline: list[Decimal] = Field(default_factory=list)


class OriginLeaderboardResponse(BaseModel):
    period_start: date
    period_end: date
    buckets: int
    data: list[OriginLeaderboardItem]


class PivotCell(BaseModel):
    row: str
    col: str
    total_cost: Decimal


class PivotResponse(BaseModel):
    """Generic top-N x top-N pivot used by all four heatmap-style endpoints."""
    rows: list[str] = Field(description="Row labels ordered by total cost desc.")
    cols: list[str] = Field(description="Column labels ordered by total cost desc.")
    cells: list[PivotCell]
    null_identity_cost: Optional[Decimal] = Field(
        None,
        description="(Identity pivots only) total cost from rows where run_as is NULL — typically interactive workloads.",
    )


class ConcentrationRow(BaseModel):
    label: str = Field(description="SKU name or billing origin")
    total_cost: Decimal
    # SKU breakdown share inside this row
    top1_sku_pct: Optional[float] = None
    top3_sku_pct: Optional[float] = None
    top5_sku_pct: Optional[float] = None
    # Billing origin breakdown share inside this row (only populated for by-SKU rows)
    top1_origin_pct: Optional[float] = None
    top3_origin_pct: Optional[float] = None
    top5_origin_pct: Optional[float] = None
    # Workspace share
    top1_workspace_pct: Optional[float] = None
    top3_workspace_pct: Optional[float] = None
    top5_workspace_pct: Optional[float] = None


class ConcentrationResponse(BaseModel):
    by_origin: list[ConcentrationRow]
    by_sku: list[ConcentrationRow]


class TrendSeriesPoint(BaseModel):
    usage_date: date
    total_cost: Decimal


class TrendStackedPoint(BaseModel):
    usage_date: date
    # workspace_id -> cost (sparse; missing = 0)
    values: dict[str, Decimal]
    other_cost: Decimal = Field(default=Decimal(0), description="Bucketed-together cost from workspaces outside the top-N.")


class TrendResponse(BaseModel):
    workspaces: list[str] = Field(description="Top-N workspace labels for stacking, ordered by cost desc.")
    points: list[TrendStackedPoint]
    total: list[TrendSeriesPoint] = Field(description="Daily totals across all workspaces.")
    filter_sku: Optional[str] = None
    filter_origin: Optional[str] = None


class ServerlessShareItem(BaseModel):
    billing_origin_product: str
    serverless_cost: Decimal
    classic_cost: Decimal
    unknown_cost: Decimal = Field(description="Cost on rows where is_serverless is NULL.")
    total_cost: Decimal
    serverless_pct: Optional[float] = Field(None, description="0-100; null if total_cost is 0.")


class ServerlessShareResponse(BaseModel):
    data: list[ServerlessShareItem]


class DrillTopItem(BaseModel):
    label: str
    total_cost: Decimal
    total_usage: Decimal


class DrillOwnerItem(BaseModel):
    owner: str
    source: str = Field(description="cluster|warehouse|job")
    resource_count: int
    total_cost: Decimal


class DrillResponse(BaseModel):
    target_kind: str = Field(description="sku|billing_origin")
    target: str
    total_cost: Decimal
    total_usage: Decimal
    trend: list[TrendSeriesPoint]
    top_workspaces: list[DrillTopItem]
    top_identities: list[DrillTopItem]
    null_identity_cost: Decimal
    related_owners: list[DrillOwnerItem]
