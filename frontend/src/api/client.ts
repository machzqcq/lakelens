/**
 * API client for the Databricks billing dashboard backend.
 * All functions use the /api prefix which Vite proxies to the FastAPI backend.
 */

import type {
  ApiResponse,
  PaginatedResponse,
  BreakdownItem,
  ClusterDetail,
  ClusterFullDetail,
  ClusterListParams,
  ComputeCostResponse,
  CostAnomalyItem,
  CostMatrixResponse,
  DailyTrendItem,
  ForecastItem,
  KPISummary,
  MoMGrowthItem,
  SkuUserMatrixResponse,
  TopSkuItem,
  UsageSummaryBySkuResponse,
  UserUtilizationResponse,
  UsageSummaryItem,
  UserCostItem,
  UtilizationItem,
  WarehouseDetail,
  WarehouseFullDetail,
} from '../types/api';

const BASE = '/api';

// ---------------------------------------------------------------------------
// Auth token (managed by AuthContext, but read here too so non-React fetches
// also include the Authorization header).
// ---------------------------------------------------------------------------

const TOKEN_STORAGE_KEY = 'auth.access_token';
let _onUnauthorized: (() => void) | null = null;

export function getAuthToken(): string | null {
  try { return localStorage.getItem(TOKEN_STORAGE_KEY); } catch { return null; }
}

export function setAuthToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export function setOnUnauthorized(handler: (() => void) | null): void {
  _onUnauthorized = handler;
}

/** Build a query string, skipping undefined/null values. */
function qs(params: Record<string, string | number | undefined | null>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
    }
  }
  return parts.length ? `?${parts.join('&')}` : '';
}

/**
 * Recursively convert string-encoded numbers (from backend Decimal fields) to
 * actual JS numbers so Recharts can compute axis domains correctly.
 */
function parseNumericStrings(obj: unknown): unknown {
  if (obj === null || obj === undefined) return obj;
  if (Array.isArray(obj)) return obj.map(parseNumericStrings);
  if (typeof obj === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      out[k] = parseNumericStrings(v);
    }
    return out;
  }
  if (typeof obj === 'string' && obj !== '' && !isNaN(Number(obj)) && /^-?\d+(\.\d+)?$/.test(obj)) {
    return Number(obj);
  }
  return obj;
}

/** Build headers with Authorization if a token is set. */
function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getAuthToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

/** Generic authenticated fetch helper with error handling. */
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = { ...authHeaders(), ...((init?.headers as Record<string, string>) ?? {}) };
  const response = await fetch(url, { ...init, headers });
  if (response.status === 401) {
    setAuthToken(null);
    if (_onUnauthorized) _onUnauthorized();
    throw new Error('Unauthorized');
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const j = await response.json();
      detail = j.detail;
    } catch { /* not json */ }
    throw new Error(detail || `API error ${response.status}: ${response.statusText}`);
  }
  const json = await response.json();
  return parseNumericStrings(json) as T;
}

// ---------------------------------------------------------------------------
// Auth + admin
// ---------------------------------------------------------------------------

export interface AuthMe {
  id: number;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_email_verified: boolean;
  roles: string[];
  is_admin: boolean;
}

export interface LoginResponseT {
  access_token: string;
  token_type: string;
  user: AuthMe;
}

export async function authLogin(email: string, password: string): Promise<LoginResponseT> {
  return request(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
}

export async function authRegister(
  email: string,
  password: string,
  full_name?: string,
): Promise<{ user_id: number; email: string; verification_required: boolean; message: string }> {
  return request(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, full_name: full_name || undefined }),
  });
}

export async function authMe(): Promise<AuthMe> {
  return request(`${BASE}/auth/me`);
}

export async function authVerifyEmail(token: string): Promise<{ success: boolean; message: string }> {
  return request(`${BASE}/auth/verify-email?token=${encodeURIComponent(token)}`);
}

export async function authResendVerification(email: string): Promise<{ success: boolean; message: string }> {
  return request(`${BASE}/auth/resend-verification?email=${encodeURIComponent(email)}`, { method: 'POST' });
}

export async function authOauthProviders(): Promise<Record<string, boolean>> {
  return request(`${BASE}/auth/oauth/providers`);
}

/** Local-dev only: returns the bootstrap admin credentials when the backend
 *  has EXPOSE_DEV_CREDENTIALS=true. Resolves to null otherwise (404). */
export async function authDevCredentials(): Promise<{ email: string; password: string } | null> {
  try {
    return await request(`${BASE}/auth/dev-credentials`);
  } catch {
    return null;
  }
}

export async function authOauthAuthorize(provider: string): Promise<{ url: string; state: string }> {
  return request(`${BASE}/auth/oauth/${provider}/authorize`);
}

// Admin: users
export interface AdminUser {
  id: number;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_email_verified: boolean;
  created_at: string;
  roles: string[];
  oauth_providers: string[];
}

export async function adminListUsers(): Promise<AdminUser[]> {
  return request(`${BASE}/admin/users`);
}

