import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { DollarSign, Zap, TrendingUp, Server, Lightbulb } from 'lucide-react';

import KpiCard from '../components/KpiCard';
import ChartCard from '../components/ChartCard';
import DateRangeFilter from '../components/DateRangeFilter';
import FieldDefinitions from '../components/FieldDefinitions';

import {
  fetchKPISummary,
  fetchUsageSummary,
  fetchByDimension,
  fetchTopSkus,
} from '../api/client';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const COLORS = [
  '#0071e3', '#34c759', '#ff9500', '#af52de', '#ff3b30',
  '#5ac8fa', '#ff2d55', '#00856f', '#5856d6', '#ffcc00',
];

const FIELD_DEFINITIONS = [
  { name: 'SKU Name', description: 'The Databricks Stock Keeping Unit identifying a specific compute product and pricing tier (e.g., PREMIUM_JOBS_COMPUTE, ENTERPRISE_ALL_PURPOSE_COMPUTE).' },
  { name: 'DBU', description: 'Databricks Unit - a normalized unit of processing power used to measure compute consumption. Different SKUs have different per-DBU list prices.' },
  { name: 'Usage Quantity', description: 'The number of DBUs consumed during the billing period for a given SKU and workspace combination.' },
  { name: 'Billing Origin Product', description: 'The Databricks product that originated the usage: JOBS, SQL, ALL_PURPOSE, DLT, MODEL_SERVING, etc.' },
  { name: 'Usage Type', description: 'Describes how compute was consumed - e.g., STANDARD_COMPUTE, SERVERLESS_COMPUTE, PHOTON_COMPUTE.' },
  { name: 'Cloud', description: 'The cloud provider where the workspace runs: AWS, AZURE, or GCP.' },
  { name: 'Workspace', description: 'A unique Databricks workspace identified by its workspace ID. Each workspace is an isolated environment for data engineering and analytics.' },
];

const currencyFmt = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const numberFmt = new Intl.NumberFormat('en-US');
const compactCurrencyFmt = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  maximumFractionDigits: 1,
});

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Custom Recharts tooltip (light theme)
// ---------------------------------------------------------------------------

interface CustomTooltipPayloadEntry {
  name: string;
  value: number;
  color: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: CustomTooltipPayloadEntry[];
  label?: string;
  formatter?: (value: number, name: string) => string;
}

