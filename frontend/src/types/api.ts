/** TypeScript interfaces matching backend Pydantic models. */

// --- Billing ---

export interface UsageSummaryItem {
  period: string;
  total_usage: number;
  total_cost: number;
}

export interface UsageSummaryBySkuItem {
  period: string;
  sku_name: string;
  total_usage: number;
  total_cost: number;
}

export interface UsageSummaryBySkuResponse {
  skus: string[];
  data: UsageSummaryBySkuItem[];
}

export interface BreakdownItem {
  label: string;
  total_usage: number;
  total_cost: number;
}

export interface UserCostItem {
  user: string;
  total_usage: number;
  total_cost: number;
}

export interface DailyTrendItem {
  usage_date: string;
  total_usage: number;
  total_cost: number;
}

export interface TopSkuItem {
  sku_name: string;
  total_usage: number;
  total_cost: number;
  rank: number;
}

export interface SkuUserCostItem {
  sku_name: string;
  run_as: string;
  total_usage: number;
  total_cost: number;
}

export interface SkuUserMatrixResponse {
  skus: string[];
  users: string[];
  cells: SkuUserCostItem[];
}

export interface UserSkuUsage {
  sku_name: string;
  total_usage: number;
  total_cost: number;
}

export interface UserResourceUsage {
  resource_id: string;
  resource_name: string | null;
  total_usage: number;
  total_cost: number;
}

export interface UserUtilizationResponse {
  user: string;
  total_usage: number;
  total_cost: number;
  skus: UserSkuUsage[];
  clusters: UserResourceUsage[];
  warehouses: UserResourceUsage[];
}

// --- Chatbot ---

export interface ChatModelsResponse {
  models: Record<string, string[]>;
}

export interface ChatAskRequest {
  message: string;
  provider: string;
  model: string;
  api_key?: string;
  explain?: boolean;
}

export interface ChatAskResponse {
  sql: string;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  explanation: string | null;
  error?: string | null;
  user_message: string;
  provider: string;
  model: string;
  system_prompt: string;
  raw_llm_response: string;
  elapsed_seconds: number;
}

// --- Compute ---

export interface ClusterDetail {
  cluster_id: string;
  cluster_name: string;
  workspace_id: string;
  owned_by: string | null;
  driver_node_type: string | null;
  worker_node_type: string | null;
  worker_count: number | null;
  min_autoscale_workers: number | null;
  max_autoscale_workers: number | null;
  dbr_version: string | null;
  cluster_source: string | null;
  data_security_mode: string | null;
  create_time: string | null;
  delete_time: string | null;

  driver_vcpus: number | null;
  driver_memory_gb: number | null;
  driver_family: string | null;
  driver_has_gpu: boolean | null;
  total_vcpus: number | null;
  total_memory_gb: number | null;
}

export type ClusterSortBy =
  | 'name'
  | 'created'
  | 'workers'
  | 'driver_vcpus'
  | 'driver_memory_gb'
  | 'total_vcpus'
  | 'total_memory_gb';

export type SortOrder = 'asc' | 'desc';

export interface ClusterListParams {
  page?: number;
  pageSize?: number;
  search?: string;
  workspaceId?: string;
  clusterSource?: string;
  dataSecurityMode?: string;
  nodeFamily?: string;
  hasGpu?: boolean;
  minVcpus?: number;
  minMemoryGb?: number;
  sortBy?: ClusterSortBy;
  sortOrder?: SortOrder;
}

export interface WarehouseDetail {
  warehouse_id: string;
  warehouse_name: string;
  workspace_id: string;
  warehouse_type: string | null;
  warehouse_size: string | null;
  min_clusters: number | null;
  max_clusters: number | null;
  auto_stop_minutes: number | null;
  created_by: string | null;
  change_time: string | null;
  delete_time: string | null;
}

export interface WarehouseSizeSpec {
  size: string;
  label: string;
  max_dbu_per_hour: number;
  cluster_count: number;
}

export interface WarehouseSkuUsage {
  sku_name: string;
  total_usage: number;
  total_cost: number;
}

export interface WarehouseFullDetail {
  warehouse_id: string;
  warehouse_name: string;
  account_id: string;
  workspace_id: string;
  warehouse_type: string | null;
  warehouse_size: string | null;
  min_clusters: number | null;
  max_clusters: number | null;
  auto_stop_minutes: number | null;
  created_by: string | null;
  change_time: string | null;
  delete_time: string | null;

  size_spec: WarehouseSizeSpec | null;
  max_dbu_per_hour: number | null;

  total_cost: number;
  total_usage: number;
  last_usage_date: string | null;
  is_photon_observed: boolean;
  is_serverless_observed: boolean;
  sku_breakdown: WarehouseSkuUsage[];
}

export interface ComputeCostResponse {
  resource_id: string;
  total_usage: number;
  total_cost: number;
  start_date: string;
  end_date: string;
}

export interface NodeSpec {
  node_type: string;
  cloud: string;
  family: string;
  vcpus: number;
  memory_gb: number;
  local_disk_gb: number | null;
  gpu_count: number | null;
  gpu_type: string | null;
}