export async function adminCreateUser(req: {
  email: string;
  password: string;
  full_name?: string;
  role_ids?: number[];
  is_email_verified?: boolean;
}): Promise<AdminUser> {
  return request(`${BASE}/admin/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}

export async function adminPatchUser(userId: number, patch: { is_active?: boolean; full_name?: string }): Promise<AdminUser> {
  return request(`${BASE}/admin/users/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
}

export async function adminDeleteUser(userId: number): Promise<void> {
  await request(`${BASE}/admin/users/${userId}`, { method: 'DELETE' }).catch(() => undefined);
}

export async function adminAssignRole(userId: number, roleId: number): Promise<AdminUser> {
  return request(`${BASE}/admin/users/${userId}/roles/${roleId}`, { method: 'POST' });
}

export async function adminUnassignRole(userId: number, roleId: number): Promise<AdminUser> {
  return request(`${BASE}/admin/users/${userId}/roles/${roleId}`, { method: 'DELETE' });
}

// Admin: roles
export interface AdminRole {
  id: number;
  name: string;
  description: string | null;
  is_system: boolean;
  filters: Record<string, unknown> | null;
  /** Feature keys this role grants. null = grants everything (system roles
   *  and legacy custom roles). Empty array = grants nothing. */
  features: string[] | null;
  user_count: number;
}

export interface AdminRolePayload {
  name: string;
  description?: string;
  filters?: Record<string, unknown>;
  features?: string[];
}

export interface AdminRolePatch {
  description?: string;
  filters?: Record<string, unknown>;
  features?: string[];
}

export async function adminListRoles(): Promise<AdminRole[]> {
  return request(`${BASE}/admin/roles`);
}

export async function adminCreateRole(req: AdminRolePayload): Promise<AdminRole> {
  return request(`${BASE}/admin/roles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}

export async function adminPatchRole(roleId: number, patch: AdminRolePatch): Promise<AdminRole> {
  return request(`${BASE}/admin/roles/${roleId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
}

export async function adminDeleteRole(roleId: number): Promise<void> {
  await request(`${BASE}/admin/roles/${roleId}`, { method: 'DELETE' }).catch(() => undefined);
}

export interface FilterDimensions {
  workspace_ids: string[];
  clouds: string[];
  billing_origins: string[];
  cluster_sources: string[];
  sku_names: string[];
}

export async function adminFilterDimensions(): Promise<FilterDimensions> {
  return request(`${BASE}/admin/filter-dimensions`);
}

export interface FeatureRegistryEntry {
  key: string;
  title: string;
  description: string;
  category: 'frontend' | 'backend';
  default_enabled: boolean;
}

export async function adminFeatureRegistry(): Promise<{ features: FeatureRegistryEntry[] }> {
  return request(`${BASE}/admin/feature-registry`);
}

// ---------------------------------------------------------------------------
// Admin: database explorer
// ---------------------------------------------------------------------------

export interface DbColumn {
  name: string;
  type: string;
  nullable: boolean;
}

export interface DbObject {
  schema_name: string;
  name: string;
  kind: 'table' | 'view';
  approx_rows: number;
  columns: DbColumn[];
}

export interface DbQueryResult {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
}

export async function dbListObjects(): Promise<DbObject[]> {
  return request(`${BASE}/admin/db/objects`);
}

export async function dbRunQuery(sql: string, maxRows = 1000): Promise<DbQueryResult> {
  return request(`${BASE}/admin/db/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sql, max_rows: maxRows }),
  });
}

// ---------------------------------------------------------------------------
// Billing endpoints
// ---------------------------------------------------------------------------

export async function fetchUsageSummary(
  startDate?: string,
  endDate?: string,
  groupBy: 'day' | 'week' | 'month' = 'day',
): Promise<ApiResponse<UsageSummaryItem>> {
  const query = qs({ start_date: startDate, end_date: endDate, group_by: groupBy });
  return request(`${BASE}/billing/usage-summary${query}`);
}

export async function fetchUsageSummaryBySku(
  startDate?: string,
  endDate?: string,
  groupBy: 'day' | 'week' | 'month' = 'day',
  topSkus: number = 5,
): Promise<UsageSummaryBySkuResponse> {
  const query = qs({
    start_date: startDate,
    end_date: endDate,
    group_by: groupBy,
    top_skus: topSkus,
  });
  return request(`${BASE}/billing/usage-summary-by-sku${query}`);
}

export async function fetchByDimension(
  dimension: 'sku' | 'workspace' | 'origin' | 'usage-type' | 'cloud',
  startDate?: string,
  endDate?: string,
): Promise<ApiResponse<BreakdownItem>> {
  const query = qs({ start_date: startDate, end_date: endDate });
  return request(`${BASE}/billing/by-${dimension}${query}`);
}

export async function fetchByUser(
  startDate?: string,
  endDate?: string,
  limit?: number,
): Promise<ApiResponse<UserCostItem>> {
  const query = qs({ start_date: startDate, end_date: endDate, limit });
  return request(`${BASE}/billing/by-user${query}`);
}

export async function fetchDailyTrend(
  startDate?: string,
  endDate?: string,
  skuName?: string,
  workspaceId?: string,
  runAs?: string,
): Promise<ApiResponse<DailyTrendItem>> {
  const query = qs({
    start_date: startDate,
    end_date: endDate,
    sku_name: skuName,
    workspace_id: workspaceId,
    run_as: runAs,
  });
  return request(`${BASE}/billing/daily-trend${query}`);
}

export async function fetchUserUtilization(
  runAs: string,
  startDate?: string,
  endDate?: string,
): Promise<UserUtilizationResponse> {
  const query = qs({ run_as: runAs, start_date: startDate, end_date: endDate });
  return request(`${BASE}/billing/user-utilization${query}`);
}

export async function fetchBySkuUser(
  startDate?: string,
  endDate?: string,
  topSkus: number = 10,
  topUsers: number = 10,
): Promise<SkuUserMatrixResponse> {
  const query = qs({
    start_date: startDate,
    end_date: endDate,
    top_skus: topSkus,
    top_users: topUsers,
  });
  return request(`${BASE}/billing/by-sku-user${query}`);
}

export async function fetchTopSkus(
  startDate?: string,
  endDate?: string,
  limit?: number,
): Promise<ApiResponse<TopSkuItem>> {
  const query = qs({ start_date: startDate, end_date: endDate, limit });
  return request(`${BASE}/billing/top-skus${query}`);
}

// ---------------------------------------------------------------------------
// Compute endpoints
// ---------------------------------------------------------------------------

export async function fetchClusters(
  params: ClusterListParams = {},
): Promise<PaginatedResponse<ClusterDetail>> {
  const query = qs({
    page: params.page ?? 1,
    page_size: params.pageSize ?? 20,
    search: params.search,
    workspace_id: params.workspaceId,
    cluster_source: params.clusterSource,
    data_security_mode: params.dataSecurityMode,
    node_family: params.nodeFamily,
    has_gpu: params.hasGpu == null ? undefined : String(params.hasGpu),
    min_vcpus: params.minVcpus,
    min_memory_gb: params.minMemoryGb,
    sort_by: params.sortBy,
    sort_order: params.sortOrder,
  });
  return request(`${BASE}/compute/clusters${query}`);
}

export async function fetchWarehouses(
  page: number = 1,
  pageSize: number = 20,
  search?: string,
): Promise<PaginatedResponse<WarehouseDetail>> {
  const query = qs({ page, page_size: pageSize, search });
  return request(`${BASE}/compute/warehouses${query}`);
}

export async function fetchClusterDetail(clusterId: string): Promise<ClusterFullDetail> {
  return request(`${BASE}/compute/clusters/${encodeURIComponent(clusterId)}`);
}

export async function fetchClusterCost(
  clusterId: string,
  startDate?: string,
  endDate?: string,
): Promise<ComputeCostResponse> {
  const query = qs({ cluster_id: clusterId, start_date: startDate, end_date: endDate });
  return request(`${BASE}/compute/cluster-cost${query}`);
}

export async function fetchWarehouseDetail(warehouseId: string): Promise<WarehouseFullDetail> {
  return request(`${BASE}/compute/warehouses/${encodeURIComponent(warehouseId)}`);
}

export async function fetchWarehouseCost(
  warehouseId: string,
  startDate?: string,
  endDate?: string,
): Promise<ComputeCostResponse> {
  const query = qs({ warehouse_id: warehouseId, start_date: startDate, end_date: endDate });
  return request(`${BASE}/compute/warehouse-cost${query}`);
}

// ---------------------------------------------------------------------------
// Analytics endpoints
// ---------------------------------------------------------------------------

export async function fetchCostAnomalies(): Promise<ApiResponse<CostAnomalyItem>> {
  return request(`${BASE}/analytics/cost-anomalies`);
}

export async function fetchForecast(): Promise<ApiResponse<ForecastItem>> {
  return request(`${BASE}/analytics/forecast`);
}

export async function fetchMoMGrowth(): Promise<ApiResponse<MoMGrowthItem>> {
  return request(`${BASE}/analytics/mom-growth`);
}

export async function fetchCostMatrix(
  startDate?: string,
  endDate?: string,
): Promise<CostMatrixResponse> {
  const query = qs({ start_date: startDate, end_date: endDate });
  return request(`${BASE}/analytics/cost-breakdown-matrix${query}`);
}

export async function fetchUtilization(
  startDate?: string,
  endDate?: string,
): Promise<ApiResponse<UtilizationItem>> {
  const query = qs({ start_date: startDate, end_date: endDate });
  return request(`${BASE}/analytics/utilization-summary${query}`);
}

export async function fetchKPISummary(
  startDate: string,
  endDate: string,
): Promise<KPISummary> {
  const query = qs({ start_date: startDate, end_date: endDate });
  return request(`${BASE}/analytics/kpi-summary${query}`);
}

// ---------------------------------------------------------------------------
// SKU & Billing-Origin analytics
// ---------------------------------------------------------------------------

import type {
  ConcentrationResponse,
  DrillResponse,
  OriginLeaderboardResponse,
  PivotResponse,
  ServerlessShareResponse,
  SkuLeaderboardResponse,
  SkuOriginTreemapResponse,
  TrendResponse,
} from '../types/api';

const SO_BASE = `${BASE}/analytics/sku-origin`;

export async function fetchSoTreemap(
  startDate?: string,
  endDate?: string,
  limit = 200,
): Promise<SkuOriginTreemapResponse> {
  return request(`${SO_BASE}/treemap${qs({ start_date: startDate, end_date: endDate, limit })}`);
}

export async function fetchSoSkuLeaderboard(
  startDate?: string,
  endDate?: string,
  limit = 15,
  buckets = 30,
): Promise<SkuLeaderboardResponse> {
  return request(`${SO_BASE}/sku-leaderboard${qs({ start_date: startDate, end_date: endDate, limit, buckets })}`);
}

export async function fetchSoOriginLeaderboard(
  startDate?: string,
  endDate?: string,
  limit = 15,
  buckets = 30,
): Promise<OriginLeaderboardResponse> {
  return request(`${SO_BASE}/origin-leaderboard${qs({ start_date: startDate, end_date: endDate, limit, buckets })}`);
}

export async function fetchSoSkuWorkspaceMatrix(
  startDate?: string,
  endDate?: string,
  topSkus = 15,
  topWorkspaces = 15,
): Promise<PivotResponse> {
  return request(`${SO_BASE}/sku-workspace-matrix${qs({ start_date: startDate, end_date: endDate, top_skus: topSkus, top_workspaces: topWorkspaces })}`);
}

export async function fetchSoOriginWorkspaceMatrix(
  startDate?: string,
  endDate?: string,
  topOrigins = 15,
  topWorkspaces = 15,
): Promise<PivotResponse> {
  return request(`${SO_BASE}/origin-workspace-matrix${qs({ start_date: startDate, end_date: endDate, top_origins: topOrigins, top_workspaces: topWorkspaces })}`);
}

export async function fetchSoSkuIdentity(
  startDate?: string,
  endDate?: string,
  topSkus = 15,
  topIdentities = 15,
): Promise<PivotResponse> {
  return request(`${SO_BASE}/sku-identity${qs({ start_date: startDate, end_date: endDate, top_skus: topSkus, top_identities: topIdentities })}`);
}

export async function fetchSoOriginIdentity(
  startDate?: string,
  endDate?: string,
  topOrigins = 15,
  topIdentities = 15,
): Promise<PivotResponse> {
  return request(`${SO_BASE}/origin-identity${qs({ start_date: startDate, end_date: endDate, top_origins: topOrigins, top_identities: topIdentities })}`);
}

export async function fetchSoConcentration(
  startDate?: string,
  endDate?: string,
  top = 8,
): Promise<ConcentrationResponse> {
  return request(`${SO_BASE}/concentration${qs({ start_date: startDate, end_date: endDate, top })}`);
}

export async function fetchSoTrend(opts: {
  startDate?: string;
  endDate?: string;
  skuName?: string;
  billingOrigin?: string;
  topWorkspaces?: number;
}): Promise<TrendResponse> {
  return request(`${SO_BASE}/trend${qs({
    start_date: opts.startDate,
    end_date: opts.endDate,
    sku_name: opts.skuName,
    billing_origin: opts.billingOrigin,
    top_workspaces: opts.topWorkspaces ?? 5,
  })}`);
}

export async function fetchSoServerlessShare(
  startDate?: string,
  endDate?: string,
  limit = 20,
): Promise<ServerlessShareResponse> {
  return request(`${SO_BASE}/serverless-share${qs({ start_date: startDate, end_date: endDate, limit })}`);
}

export async function fetchSoDrilldown(opts: {
  startDate?: string;
  endDate?: string;
  skuName?: string;
  billingOrigin?: string;
}): Promise<DrillResponse> {
  return request(`${SO_BASE}/drilldown${qs({
    start_date: opts.startDate,
    end_date: opts.endDate,
    sku_name: opts.skuName,
    billing_origin: opts.billingOrigin,
  })}`);
}

// ---------------------------------------------------------------------------
// Metadata lookups (workspace_id -> name etc.)
// ---------------------------------------------------------------------------

export interface WorkspaceMeta {
  workspace_id: string;
  workspace_name: string | null;
  workspace_url: string | null;
  status: string | null;
}

export async function fetchWorkspaceMeta(): Promise<WorkspaceMeta[]> {
  const body = await request<{ data: WorkspaceMeta[] }>(`${BASE}/metadata/workspaces`);
  return body.data;
}

// ---------------------------------------------------------------------------
// Admin endpoints
// ---------------------------------------------------------------------------

export interface DataSourceStatus {
  source: string;
  databricks_host: string | null;
  databricks_connected: boolean;
}

export interface TableCounts {
  billing_usage: number;
  list_prices: number;
  clusters: number;
  warehouses: number;
  jobs: number;
}

export interface IngestResult {
  source: string;
  tables_ingested: Record<string, number>;
  duration_seconds: number;
}

export interface ExtractionResult {
  tables_extracted: Record<string, number>;
  tables_ingested: Record<string, number>;
  parquet_saved: boolean;
  duration_seconds: number;
}

export async function fetchDataSourceStatus(): Promise<DataSourceStatus> {
  return request(`${BASE}/admin/status`);
}

export async function fetchTableCounts(): Promise<TableCounts> {
  return request(`${BASE}/admin/table-counts`);
}

export type ExtractGroup = 'billing' | 'compute' | 'query_history' | 'meta' | 'lineage' | 'audit' | 'node_pool';
export const ALL_EXTRACT_GROUPS: ExtractGroup[] = ['billing', 'compute', 'query_history', 'meta', 'lineage', 'audit', 'node_pool'];

export async function triggerExtract(
  startDate: string = '2024-01-01',
  endDate?: string,
  replace: boolean = false,
  mode: 'full' | 'incremental' = 'full',
  groups: ExtractGroup[] = ALL_EXTRACT_GROUPS,
  tableLineageDaysBack: number = 14,
  columnLineageDaysBack: number = 7,
  // Per-table lookbacks for the audit + node_pool groups. node_types and
  // instance_pools are reference tables and don't take a knob.
  auditEventsDaysBack: number = 3,
  assistantEventsDaysBack: number = 30,
  nodeTimelineDaysBack: number = 3,
  warehouseEventsDaysBack: number = 30,
  instanceEventsDaysBack: number = 14,
): Promise<ExtractionResult> {
  const params = new URLSearchParams();
  params.set('mode', mode);
  params.set('start_date', startDate);
  if (endDate) params.set('end_date', endDate);
  params.set('replace', replace ? 'true' : 'false');
  params.set('save_parquet', 'true');
  for (const g of groups) params.append('groups', g);
  params.set('table_lineage_days_back',     String(tableLineageDaysBack));
  params.set('column_lineage_days_back',    String(columnLineageDaysBack));
  params.set('audit_events_days_back',      String(auditEventsDaysBack));
  params.set('assistant_events_days_back',  String(assistantEventsDaysBack));
  params.set('node_timeline_days_back',     String(nodeTimelineDaysBack));
  params.set('warehouse_events_days_back',  String(warehouseEventsDaysBack));
  params.set('instance_events_days_back',   String(instanceEventsDaysBack));
  const response = await fetch(`${BASE}/admin/extract?${params.toString()}`, { method: 'POST', headers: authHeaders() });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `API error ${response.status}`);
  }
  return response.json();
}

export async function triggerIngestParquet(
  replace: boolean = false,
): Promise<IngestResult> {
  const query = qs({ replace: replace ? 'true' : 'false' });
  const response = await fetch(`${BASE}/admin/ingest-parquet${query}`, { method: 'POST', headers: authHeaders() });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `API error ${response.status}`);
  }
  return response.json();
}

export async function triggerSeedDemo(replace: boolean = false): Promise<IngestResult> {
  const query = qs({ replace: replace ? 'true' : 'false' });
  const response = await fetch(`${BASE}/admin/seed-demo${query}`, { method: 'POST', headers: authHeaders() });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `API error ${response.status}`);
  }
  return response.json();
}

export interface QueryIntelResult {
  source_file: string;
  rows_processed: number;
  statements_inserted: number;
  tables_extracted: number;
  columns_extracted: number;
  tags_extracted: number;
  params_extracted: number;
  errors_extracted: number;
  parse_failures: number;
  duration_seconds: number;
}

// ---------------------------------------------------------------------------
// Data-isolation / view-mode / background jobs
// ---------------------------------------------------------------------------

export type DataOrigin = 'real' | 'demo';

export interface ViewMode { mode: DataOrigin; }

export interface BackgroundJob {
  id: number;
  kind: string;
  status: 'queued' | 'running' | 'success' | 'failed' | 'canceled' | 'lost';
  progress_pct: number;
  current_step: number | null;
  total_steps: number | null;
  message: string | null;
  started_at: string;
  ended_at: string | null;
  error_message: string | null;
  result_json: Record<string, any> | null;
  params_json: Record<string, any> | null;
  cancel_requested: boolean;
}

export async function getViewMode(): Promise<ViewMode> {
  const r = await fetch(`${BASE}/data-ops/me/view-mode`, { headers: authHeaders() });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `API error ${r.status}`);
  return r.json();
}

export async function setViewMode(mode: DataOrigin): Promise<ViewMode> {
  const r = await fetch(`${BASE}/data-ops/me/view-mode`, {
    method: 'PATCH',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `API error ${r.status}`);
  return r.json();
}

export async function listJobs(hours = 24, limit = 50): Promise<BackgroundJob[]> {
  const r = await fetch(`${BASE}/data-ops/jobs${qs({ hours, limit })}`, { headers: authHeaders() });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `API error ${r.status}`);
  return r.json();
}

export async function cancelJob(id: number): Promise<BackgroundJob> {
  const r = await fetch(`${BASE}/data-ops/jobs/${id}/cancel`, { method: 'POST', headers: authHeaders() });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `API error ${r.status}`);
  return r.json();
}

async function _dataOpsPost(path: string, body: any): Promise<{ job_id: number }> {
  const r = await fetch(`${BASE}/data-ops/${path}`, {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `API error ${r.status}`);
  return r.json();
}

export const dataOps = {
  softDelete: (origin: DataOrigin) => _dataOpsPost('soft-delete', { origin }),
  hardDelete: (origin: DataOrigin) => _dataOpsPost('hard-delete', { origin }),
  restore:    (origin: DataOrigin) => _dataOpsPost('restore', { origin }),
  incrementalLoad: (data_origin: DataOrigin) =>
    _dataOpsPost('incremental-load', {
      file_prefix: data_origin === 'demo' ? 'demo_' : '',
      data_origin,
    }),
};

export type SparkMode = 'jdbc_views' | 'materialized';

export interface EngineState {
  engine: 'duckdb' | 'spark';
  // null when engine='duckdb'.
  spark_mode?: SparkMode | null;
}

export interface MaterializeResult {
  counts: Record<string, number>;
  duration_seconds: number;
}

export async function triggerMaterializePostgresToSpark(): Promise<MaterializeResult> {
  const response = await fetch(`${BASE}/admin/materialize-postgres-to-spark`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `API error ${response.status}`);
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Spark SQL editor — admin-only, over spark-warehouse
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Meta Explorer — Unity Catalog browser over databricks_meta
// ---------------------------------------------------------------------------

export interface MetaStats {
  catalogs: number;
  databases: number;
  tables: number;
  columns: number;
  last_extract: string | null;
}
export interface CatalogRow {
  catalog: string;
  database_count: number;
  table_count: number;
  column_count: number;
}
export interface DatabaseRow {
  catalog: string;
  database: string;
  table_count: number;
  column_count: number;
}
export interface TableRow {
  catalog: string;
  database: string;
  table_name: string;
  table_type: string | null;
  table_owner: string | null;
  table_comment: string | null;
  column_count: number;
}
export interface ColumnRow {
  col_name: string;
  data_type: string | null;
  comment: string | null;
}
export interface TableDetail extends Omit<TableRow, 'column_count'> {
  columns: ColumnRow[];
}
export interface SearchHit {
  catalog: string;
  database: string;
  table_name: string;
  col_name: string | null;
  data_type: string | null;
  table_comment: string | null;
  matched_in: 'table' | 'column' | 'comment';
}

async function _metaGet<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const queryStr = params ? qs(params) : '';
  const r = await fetch(`${BASE}/meta${path}${queryStr}`, { headers: authHeaders() });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `API error ${r.status}`);
  return r.json();
}

export interface ExportTableRow {
  catalog: string;
  database: string;
  table_name: string;
  table_type: string | null;
  table_owner: string | null;
  table_comment: string | null;
  column_count: number;
}
export interface ExportColumnRow {
  catalog: string;
  database: string;
  table_name: string;
  table_type: string | null;
  table_owner: string | null;
  table_comment: string | null;
  col_name: string;
  data_type: string | null;
  comment: string | null;
}

// ---------------------------------------------------------------------------
// Feature state — per-user effective feature map computed from the calling
// user's roles. Used by useFeatures() and the RequireFeature route guard.
// The matrix itself is edited on the Role create/edit page.
// ---------------------------------------------------------------------------

export interface FeatureStateMap {
  features: Record<string, boolean>;
}

export async function fetchFeatureState(): Promise<FeatureStateMap> {
  const r = await fetch(`${BASE}/features/state`, { headers: authHeaders() });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `API error ${r.status}`);
  return r.json();
}


// ---------------------------------------------------------------------------
// Lineage — system.access.table_lineage / column_lineage
// ---------------------------------------------------------------------------

export interface LineageBreakdownEntry { label: string; count: number; }

export interface LineageStats {
  table_edges: number;
  column_edges: number;
  distinct_tables: number;
  distinct_columns: number;
  distinct_entities: number;
  last_event: string | null;
  direct_edges: number;
  indirect_edges: number;
  read_only_events: number;
  write_only_events: number;
  read_write_events: number;
  by_entity_type: LineageBreakdownEntry[];
  by_source_type: LineageBreakdownEntry[];
  by_target_type: LineageBreakdownEntry[];
  column_distinct_tables: number;
  column_distinct_entities: number;
  column_last_event: string | null;
}

export interface LineageNeighbour {
  full_name: string;
  catalog: string | null;
  database: string | null;
  table_name: string | null;
  type: string | null;
  edge_count: number;
  sample_entities: string[];
}

export interface TableLineageGraph {
  center: string;
  upstream: LineageNeighbour[];
  downstream: LineageNeighbour[];
}

export interface ColumnLineageNeighbour {
  full_name: string;
  column_name: string;
  edge_count: number;
}

export interface ColumnLineageGraph {
  center_table: string;
  center_column: string;
  upstream: ColumnLineageNeighbour[];
  downstream: ColumnLineageNeighbour[];
}

export interface LineageTopEntry { label: string; edge_count: number; }
export interface LineageTops {
  top_sources:   LineageTopEntry[];
  top_targets:   LineageTopEntry[];
  top_entities:  LineageTopEntry[];
  top_columns:   LineageTopEntry[];
  orphan_tables:  string[];
  terminal_tables: string[];
}

export interface ColumnLineageTops {
  most_fanned_out:    LineageTopEntry[];
  most_depended_on:   LineageTopEntry[];
  tables_by_col_edges: LineageTopEntry[];
  top_entities:       LineageTopEntry[];
}

export interface LineageSearchHit {
  full_name: string;
  table_edges_in: number;
  table_edges_out: number;
}

// ---------------------------------------------------------------------------
// Audit dashboard (Meta Explorer > Audit) — system.access.audit + assistant_events
// ---------------------------------------------------------------------------

export interface AuditBreakdownEntry { label: string; count: number; }

export interface AuditStats {
  audit_events: number;
  assistant_events: number;
  distinct_users: number;
  distinct_actions: number;
  distinct_services: number;
  error_events: number;
  last_event: string | null;
  by_service: AuditBreakdownEntry[];
  by_audit_level: AuditBreakdownEntry[];
  by_status_class: AuditBreakdownEntry[];
  top_actions: AuditBreakdownEntry[];
  top_users: AuditBreakdownEntry[];
  top_assistant_users: AuditBreakdownEntry[];
  assistant_distinct_users: number;
  assistant_last_event: string | null;
}

export interface AuditEventOut {
  event_time: string | null;
  user_identity_email: string | null;
  service_name: string | null;
  action_name: string | null;
  audit_level: string | null;
  response_status_code: number | null;
  response_error_message: string | null;
  source_ip_address: string | null;
  workspace_id: string | null;
  request_id: string | null;
  event_id: string | null;
}

export interface AuditSearchHit extends AuditEventOut { matched_in: string; }


// Node Pool dashboard (Meta Explorer > Node Pool) — system.compute.*
export interface NodePoolBreakdownEntry { label: string; count: number; }
export interface NodePoolStats {
  node_timeline_rows: number;
  warehouse_event_rows: number;
  instance_event_rows: number;
  node_type_rows: number;
  instance_pool_rows: number;
  distinct_clusters_in_timeline: number;
  distinct_instances_in_timeline: number;
  distinct_warehouses_in_events: number;
  distinct_pools_referenced: number;
  last_node_timeline: string | null;
  last_warehouse_event: string | null;
  last_instance_event: string | null;
  by_warehouse_event_type: NodePoolBreakdownEntry[];
  by_instance_event_type:  NodePoolBreakdownEntry[];
  by_node_type_category:   NodePoolBreakdownEntry[];
}

export interface NodePoolUtilizationRow {
  cluster_id: string | null;
  sample_count: number;
  avg_cpu_user_percent: number | null;
  avg_cpu_system_percent: number | null;
  avg_mem_used_percent: number | null;
  max_cpu_user_percent: number | null;
  max_mem_used_percent: number | null;
  last_sample: string | null;
}

export interface WarehouseEventOut {
  event_time: string | null;
  warehouse_id: string | null;
  event_type: string | null;
  cluster_count: number | null;
  workspace_id: string | null;
}

export interface InstanceEventOut {
  event_time: string | null;
  cluster_id: string | null;
  instance_id: string | null;
  instance_pool_id: string | null;
  event_type: string | null;
  node_type: string | null;
  workspace_id: string | null;
}

export interface NodeTypeOut {
  node_type: string | null;
  core_count: number | null;
  memory_mb: number | null;
  gpu_count: number | null;
  category: string | null;
}

export interface InstancePoolOut {
  instance_pool_id: string | null;
  instance_pool_name: string | null;
  node_type: string | null;
  min_idle_instances: number | null;
  max_capacity: number | null;
  idle_instance_autotermination_minutes: number | null;
  enable_elastic_disk: boolean | null;
  workspace_id: string | null;
  create_time: string | null;
  change_time: string | null;
}


export const metaExplorer = {
  stats: () => _metaGet<MetaStats>('/stats'),
  catalogs: () => _metaGet<CatalogRow[]>('/catalogs'),
  databases: (catalog: string) => _metaGet<DatabaseRow[]>('/databases', { catalog }),
  tables: (catalog: string, database: string) => _metaGet<TableRow[]>('/tables', { catalog, database }),
  tableDetail: (catalog: string, database: string, table_name: string) =>
    _metaGet<TableDetail>('/table-detail', { catalog, database, table_name }),
  search: (q: string, limit = 50) => _metaGet<SearchHit[]>('/search', { q, limit }),
  exportCatalogs: () => _metaGet<CatalogRow[]>('/export/catalogs'),
  exportTables:   () => _metaGet<ExportTableRow[]>('/export/tables'),
  exportColumns:  () => _metaGet<ExportColumnRow[]>('/export/columns'),

  lineageStats:  () => _metaGet<LineageStats>('/lineage/stats'),
  lineageSearch: (q: string, limit = 20) =>
    _metaGet<LineageSearchHit[]>('/lineage/search', { q, limit }),
  tableGraph:    (full_name: string, limit = 25, direct_only = false) =>
    _metaGet<TableLineageGraph>('/lineage/table-graph', {
      full_name, limit, direct_only: direct_only ? 'true' : 'false',
    }),
  columnGraph:   (full_name: string, column_name: string, limit = 25) =>
    _metaGet<ColumnLineageGraph>('/lineage/column-graph', { full_name, column_name, limit }),
  lineageTops:   (limit = 15) => _metaGet<LineageTops>('/lineage/tops', { limit }),
  lineageColumnTops: (limit = 15) => _metaGet<ColumnLineageTops>('/lineage/column-tops', { limit }),

  auditStats: (limit = 15) => _metaGet<AuditStats>('/audit/stats', { limit }),
  auditRecent: (params: { limit?: number; errors_only?: boolean; service?: string; user_email?: string } = {}) =>
    _metaGet<AuditEventOut[]>('/audit/recent', {
      limit: params.limit ?? 50,
      errors_only: params.errors_only ? 'true' : undefined,
      service: params.service,
      user_email: params.user_email,
    }),
  auditSearch: (q: string, limit = 50) => _metaGet<AuditSearchHit[]>('/audit/search', { q, limit }),

  nodePoolStats:        () => _metaGet<NodePoolStats>('/node-pool/stats'),
  nodePoolUtilization:  (limit = 25) =>
    _metaGet<NodePoolUtilizationRow[]>('/node-pool/utilization', { limit }),
  nodePoolWarehouseEvents: (limit = 50) =>
    _metaGet<WarehouseEventOut[]>('/node-pool/warehouse-events', { limit }),
  nodePoolInstanceEvents:  (limit = 50) =>
    _metaGet<InstanceEventOut[]>('/node-pool/instance-events', { limit }),
  nodePoolNodeTypes:       () => _metaGet<NodeTypeOut[]>('/node-pool/node-types'),
  nodePoolInstancePools:   () => _metaGet<InstancePoolOut[]>('/node-pool/instance-pools'),
};


export interface SparkSessionInfo {
  reachable: boolean;
  remote: string;
  spark_version: string | null;
  warehouse_dir: string | null;
  error: string | null;
}

export interface SparkColumnInfo {
  name: string;
  type: string;
  nullable: boolean;
}

export interface SparkTable {
  catalog: string;
  database: string;
  name: string;
  kind: string;
  columns: SparkColumnInfo[];
}

export interface SparkQueryResponse {
  columns: string[];
  rows: Record<string, any>[];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
}

async function _sparkGet<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}/spark-sql${path}`, { headers: authHeaders() });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `API error ${r.status}`);
  return r.json();
}

export const sparkSql = {
  session: () => _sparkGet<SparkSessionInfo>('/session'),
  tables: () => _sparkGet<SparkTable[]>('/tables'),
  query: async (sql: string, max_rows = 1000): Promise<SparkQueryResponse> => {
    const r = await fetch(`${BASE}/spark-sql/query`, {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql, max_rows }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `API error ${r.status}`);
    return r.json();
  },
};

export async function fetchEngine(): Promise<EngineState> {
  const response = await fetch(`${BASE}/admin/engine`, { headers: authHeaders() });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `API error ${response.status}`);
  }
  return response.json();
}