function ChartTooltip({ active, payload, label, formatter }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-[var(--color-border)] rounded-xl px-3 py-2 shadow-lg text-xs">
      {label && (
        <p className="text-[var(--color-text-secondary)] mb-1 font-medium">{label}</p>
      )}
      {payload.map((entry, i) => (
        <p key={i} style={{ color: entry.color }} className="font-medium">
          {entry.name}: {formatter ? formatter(entry.value, entry.name) : entry.value}
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Billing Explorer — overview page (formerly Dashboard)
// ---------------------------------------------------------------------------

export default function BillingExplorer() {
  const [startDate, setStartDate] = useState(daysAgo(30));
  const [endDate, setEndDate] = useState(today());

  const kpiQuery = useQuery({
    queryKey: ['kpi-summary', startDate, endDate],
    queryFn: () => fetchKPISummary(startDate, endDate),
  });

  const usageQuery = useQuery({
    queryKey: ['usage-summary', startDate, endDate, 'day'],
    queryFn: () => fetchUsageSummary(startDate, endDate, 'day'),
  });

  const skuQuery = useQuery({
    queryKey: ['by-sku', startDate, endDate],
    queryFn: () => fetchByDimension('sku', startDate, endDate),
  });

  const originQuery = useQuery({
    queryKey: ['by-origin', startDate, endDate],
    queryFn: () => fetchByDimension('origin', startDate, endDate),
  });

  const topSkuQuery = useQuery({
    queryKey: ['top-skus', startDate, endDate],
    queryFn: () => fetchTopSkus(startDate, endDate, 10),
  });

  const kpi = kpiQuery.data;

  const dailyData = useMemo(
    () => usageQuery.data?.data ?? [],
    [usageQuery.data],
  );

  const skuData = useMemo(
    () => (skuQuery.data?.data ?? []).sort((a, b) => b.total_cost - a.total_cost).slice(0, 10),
    [skuQuery.data],
  );

  const originData = useMemo(() => {
    const items = originQuery.data?.data ?? [];
    const total = items.reduce((sum, d) => sum + d.total_cost, 0);
    return items.map(d => ({
      ...d,
      pct: total > 0 ? ((d.total_cost / total) * 100).toFixed(1) : '0.0',
    }));
  }, [originQuery.data]);

  const topSkuData = useMemo(
    () => topSkuQuery.data?.data ?? [],
    [topSkuQuery.data],
  );

  const costFormatter = (value: number, name: string) => {
    if (name.toLowerCase().includes('dbu') || name.toLowerCase().includes('usage')) {
      return numberFmt.format(value);
    }
    return currencyFmt.format(value);
  };

  return (
    <div className="space-y-6 max-w-[1400px]">
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Billing Explorer</h1>
        <p className="text-sm text-[var(--color-text-muted)] mt-1">
          Aggregated view of Databricks spending. Drill into the sub-sections in the sidebar for finer slices.
        </p>
      </div>

      <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-2xl px-4 py-3">
        <Lightbulb size={18} className="text-[var(--color-primary)] mt-0.5 shrink-0" />
        <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
          This page shows an aggregated view of your Databricks billing data. Use the date
          range filter to adjust the time period. Hover over any{' '}
          <span className="text-[var(--color-primary)] font-medium">(i)</span> icon for detailed
          explanations of metrics and fields. All costs are estimated based on list prices and
          actual DBU consumption.
        </p>
      </div>

      <DateRangeFilter
        startDate={startDate}
        endDate={endDate}
        onStartChange={setStartDate}
        onEndChange={setEndDate}
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          title="Total Cost"
          value={kpi ? currencyFmt.format(kpi.total_cost) : '--'}
          trend={kpi?.cost_trend_pct}
          icon={<DollarSign size={20} />}
          accentColor="var(--color-primary)"
          tooltip="Total estimated cost for the selected date range, calculated as the sum of (DBU usage x list price) across all SKUs and workspaces."
          subtitle="Sum of all estimated charges"
        />
        <KpiCard
          title="Total DBUs"
          value={kpi ? numberFmt.format(kpi.total_dbus) : '--'}
          trend={kpi?.cost_trend_pct}
          icon={<Zap size={20} />}
          accentColor="var(--color-accent)"
          tooltip="Total Databricks Units consumed across all workspaces and SKUs. DBUs are a normalized measure of compute processing power."
          subtitle="Databricks Units consumed"
        />
        <KpiCard
          title="Avg Daily Cost"
          value={kpi ? currencyFmt.format(kpi.avg_daily_cost) : '--'}
          trend={kpi?.cost_trend_pct}
          icon={<TrendingUp size={20} />}
          accentColor="var(--color-warning)"
          tooltip="Average estimated daily cost over the selected period. Useful for spotting whether spending is trending up or down compared to prior periods."
          subtitle="Average per day in range"
        />
        <KpiCard
          title="Active Workspaces"
          value={kpi ? numberFmt.format(kpi.active_workspaces) : '--'}
          icon={<Server size={20} />}
          accentColor="var(--color-success)"
          tooltip="Number of distinct Databricks workspaces that recorded billing usage during the selected date range."
          subtitle="Workspaces with usage"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard
          title="Daily Cost Trend"
          tooltip="Daily estimated cost over the selected period. Spikes may indicate batch jobs or quarter-end processing. Weekends typically show lower usage."
          isLoading={usageQuery.isLoading}
          exportFilename="daily-cost-trend"
          exportRows={() => dailyData.map((d) => ({
            period: d.period,
            total_cost: d.total_cost,
            total_usage: d.total_usage,
          }))}
        >
          {dailyData.length === 0 ? (
            <div className="flex items-center justify-center h-64 text-sm text-[var(--color-text-muted)]">
              No data for the selected period
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={dailyData} margin={{ top: 20, right: 20, left: 10, bottom: 5 }}>
                <defs>
                  <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0071e3" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#0071e3" stopOpacity={0.01} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
                <XAxis
                  dataKey="period"
                  tick={{ fontSize: 11, fill: '#86868b' }}
                  tickFormatter={(v: string) => v.slice(5)}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: '#86868b' }}
                  tickFormatter={(v: number) => compactCurrencyFmt.format(v)}
                  domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.15)]}
                />
                <Tooltip content={<ChartTooltip formatter={costFormatter} />} />
                <Area
                  type="monotone"
                  dataKey="total_cost"
                  name="Cost"
                  stroke="#0071e3"
                  fill="url(#costGradient)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard
          title="Cost by SKU"
          tooltip="Breakdown of costs by Databricks SKU (Stock Keeping Unit). Each SKU represents a specific compute product like Jobs Compute, SQL Compute, or All Purpose Compute. Higher-tier SKUs (Premium, Enterprise) cost more per DBU but offer additional features."
          isLoading={skuQuery.isLoading}
          exportFilename="cost-by-sku"
          exportRows={() => skuData.map((d) => ({
            sku_name: d.label,
            total_cost: d.total_cost,
            total_usage: d.total_usage,
          }))}
        >
          {skuData.length === 0 ? (
            <div className="flex items-center justify-center h-64 text-sm text-[var(--color-text-muted)]">
              No data for the selected period
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart
                data={skuData}
                layout="vertical"
                margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" horizontal={false} />
                <XAxis
                  type="number"
                  tick={{ fontSize: 11, fill: '#86868b' }}
                  tickFormatter={(v: number) => compactCurrencyFmt.format(v)}
                />
                <YAxis
                  type="category"
                  dataKey="label"
                  width={140}
                  tick={{ fontSize: 10, fill: '#6e6e73' }}
                  tickFormatter={(v: string) =>
                    v.length > 20 ? `${v.slice(0, 20)}...` : v
                  }
                />
                <Tooltip content={<ChartTooltip formatter={costFormatter} />} />
                <Bar dataKey="total_cost" name="Cost" radius={[0, 6, 6, 0]}>
                  {skuData.map((_entry, index) => (
                    <Cell
                      key={`sku-cell-${index}`}
                      fill={COLORS[index % COLORS.length]}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard
          title="Cost by Billing Origin"
          tooltip="Distribution of costs by the product that originated the usage. JOBS = scheduled workflows, SQL = SQL warehouse queries, ALL_PURPOSE = interactive notebooks, DLT = Delta Live Tables pipelines, SERVING = model serving endpoints."
          isLoading={originQuery.isLoading}
          exportFilename="cost-by-billing-origin"
          exportRows={() => originData.map((d) => ({
            billing_origin: d.label,
            total_cost: d.total_cost,
            total_usage: d.total_usage,
            pct_of_total: d.pct,
          }))}
        >
          {originData.length === 0 ? (
            <div className="flex items-center justify-center h-64 text-sm text-[var(--color-text-muted)]">
              No data for the selected period
            </div>
          ) : (
            <div>
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie
                    data={originData}
                    dataKey="total_cost"
                    nameKey="label"
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={90}
                    paddingAngle={2}
                    stroke="#ffffff"
                    strokeWidth={2}
                  >
                    {originData.map((_entry, index) => (
                      <Cell key={`origin-cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip content={<ChartTooltip formatter={costFormatter} />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="flex flex-wrap justify-center gap-x-4 gap-y-1.5 mt-2 px-2">
                {originData.map((d, i) => (
                  <span key={d.label} className="flex items-center gap-1.5 text-xs">
                    <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                    <span className="text-[var(--color-text-secondary)] font-medium">{d.label}</span>
                    <span className="text-[var(--color-text-muted)]">({d.pct}%)</span>
                  </span>
                ))}
              </div>
            </div>
          )}
        </ChartCard>

        <ChartCard
          title="Top 10 SKUs"
          tooltip="Top 10 most expensive SKUs ranked by total estimated cost. This helps identify which compute products drive the majority of your spending."
          isLoading={topSkuQuery.isLoading}
          exportFilename="top-10-skus"
          exportRows={() => topSkuData.map((d) => ({
            rank: d.rank,
            sku_name: d.sku_name,
            total_cost: d.total_cost,
            total_usage: d.total_usage,
          }))}
        >
          {topSkuData.length === 0 ? (
            <div className="flex items-center justify-center h-64 text-sm text-[var(--color-text-muted)]">
              No data for the selected period
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={topSkuData} margin={{ top: 20, right: 20, left: 10, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
                <XAxis
                  dataKey="sku_name"
                  tick={{ fontSize: 10, fill: '#86868b' }}
                  tickFormatter={(v: string) =>
                    v.length > 12 ? `${v.slice(0, 12)}...` : v
                  }
                  interval={0}
                  angle={-35}
                  textAnchor="end"
                  height={60}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: '#86868b' }}
                  tickFormatter={(v: number) => compactCurrencyFmt.format(v)}
                />
                <Tooltip content={<ChartTooltip formatter={costFormatter} />} />
                <Bar dataKey="total_cost" name="Cost" radius={[6, 6, 0, 0]}>
                  {topSkuData.map((_entry, index) => (
                    <Cell key={`top-sku-cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>
      </div>

      <FieldDefinitions fields={FIELD_DEFINITIONS} />
    </div>
  );
}
