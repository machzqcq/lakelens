import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, PieChart, Pie, Cell, AreaChart, Area, Legend,
} from 'recharts';
import {
  Tag, Building2, GitBranch, Activity, Cloud, Users,
  Info, ArrowDownAZ, ArrowUpDown,
} from 'lucide-react';
import ChartCard from '../components/ChartCard';
import DateRangeFilter from '../components/DateRangeFilter';
import InfoTooltip from '../components/InfoTooltip';
import FieldDefinitions from '../components/FieldDefinitions';
import { useWorkspaceNames } from '../hooks/useWorkspaceNames';
import { fetchByDimension, fetchByUser, fetchDailyTrend } from '../api/client';
import type { BreakdownItem, UserCostItem, DailyTrendItem } from '../types/api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const COLORS = [
  '#0071e3', '#34c759', '#ff9500', '#af52de', '#ff3b30',
  '#5ac8fa', '#ff2d55', '#00856f', '#5856d6', '#ffcc00',
];

type DimensionKey = 'sku' | 'workspace' | 'origin' | 'usage-type' | 'cloud' | 'user';

interface DimensionMeta {
  key: DimensionKey;
  label: string;
  icon: typeof Tag;
  tooltip: string;
}

const DIMENSIONS: DimensionMeta[] = [
  {
    key: 'sku',
    label: 'SKU',
    icon: Tag,
    tooltip:
      'Stock Keeping Unit - each represents a specific Databricks compute product with its own pricing tier. Examples: PREMIUM_JOBS_COMPUTE ($0.30/DBU), SERVERLESS_SQL_COMPUTE ($0.70/DBU).',
  },
  {
    key: 'workspace',
    label: 'Workspace',
    icon: Building2,
    tooltip:
      'Databricks workspaces are isolated environments for teams. Each workspace has its own set of clusters, warehouses, and notebooks.',
  },
  {
    key: 'origin',
    label: 'Origin',
    icon: GitBranch,
    tooltip:
      'The Databricks product that originated the usage: JOBS (scheduled workflows), SQL (warehouse queries), ALL_PURPOSE (interactive compute), DLT (Delta Live Tables), SERVING (model endpoints).',
  },
  {
    key: 'usage-type',
    label: 'Usage Type',
    icon: Activity,
    tooltip:
      'How the resources were consumed: COMPUTE_TIME (processing), STORAGE_SPACE (data storage), NETWORK_BYTES (data transfer), TOKEN (API calls), GPU_TIME (GPU compute).',
  },
  {
    key: 'cloud',
    label: 'Cloud',
    icon: Cloud,
    tooltip:
      'Cloud provider where the compute ran. Most organizations use a primary cloud (AZURE, AWS, or GCP) with possible multi-cloud workloads.',
  },
  {
    key: 'user',
    label: 'User',
    icon: Users,
    tooltip:
      'The identity (run_as) that executed the workload. Helps with cost allocation and identifying top consumers.',
  },
];

type SortField = 'label' | 'total_usage' | 'total_cost' | 'pct';
type SortDir = 'asc' | 'desc';