export async function setEngine(
  engine: 'duckdb' | 'spark',
  spark_mode?: SparkMode,
): Promise<EngineState> {
  const body: Record<string, string> = { engine };
  if (engine === 'spark' && spark_mode) body.spark_mode = spark_mode;
  const response = await fetch(`${BASE}/admin/engine`, {
    method: 'PATCH',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `API error ${response.status}`);
  }
  return response.json();
}

export async function triggerExtractQueryIntel(useDemo: boolean = true): Promise<QueryIntelResult> {
  const query = qs({ use_demo: useDemo ? 'true' : 'false' });
  const response = await fetch(`${BASE}/admin/extract-query-intel${query}`, { method: 'POST', headers: authHeaders() });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `API error ${response.status}`);
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Live progress map for Data Management operations.
//
// One entry per "kind" (e.g. `extract`, `ingest-parquet`, `seed-demo`,
// `query-intel-real`, `transform-lineage-demo`). Polled by the page while
// any mutation is in flight.
// ---------------------------------------------------------------------------

export interface ProgressEntry {
  kind: string;
  label: string;
  status: 'running' | 'success' | 'failed' | 'cancelled';
  started_at: number;
  finished_at: number | null;
  current_step: number;
  total_steps: number;
  last_message: string;
  error: string | null;
  summary: Record<string, unknown> | null;
  elapsed_seconds: number;
  // True once the user has clicked Cancel but the run hasn't finished
  // tearing down yet. UI shows a "Cancelling…" label in that interval.
  cancel_requested: boolean;
}