export interface ClusterSkuUsage {
  sku_name: string;
  total_usage: number;
  total_cost: number;
}

export interface ClusterFullDetail {
  cluster_id: string;
  cluster_name: string;
  account_id: string;
  workspace_id: string;
  owned_by: string | null;
  driver_node_type: string | null;
  worker_node_type: string | null;
  worker_count: number | null;
  min_autoscale_workers: number | null;
  max_autoscale_workers: number | null;
  dbr_version: string | null;
  cluster_source: string | null;
  data_security_mode: string | null;
  create_time: string | null;
  change_time: string | null;
  delete_time: string | null;

  driver_spec: NodeSpec | null;
  worker_spec: NodeSpec | null;
  total_vcpus: number | null;
  total_memory_gb: number | null;

  total_cost: number;
  total_usage: number;
  last_usage_date: string | null;
  is_photon_observed: boolean;
  is_serverless_observed: boolean;
  sku_breakdown: ClusterSkuUsage[];
}

// --- Analytics ---

export interface CostAnomalyItem {
  usage_date: string;
  actual_cost: number;
  expected_cost: number;
  std_dev: number;
  z_score: number;
}

export interface ForecastItem {
  forecast_date: string;
  forecasted_cost: number;
}

export interface MoMGrowthItem {
  month: string;
  total_cost: number;
  prior_month_cost: number | null;
  growth_pct: number | null;
}

export interface CostMatrixCell {
  workspace_id: string;
  billing_origin: string;
  total_cost: number;
}

export interface CostMatrixResponse {
  workspaces: string[];
  billing_origins: string[];
  cells: CostMatrixCell[];
}

export interface UtilizationItem {
  workspace_id: string;
  avg_dbu_per_day: number;
  peak_dbu_per_day: number;
  total_cost: number;
}

export interface KPISummary {
  total_cost: number;
  total_dbus: number;
  avg_daily_cost: number;
  active_workspaces: number;
  active_skus: number;
  cost_trend_pct: number | null;
}

// --- SKU & Billing Origin analytics ---

export interface SkuOriginTreemapItem {
  sku_name: string;
  billing_origin_product: string;
  total_cost: number;
  total_usage: number;
}

export interface SkuOriginTreemapResponse {
  items: SkuOriginTreemapItem[];
}

export interface SkuLeaderboardItem {
  sku_name: string;
  total_cost: number;
  total_usage: number;
  cost_per_unit: number | null;
  workspace_count: number;
  primary_billing_origin: string | null;
  sparkline: number[];
}

export interface SkuLeaderboardResponse {
  period_start: string;
  period_end: string;
  buckets: number;
  data: SkuLeaderboardItem[];
}

export interface OriginLeaderboardItem {
  billing_origin_product: string;
  total_cost: number;
  total_usage: number;
  sku_count: number;
  workspace_count: number;
  serverless_share_pct: number | null;
  sparkline: number[];
}

export interface OriginLeaderboardResponse {
  period_start: string;
  period_end: string;
  buckets: number;
  data: OriginLeaderboardItem[];
}

export interface PivotCell {
  row: string;
  col: string;
  total_cost: number;
}

export interface PivotResponse {
  rows: string[];
  cols: string[];
  cells: PivotCell[];
  null_identity_cost?: number | null;
}

export interface ConcentrationRow {
  label: string;
  total_cost: number;
  top1_sku_pct: number | null;
  top3_sku_pct: number | null;
  top5_sku_pct: number | null;
  top1_origin_pct: number | null;
  top3_origin_pct: number | null;
  top5_origin_pct: number | null;
  top1_workspace_pct: number | null;
  top3_workspace_pct: number | null;
  top5_workspace_pct: number | null;
}

export interface ConcentrationResponse {
  by_origin: ConcentrationRow[];
  by_sku: ConcentrationRow[];
}

export interface TrendSeriesPoint {
  usage_date: string;
  total_cost: number;
}

export interface TrendStackedPoint {
  usage_date: string;
  values: Record<string, number>;
  other_cost: number;
}

export interface TrendResponse {
  workspaces: string[];
  points: TrendStackedPoint[];
  total: TrendSeriesPoint[];
  filter_sku: string | null;
  filter_origin: string | null;
}

export interface ServerlessShareItem {
  billing_origin_product: string;
  serverless_cost: number;
  classic_cost: number;
  unknown_cost: number;
  total_cost: number;
  serverless_pct: number | null;
}

export interface ServerlessShareResponse {
  data: ServerlessShareItem[];
}

export interface DrillTopItem {
  label: string;
  total_cost: number;
  total_usage: number;
}

export interface DrillOwnerItem {
  owner: string;
  source: 'cluster' | 'warehouse' | 'job';
  resource_count: number;
  total_cost: number;
}

export interface DrillResponse {
  target_kind: 'sku' | 'billing_origin';
  target: string;
  total_cost: number;
  total_usage: number;
  trend: TrendSeriesPoint[];
  top_workspaces: DrillTopItem[];
  top_identities: DrillTopItem[];
  null_identity_cost: number;
  related_owners: DrillOwnerItem[];
}

// --- API response wrappers ---

export interface ApiResponse<T> {
  data: T[];
}

export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}