const TABLE_FIELDS = [
  { name: 'Label', description: 'The dimension value (SKU name, workspace ID, origin, etc.).' },
  { name: 'Total DBUs', description: 'Total Databricks Units consumed by this item in the selected date range.' },
  { name: 'Total Cost', description: 'Dollar cost calculated as DBU usage multiplied by the SKU list price.' },
  { name: '% of Total', description: 'This item\'s share of the total cost across all items in this dimension.' },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtCost(n: number): string {
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
}

function fmtNumber(n: number): string {
  return n.toLocaleString('en-US', { maximumFractionDigits: 1 });
}

function fmtPct(n: number): string {
  return `${n.toFixed(1)}%`;
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Truncate long labels for chart axes. */
function truncate(s: string, max = 24): string {
  return s.length > max ? `${s.slice(0, max)}...` : s;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface UnifiedRow {
  label: string;
  display_label: string;  // human-friendly (workspace name etc.); falls back to label
  total_usage: number;
  total_cost: number;
  pct: number;
}

function buildRows(
  dimensionData: BreakdownItem[] | undefined,
  userData: UserCostItem[] | undefined,
  isUser: boolean,
  toDisplay?: (label: string) => string,
): UnifiedRow[] {
  const raw: { label: string; total_usage: number; total_cost: number }[] = isUser
    ? (userData ?? []).map((u) => ({ label: u.user, total_usage: u.total_usage, total_cost: u.total_cost }))
    : (dimensionData ?? []).map((b) => ({ label: b.label, total_usage: b.total_usage, total_cost: b.total_cost }));

  const totalCost = raw.reduce((s, r) => s + r.total_cost, 0);
  return raw.map((r) => ({
    ...r,
    display_label: toDisplay ? toDisplay(r.label) : r.label,
    pct: totalCost > 0 ? (r.total_cost / totalCost) * 100 : 0,
  }));
}

// Custom bar chart tooltip — payload[0].payload has the underlying row, so we can
// pull display_label (human) and label (workspace id / raw key).
function BarTooltipContent({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload ?? {};
  const header = row.display_label && row.display_label !== row.label
    ? `${row.display_label} (${row.label})`
    : (row.display_label || label);
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-3 shadow-lg text-xs">
      <p className="font-medium text-gray-900 mb-1.5">{header}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} className="text-gray-600">
          <span className="inline-block w-2 h-2 rounded-full mr-1.5" style={{ backgroundColor: p.fill }} />
          <span style={{ color: p.fill }}>{p.name}</span>: {p.dataKey === 'total_cost' ? fmtCost(p.value) : fmtNumber(p.value)}
        </p>
      ))}
    </div>
  );
}

// Custom pie tooltip
function PieTooltipContent({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0];
  const row = d.payload ?? {};
  const header = row.display_label && row.display_label !== row.label
    ? `${row.display_label} (${row.label})`
    : (row.display_label || d.name);
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-3 shadow-lg text-xs">
      <p className="font-medium text-gray-900 mb-1">{header}</p>
      <p className="text-gray-600">Cost: <span style={{ color: d.payload.fill }}>{fmtCost(d.value)}</span></p>
      <p className="text-gray-600">Share: {fmtPct(d.payload.pct)}</p>
    </div>
  );
}