export async function fetchProgress(): Promise<Record<string, ProgressEntry>> {
  const r = await fetch(`${BASE}/data-ops/progress`, { headers: authHeaders() });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `API error ${r.status}`);
  return r.json();
}

export async function cancelProgress(kind: string): Promise<void> {
  const r = await fetch(`${BASE}/data-ops/progress/${encodeURIComponent(kind)}/cancel`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || `API error ${r.status}`);
  }
}

export interface LineageRollupResult {
  data_origin: string;
  rollup_rows: number;
  table_edges: number;
  column_edges: number;
  direct_edges: number;
  indirect_edges: number;
  distinct_entities: number;
  last_event: string | null;
  duration_seconds: number;
}

export async function triggerTransformLineage(useDemo: boolean): Promise<LineageRollupResult> {
  const query = qs({ use_demo: useDemo ? 'true' : 'false' });
  const response = await fetch(`${BASE}/admin/transform-lineage${query}`, { method: 'POST', headers: authHeaders() });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `API error ${response.status}`);
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Query Intel analytics — all endpoints under /api/query-intel/*
// All return either an object or an array of rows; shape is documented at
// the call site. We don't fight TypeScript over JSON-y row shapes — pages
// use `any` for these.
// ---------------------------------------------------------------------------

export interface QiOverview {
  total_statements: number;
  distinct_users: number;
  distinct_workspaces: number;
  success_rate: number;
  failed_count: number;
  canceled_count: number;
  median_duration_ms: number | null;
  p95_duration_ms: number | null;
  cache_hit_rate: number;
  serverless_share: number;
  genie_query_count: number;
  dashboard_query_count: number;
  job_query_count: number;
  notebook_query_count: number;
  has_data: boolean;
  last_extract_at: string | null;
  last_extract_source: string | null;
  date_min: string | null;
  date_max: string | null;
}

async function _qiGet<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const queryStr = params ? qs(params) : '';
  const response = await fetch(`${BASE}/query-intel${path}${queryStr}`, { headers: authHeaders() });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `API error ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const qi = {
  overview: (p?: { start_date?: string; end_date?: string; workspace_id?: string }) =>
    _qiGet<QiOverview>('/overview', p),
  expensiveQueries: (limit = 50) => _qiGet<any[]>('/platform/expensive-queries', { limit }),
  fullScans: (limit = 50) => _qiGet<any[]>('/platform/full-scans', { limit }),
  spillLeaders: (limit = 20) => _qiGet<any[]>('/platform/spill-leaders', { limit }),
  errorTrends: () => _qiGet<any[]>('/platform/error-trends'),
  errorCategories: () => _qiGet<any[]>('/platform/error-categories'),
  capacityQueueing: () => _qiGet<any[]>('/platform/capacity-queueing'),
  cacheEffectiveness: () => _qiGet<any[]>('/platform/cache-effectiveness'),
  topTables: (limit = 20, role?: string) => _qiGet<any[]>('/catalog/top-tables', { limit, role }),
  topColumns: (limit = 20, role?: string) => _qiGet<any[]>('/catalog/top-columns', { limit, role }),
  partitioningCandidates: (limit = 20) => _qiGet<any[]>('/catalog/partitioning-candidates', { limit }),
  zombieTables: (limit = 20) => _qiGet<any[]>('/catalog/zombie-tables', { limit }),
  tagCoverage: () => _qiGet<any>('/finops/tag-coverage'),
  failedCost: () => _qiGet<any>('/finops/failed-cost'),
  sourceAttribution: () => _qiGet<any[]>('/finops/source-attribution'),
  projectSearch: (keyword: string, start_date?: string, end_date?: string) =>
    _qiGet<any>('/finops/project-search', { keyword, start_date, end_date }),
  // Executive — date range + grain. Pass empty strings (or undefined) to
  // get the un-filtered defaults; the backend treats NULL as open-ended.
  adoptionTrend: (start_date?: string, end_date?: string, grain?: string) =>
    _qiGet<any[]>('/executive/adoption-trend', { start_date, end_date, grain }),
  executiveServerlessShare: (start_date?: string, end_date?: string, grain?: string) =>
    _qiGet<any[]>('/executive/serverless-share', { start_date, end_date, grain }),
  reliability: (start_date?: string, end_date?: string, grain?: string) =>
    _qiGet<any[]>('/executive/reliability', { start_date, end_date, grain }),
  jobFailureRates: (limit = 20) => _qiGet<any[]>('/dataeng/job-failure-rates', { limit }),
  slowestPipelines: (limit = 20) => _qiGet<any[]>('/dataeng/slowest-pipelines', { limit }),
  compileHeavy: (limit = 20) => _qiGet<any[]>('/dataeng/compile-heavy', { limit }),
  slowestDashboards: (limit = 20) => _qiGet<any[]>('/bi/slowest-dashboards', { limit }),
  vendorFootprint: () => _qiGet<any[]>('/bi/vendor-footprint'),
  selectStarDashboards: (limit = 20) => _qiGet<any[]>('/bi/select-star-dashboards', { limit }),
  notebookActivity: (limit = 20) => _qiGet<any[]>('/datascience/notebook-activity', { limit }),
  genieAdoption: () => _qiGet<any[]>('/datascience/genie-adoption'),
  permissionDenied: (limit = 50) => _qiGet<any[]>('/security/permission-denied', { limit }),
  offHoursPii: (limit = 50) => _qiGet<any[]>('/security/off-hours-pii', { limit }),
  bulkExport: (limit = 50) => _qiGet<any[]>('/security/bulk-export', { limit }),
  grantRevoke: (limit = 50) => _qiGet<any[]>('/security/grant-revoke', { limit }),
  driverVersions: () => _qiGet<any[]>('/security/driver-versions'),
  delegatedExecution: (limit = 50) => _qiGet<any[]>('/security/delegated-execution', { limit }),
  userFootprint: (limit = 30) => _qiGet<any[]>('/devex/user-footprint', { limit }),
  toolMix: () => _qiGet<any[]>('/devex/tool-mix'),
  syntaxErrors: (limit = 20) => _qiGet<any[]>('/devex/syntax-errors', { limit }),
  sqlFeatureMix: () => _qiGet<any>('/cross/sql-feature-mix'),
  hourOfDay: () => _qiGet<any[]>('/cross/hour-of-day'),
  duplicateQueries: (limit = 20) => _qiGet<any[]>('/cross/duplicate-queries', { limit }),
  statementTypeMix: () => _qiGet<any[]>('/cross/statement-type-mix'),
};

// ---------------------------------------------------------------------------
// Chatbot endpoints
// ---------------------------------------------------------------------------

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

export interface LlmCall {
  name: string;
  system_prompt: string;
  user_message: string;
  raw_response: string;
  elapsed_seconds: number;
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
  total_elapsed_seconds: number;
  llm_calls: LlmCall[];
  // legacy (mirrors llm_calls[0])
  system_prompt: string;
  raw_llm_response: string;
  elapsed_seconds: number;
}

export async function fetchChatModels(): Promise<ChatModelsResponse> {
  return request(`${BASE}/chat/models`);
}

export async function postChatAsk(req: ChatAskRequest): Promise<ChatAskResponse> {
  const response = await fetch(`${BASE}/chat/ask`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(req),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `API error ${response.status}`);
  }
  return parseNumericStrings(await response.json()) as ChatAskResponse;
}

/** Re-execute the SQL on the backend and trigger a download of the full result set. */
export async function downloadChatResults(
  sql: string,
  format: 'csv' | 'xlsx',
  filename?: string,
): Promise<void> {
  const response = await fetch(`${BASE}/chat/download`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ sql, format, filename }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `Download failed: ${response.status}`);
  }
  const blob = await response.blob();
  // Derive filename from Content-Disposition if present
  let fname = `${filename ?? 'chatbot-result'}.${format}`;
  const cd = response.headers.get('content-disposition') || '';
  const m = /filename="([^"]+)"/.exec(cd);
  if (m) fname = m[1];
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fname;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export async function clearAllData(): Promise<TableCounts> {
  const response = await fetch(`${BASE}/admin/clear-data`, { method: 'POST', headers: authHeaders() });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `API error ${response.status}`);
  }
  return response.json();
}