// Custom area chart tooltip for daily trend
function TrendTooltipContent({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-3 shadow-lg text-xs">
      <p className="font-medium text-gray-900 mb-1.5">{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} className="text-gray-600">
          <span className="inline-block w-2 h-2 rounded-full mr-1.5" style={{ backgroundColor: p.stroke }} />
          <span style={{ color: p.stroke }}>{p.name}</span>: {p.dataKey === 'total_cost' ? fmtCost(p.value) : fmtNumber(p.value)}
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function CostExplorer() {
  // --- State ---
  const [startDate, setStartDate] = useState(daysAgo(90));
  const [endDate, setEndDate] = useState(today());
  const [dimension, setDimension] = useState<DimensionKey>('sku');
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);
  const [sortField, setSortField] = useState<SortField>('total_cost');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [trendSkuFilter, setTrendSkuFilter] = useState('');
  const [trendWsFilter, setTrendWsFilter] = useState('');

  const isUser = dimension === 'user';
  const isWorkspaceDim = dimension === 'workspace';

  // Workspace name resolver (id -> human-readable, falls back to id).
  const { resolver: wsName } = useWorkspaceNames();

  // --- Queries ---
  const dimQuery = useQuery({
    queryKey: ['costExplorer', 'dimension', dimension, startDate, endDate],
    queryFn: () =>
      isUser
        ? fetchByUser(startDate, endDate, 15).then((r) => r.data)
        : fetchByDimension(dimension as Exclude<DimensionKey, 'user'>, startDate, endDate).then((r) => r.data),
    enabled: true,
  });

  const trendQuery = useQuery({
    queryKey: ['costExplorer', 'trend', startDate, endDate, trendSkuFilter, trendWsFilter, selectedLabel, dimension],
    queryFn: () => {
      // Derive filter values from selected label based on active dimension
      let sku = trendSkuFilter || undefined;
      let ws = trendWsFilter || undefined;
      if (selectedLabel) {
        if (dimension === 'sku') sku = selectedLabel;
        else if (dimension === 'workspace') ws = selectedLabel;
      }
      return fetchDailyTrend(startDate, endDate, sku, ws).then((r) => r.data);
    },
  });

  // --- Derived data ---
  const rows: UnifiedRow[] = useMemo(() => {
    const toDisplay = isWorkspaceDim ? wsName : undefined;
    const built = buildRows(
      isUser ? undefined : (dimQuery.data as BreakdownItem[] | undefined),
      isUser ? (dimQuery.data as UserCostItem[] | undefined) : undefined,
      isUser,
      toDisplay,
    );
    const sorted = [...built].sort((a, b) => {
      const av = a[sortField];
      const bv = b[sortField];
      if (typeof av === 'string' && typeof bv === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortDir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
    return sorted;
  }, [dimQuery.data, isUser, isWorkspaceDim, wsName, sortField, sortDir]);

  const barData = useMemo(() => [...rows].sort((a, b) => b.total_cost - a.total_cost), [rows]);
  const pieData = useMemo(() => {
    const top = [...rows].sort((a, b) => b.total_cost - a.total_cost);
    if (top.length <= 10) return top;
    const main = top.slice(0, 9);
    const other = top.slice(9).reduce(
      (acc, r) => ({
        ...acc,
        total_cost: acc.total_cost + r.total_cost,
        total_usage: acc.total_usage + r.total_usage,
        pct: acc.pct + r.pct,
      }),
      { label: 'Other', display_label: 'Other', total_cost: 0, total_usage: 0, pct: 0 } as UnifiedRow,
    );
    return [...main, other];
  }, [rows]);

  const totalCost = useMemo(() => rows.reduce((s, r) => s + r.total_cost, 0), [rows]);

  const trendData: DailyTrendItem[] = trendQuery.data ?? [];

  // --- Sort handler ---
  function handleSort(field: SortField) {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('desc');
    }
  }

  function handleSegmentClick(label: string) {
    setSelectedLabel((prev) => (prev === label ? null : label));
  }

  function SortIcon({ field }: { field: SortField }) {
    if (sortField !== field) return <ArrowUpDown size={12} className="ml-1 opacity-40" />;
    return sortDir === 'asc'
      ? <ArrowDownAZ size={12} className="ml-1 text-[var(--color-primary-light)]" />
      : <ArrowDownAZ size={12} className="ml-1 text-[var(--color-primary-light)] rotate-180" />;
  }

  // --- Render ---
  const activeMeta = DIMENSIONS.find((d) => d.key === dimension)!;
  const isLoading = dimQuery.isLoading;

  return (
    <div className="space-y-6 max-w-[1600px]">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-[var(--color-text-primary)]">Cost Explorer</h2>
        <p className="text-sm text-[var(--color-text-secondary)] mt-1">
          Slice and dice your Databricks costs across multiple dimensions
        </p>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-2xl px-4 py-3">
        <Info size={18} className="text-[var(--color-primary-light)] mt-0.5 shrink-0" />
        <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
          Use the dimension selector to view costs grouped by different attributes. Combine date filters with dimension
          selection to drill into specific time periods. Click on chart segments to see detailed breakdowns.
        </p>
      </div>

      {/* Controls Row */}
      <div className="space-y-4">
        <DateRangeFilter
          startDate={startDate}
          endDate={endDate}
          onStartChange={setStartDate}
          onEndChange={setEndDate}
        />

        {/* Dimension selector */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-[var(--color-text-secondary)] mr-1">Dimension:</span>
          {DIMENSIONS.map((dim) => {
            const Icon = dim.icon;
            const active = dimension === dim.key;
            return (
              <button
                key={dim.key}
                onClick={() => {
                  setDimension(dim.key);
                  setSelectedLabel(null);
                }}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full border transition-all ${
                  active
                    ? 'bg-[var(--color-primary)] text-white border-transparent shadow-sm'
                    : 'bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] border-transparent hover:bg-[var(--color-bg-card-hover)]'
                }`}
              >
                <Icon size={14} />
                {dim.label}
              </button>
            );
          })}
          <InfoTooltip text={activeMeta.tooltip} />
        </div>
      </div>

      {/* Main Content - Charts */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* Horizontal Bar Chart */}
        <ChartCard
          title={`Cost by ${activeMeta.label}`}
          tooltip={`Horizontal bar chart showing all ${activeMeta.label.toLowerCase()} items sorted by cost descending. Blue bars represent cost, teal bars represent DBU usage.`}
          isLoading={isLoading}
          className="xl:col-span-2"
          exportFilename={`cost-by-${activeMeta.key}`}
          exportRows={() => barData.map((r) => ({
            label: r.label,
            total_usage: r.total_usage,
            total_cost: r.total_cost,
            pct_of_total: Number(r.pct.toFixed(2)),
          }))}
        >
          <div style={{ height: Math.max(300, barData.length * 38 + 40) }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={barData} layout="vertical" margin={{ top: 5, right: 30, left: 10, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11, fill: '#86868b' }} tickFormatter={(v) => fmtCost(v)} />
                <YAxis
                  type="category"
                  dataKey="display_label"
                  width={180}
                  tick={{ fontSize: 11, fill: '#6e6e73' }}
                  tickFormatter={(v) => truncate(v, 28)}
                />
                <RechartsTooltip content={<BarTooltipContent />} cursor={{ fill: 'var(--color-bg-card-hover)', opacity: 0.3 }} />
                <Legend wrapperStyle={{ fontSize: 11, color: '#86868b' }} />
                <Bar
                  dataKey="total_cost"
                  name="Cost ($)"
                  fill={COLORS[0]}
                  radius={[0, 4, 4, 0]}
                  cursor="pointer"
                  onClick={(data: any) => handleSegmentClick(data.label)}
                  opacity={0.9}
                />
                <Bar
                  dataKey="total_usage"
                  name="DBUs"
                  fill={COLORS[1]}
                  radius={[0, 4, 4, 0]}
                  cursor="pointer"
                  onClick={(data: any) => handleSegmentClick(data.label)}
                  opacity={0.7}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        {/* Donut / Pie Chart */}
        <ChartCard
          title="Cost Distribution"
          tooltip="Donut chart showing the percentage distribution of cost across items. Click a segment to filter the daily trend below."
          isLoading={isLoading}
          exportFilename={`cost-distribution-${activeMeta.key}`}
          exportRows={() => pieData.map((r) => ({
            label: r.label,
            total_cost: r.total_cost,
            total_usage: r.total_usage,
            pct_of_total: Number(r.pct.toFixed(2)),
          }))}
        >
          {/* Pie + center label (absolute) */}
          <div className="relative h-[260px]">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  dataKey="total_cost"
                  nameKey="display_label"
                  cx="50%"
                  cy="50%"
                  innerRadius="55%"
                  outerRadius="85%"
                  paddingAngle={2}
                  cursor="pointer"
                  onClick={(data: any) => handleSegmentClick(data.label)}
                  stroke="var(--color-bg-card)"
                  strokeWidth={2}
                >
                  {pieData.map((_, i) => (
                    <Cell
                      key={i}
                      fill={COLORS[i % COLORS.length]}
                      opacity={selectedLabel && pieData[i].label !== selectedLabel ? 0.35 : 1}
                    />
                  ))}
                </Pie>
                <RechartsTooltip content={<PieTooltipContent />} />
              </PieChart>
            </ResponsiveContainer>
            {totalCost > 0 && (
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Total</p>
                <p className="text-lg font-bold text-[var(--color-text-primary)]">{fmtCost(totalCost)}</p>
              </div>
            )}
          </div>
          {/* Legend below pie (separate flow) */}
          <div className="flex flex-wrap gap-x-3 gap-y-1.5 justify-center mt-4 px-2">
            {pieData.map((d, i) => (
              <button
                key={d.label}
                onClick={() => handleSegmentClick(d.label)}
                title={d.display_label !== d.label ? `${d.display_label} (${d.label})` : d.label}
                className={`flex items-center gap-1 text-[10px] transition-opacity ${
                  selectedLabel && d.label !== selectedLabel ? 'opacity-40' : 'opacity-100'
                }`}
              >
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                <span className="text-[var(--color-text-secondary)] truncate max-w-[120px]">{d.display_label}</span>
              </button>
            ))}
          </div>
        </ChartCard>
      </div>

      {/* Data Table */}
      <ChartCard
        title={`${activeMeta.label} Breakdown`}
        tooltip="Sortable data table showing every item with its DBU usage, cost, and share of total. Click column headers to sort."
        isLoading={isLoading}
        exportFilename={`${activeMeta.key}-breakdown`}
        exportRows={() => rows.map((r) => ({
          label: r.label,
          total_usage: r.total_usage,
          total_cost: r.total_cost,
          pct_of_total: Number(r.pct.toFixed(2)),
        }))}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm bg-white">
            <thead>
              <tr className="bg-[var(--color-bg-secondary)] border-b border-[var(--color-border)]">
                {[
                  { field: 'label' as SortField, label: 'Label' },
                  { field: 'total_usage' as SortField, label: 'Total DBUs' },
                  { field: 'total_cost' as SortField, label: 'Total Cost' },
                  { field: 'pct' as SortField, label: '% of Total' },
                ].map(({ field, label }) => (
                  <th
                    key={field}
                    onClick={() => handleSort(field)}
                    className="px-4 py-2.5 text-left text-xs font-semibold text-[var(--color-text-secondary)] cursor-pointer select-none hover:text-[var(--color-primary-light)] transition-colors"
                  >
                    <span className="inline-flex items-center">
                      {label}
                      <SortIcon field={field} />
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr
                  key={row.label}
                  onClick={() => handleSegmentClick(row.label)}
                  className={`border-b border-[var(--color-border)]/50 cursor-pointer transition-colors
                    ${selectedLabel === row.label ? 'bg-blue-100' : ''}
                    ${i % 2 === 0 ? 'bg-white' : 'bg-[var(--color-bg-secondary)]'}
                    hover:bg-blue-50`}
                >
                  <td className="px-4 py-2.5 text-[var(--color-text-primary)] font-medium">
                    <span className="flex items-center gap-2">
                      <span
                        className="w-2.5 h-2.5 rounded-full shrink-0"
                        style={{ backgroundColor: COLORS[i % COLORS.length] }}
                      />
                      <span
                        className="truncate max-w-[300px]"
                        title={row.display_label !== row.label ? `${row.display_label} (${row.label})` : row.label}
                      >
                        {row.display_label}
                      </span>
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-[var(--color-text-secondary)] font-mono text-right">
                    {fmtNumber(row.total_usage)}
                  </td>
                  <td className="px-4 py-2.5 text-[var(--color-text-primary)] font-mono font-semibold text-right">
                    {fmtCost(row.total_cost)}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <span className="inline-flex items-center gap-2">
                      <span className="text-[var(--color-text-secondary)] font-mono">{fmtPct(row.pct)}</span>
                      <span
                        className="block h-1.5 rounded-full bg-[var(--color-primary)] opacity-60"
                        style={{ width: `${Math.max(row.pct * 0.8, 2)}px` }}
                      />
                    </span>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && !isLoading && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-sm text-[var(--color-text-muted)]">
                    No data available for the selected filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <FieldDefinitions title="Column Definitions" fields={TABLE_FIELDS} />
      </ChartCard>

      {/* Daily Trend Section */}
      <ChartCard
        title={`Daily Trend${selectedLabel ? ` - ${isWorkspaceDim ? wsName(selectedLabel) : selectedLabel}` : ''}`}
        tooltip="Area chart showing the daily cost and DBU usage trend. Select a bar or pie segment above to filter. You can also apply additional SKU or workspace filters."
        isLoading={trendQuery.isLoading}
        exportFilename={`daily-trend${selectedLabel ? `-${selectedLabel}` : ''}`}
        exportRows={() => trendData.map((r) => ({
          usage_date: r.usage_date,
          total_cost: r.total_cost,
          total_usage: r.total_usage,
        }))}
      >
        {/* Trend filters */}
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <div className="flex items-center gap-2">
            <label className="text-xs text-[var(--color-text-muted)]">SKU filter:</label>
            <input
              type="text"
              value={trendSkuFilter}
              onChange={(e) => setTrendSkuFilter(e.target.value)}
              placeholder="e.g. PREMIUM_JOBS_COMPUTE"
              className="bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-lg px-2.5 py-1 text-xs
                text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] w-56
                focus:outline-none focus:border-[var(--color-primary)]/50 transition-colors"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-[var(--color-text-muted)]">Workspace filter:</label>
            <input
              type="text"
              value={trendWsFilter}
              onChange={(e) => setTrendWsFilter(e.target.value)}
              placeholder="e.g. 1234567890"
              className="bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-lg px-2.5 py-1 text-xs
                text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] w-44
                focus:outline-none focus:border-[var(--color-primary)]/50 transition-colors"
            />
          </div>
          {(selectedLabel || trendSkuFilter || trendWsFilter) && (
            <button
              onClick={() => {
                setSelectedLabel(null);
                setTrendSkuFilter('');
                setTrendWsFilter('');
              }}
              className="text-xs text-[var(--color-primary-light)] hover:underline"
            >
              Clear all filters
            </button>
          )}
        </div>

        <div className="h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={trendData} margin={{ top: 20, right: 20, left: 10, bottom: 5 }}>
              <defs>
                <linearGradient id="gradCost" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={COLORS[0]} stopOpacity={0.15} />
                  <stop offset="95%" stopColor={COLORS[0]} stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gradUsage" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={COLORS[1]} stopOpacity={0.15} />
                  <stop offset="95%" stopColor={COLORS[1]} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
              <XAxis
                dataKey="usage_date"
                tick={{ fontSize: 11, fill: '#86868b' }}
                tickFormatter={(v: string) => v.slice(5)}
              />
              <YAxis
                yAxisId="cost"
                tick={{ fontSize: 11, fill: '#86868b' }}
                tickFormatter={(v) => fmtCost(v)}
                domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.15)]}
              />
              <YAxis
                yAxisId="usage"
                orientation="right"
                tick={{ fontSize: 11, fill: '#86868b' }}
                tickFormatter={(v) => fmtNumber(v)}
                domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.15)]}
              />
              <RechartsTooltip content={<TrendTooltipContent />} />
              <Legend wrapperStyle={{ fontSize: 11, color: '#86868b' }} />
              <Area
                yAxisId="cost"
                type="monotone"
                dataKey="total_cost"
                name="Cost ($)"
                stroke={COLORS[0]}
                fill="url(#gradCost)"
                strokeWidth={2}
              />
              <Area
                yAxisId="usage"
                type="monotone"
                dataKey="total_usage"
                name="DBUs"
                stroke={COLORS[1]}
                fill="url(#gradUsage)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {trendData.length === 0 && !trendQuery.isLoading && (
          <p className="text-center text-xs text-[var(--color-text-muted)] mt-2">
            No trend data available for the current filters.
          </p>
        )}
      </ChartCard>
    </div>
  );
}
