import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AreaChart,
  Area,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceLine,
} from 'recharts';
import { TrendingUp } from 'lucide-react';

import ChartCard from '../components/ChartCard';
import DateRangeFilter from '../components/DateRangeFilter';
import InfoTooltip from '../components/InfoTooltip';
import FieldDefinitions from '../components/FieldDefinitions';
import {
  fetchUsageSummary,
  fetchUsageSummaryBySku,
  fetchMoMGrowth,
  fetchForecast,
  fetchDailyTrend,
} from '../api/client';
import type { UsageSummaryItem, MoMGrowthItem, ForecastItem, DailyTrendItem } from '../types/api';

const COLORS = ['#0071e3', '#34c759', '#ff9500', '#af52de', '#ff3b30', '#5ac8fa', '#ff2d55', '#00856f', '#5856d6', '#ffcc00'];

type GroupBy = 'day' | 'week' | 'month';

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

const fmtCurrency = (v: number) =>
  `$${v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

const fmtPct = (v: number | null) => (v !== null ? `${v.toFixed(1)}%` : 'N/A');

export default function Trends() {
  const [startDate, setStartDate] = useState(daysAgo(90));
  const [endDate, setEndDate] = useState(today());
  const [groupBy, setGroupBy] = useState<GroupBy>('day');

  // ---- Queries ----

  const usageSummaryQ = useQuery({
    queryKey: ['usageSummary', startDate, endDate, groupBy],
    queryFn: () => fetchUsageSummary(startDate, endDate, groupBy),
  });

  const usageBySkuQ = useQuery({
    queryKey: ['usageSummaryBySku', startDate, endDate, groupBy],
    queryFn: () => fetchUsageSummaryBySku(startDate, endDate, groupBy, 5),
  });

  const momQ = useQuery({
    queryKey: ['momGrowth'],
    queryFn: fetchMoMGrowth,
  });

  const forecastQ = useQuery({
    queryKey: ['forecast'],
    queryFn: fetchForecast,
  });

  const dailyTrendQ = useQuery({
    queryKey: ['dailyTrend30', daysAgo(30), today()],
    queryFn: () => fetchDailyTrend(daysAgo(30), today()),
  });

  // ---- Derived data ----

  const usageData: UsageSummaryItem[] = usageSummaryQ.data?.data ?? [];

  // Build the cost-per-DBU dataset: aggregate + per-top-SKU as additional series.
  // Backend returns long-form rows; we pivot here so Recharts can plot multiple
  // lines on a single x-axis. Aggregate uses the unfiltered usage-summary; the
  // per-SKU lines come from usage-summary-by-sku.
  const skuList: string[] = usageBySkuQ.data?.skus ?? [];
  const cpdData = (() => {
    const byPeriod = new Map<string, Record<string, number | string>>();
    for (const u of usageData) {
      const cpd = u.total_usage > 0 ? u.total_cost / u.total_usage : 0;
      byPeriod.set(u.period, { period: u.period, aggregate: cpd });
    }
    for (const r of usageBySkuQ.data?.data ?? []) {
      const row = byPeriod.get(r.period) ?? { period: r.period };
      const cpd = r.total_usage > 0 ? r.total_cost / r.total_usage : 0;
      row[r.sku_name] = cpd;
      byPeriod.set(r.period, row);
    }
    return [...byPeriod.values()].sort((a, b) =>
      String(a.period).localeCompare(String(b.period)),
    );
  })();

  const momData: (MoMGrowthItem & { fillColor: string })[] = (momQ.data?.data ?? []).map((d) => ({
    ...d,
    fillColor:
      d.growth_pct !== null && d.growth_pct > 0 ? '#fee2e2' : '#dcfce7',
  }));

  // Combine historical + forecast for the forecast chart
  const historicalData: DailyTrendItem[] = dailyTrendQ.data?.data ?? [];
  const forecastRaw: ForecastItem[] = forecastQ.data?.data ?? [];

  const combinedForecast = [
    ...historicalData.map((d) => ({
      date: d.usage_date,
      historical_cost: d.total_cost,
      forecast_cost: null as number | null,
    })),
    // bridge point: last historical day also starts forecast
    ...(historicalData.length > 0
      ? [
          {
            date: historicalData[historicalData.length - 1].usage_date,
            historical_cost: null as number | null,
            forecast_cost: historicalData[historicalData.length - 1].total_cost,
          },
        ]
      : []),
    ...forecastRaw.map((d) => ({
      date: d.forecast_date,
      historical_cost: null as number | null,
      forecast_cost: d.forecasted_cost,
    })),
  ];

  // ---- Render ----

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <TrendingUp size={24} className="text-[var(--color-primary)]" />
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">
            Trends &amp; Forecast
          </h1>
        </div>
        <div className="bg-blue-50 border border-blue-200 rounded-2xl px-4 py-3 text-sm text-[var(--color-text-secondary)] leading-relaxed">
          Analyze spending patterns over time. Monthly trends reveal seasonal patterns and growth
          rates. The forecast uses linear regression on the last 90 days to project the next 30 days.
          Use the grouping selector to view data at different time granularities.
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-4">
        <DateRangeFilter
          startDate={startDate}
          endDate={endDate}
          onStartChange={setStartDate}
          onEndChange={setEndDate}
        />

        <div className="flex items-center gap-2">
          <span className="text-sm text-[var(--color-text-secondary)]">Group by</span>
          <InfoTooltip text="Change the time granularity for the Cost Over Time chart." />
          <div className="flex gap-1">
            {(['day', 'week', 'month'] as const).map((g) => (
              <button
                key={g}
                onClick={() => setGroupBy(g)}
                className={`px-3 py-1 text-xs rounded-full transition-colors ${
                  groupBy === g
                    ? 'bg-[var(--color-primary)] text-white'
                    : 'bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]'
                }`}
              >
                {g.charAt(0).toUpperCase() + g.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Chart 1 - Cost Over Time */}
      <ChartCard
        title="Cost Over Time"
        tooltip="Aggregated cost and DBU consumption over the selected period. Use the grouping selector to switch between daily, weekly, and monthly views."
        isLoading={usageSummaryQ.isLoading}
        exportFilename={`cost-over-time-${groupBy}`}
        exportRows={() => usageData.map((d) => ({
          period: d.period,
          total_cost: d.total_cost,
          total_usage: d.total_usage,
        }))}
      >
        <ResponsiveContainer width="100%" height={360}>
          <AreaChart data={usageData} margin={{ top: 20, right: 20, left: 10, bottom: 5 }}>
            <defs>
              <linearGradient id="gradCost" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={COLORS[0]} stopOpacity={0.15} />
                <stop offset="95%" stopColor={COLORS[0]} stopOpacity={0.01} />
              </linearGradient>
              <linearGradient id="gradDBU" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={COLORS[1]} stopOpacity={0.15} />
                <stop offset="95%" stopColor={COLORS[1]} stopOpacity={0.01} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
            <XAxis
              dataKey="period"
              tick={{ fontSize: 11, fill: '#86868b' }}
              tickLine={false}
            />
            <YAxis
              yAxisId="cost"
              orientation="left"
              tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
              tick={{ fontSize: 11, fill: '#86868b' }}
              tickLine={false}
              domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.15)]}
            />
            <YAxis
              yAxisId="dbu"
              orientation="right"
              tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`}
              tick={{ fontSize: 11, fill: '#86868b' }}
              tickLine={false}
              domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.15)]}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#ffffff',
                border: '1px solid #e5e5ea',
                borderRadius: '0.75rem',
                fontSize: 12,
                boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)',
              }}
              formatter={(value: number, name: string) => [
                name === 'total_cost' ? fmtCurrency(value) : value.toLocaleString(),
                name === 'total_cost' ? 'Cost' : 'DBUs',
              ]}
            />
            <Legend
              formatter={(value: string) => (value === 'total_cost' ? 'Cost ($)' : 'DBUs')}
            />
            <Area
              yAxisId="cost"
              type="monotone"
              dataKey="total_cost"
              stroke={COLORS[0]}
              fill="url(#gradCost)"
              strokeWidth={2}
            />
            <Area
              yAxisId="dbu"
              type="monotone"
              dataKey="total_usage"
              stroke={COLORS[1]}
              fill="url(#gradDBU)"
              strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      </ChartCard>

      {/* Chart 1b - Cost per DBU (aggregate + per-top-SKU overlays) */}
      <ChartCard
        title="Cost per DBU"
        tooltip="Average dollar cost per DBU consumed in each period (total_cost / total_usage). The thick blue line is the aggregate; dotted lines are the top 5 SKUs by spend. Per-SKU lines reflect that SKU's effective price (mostly flat unless list_prices changed); the aggregate moves based on workload mix between tiers."
        isLoading={usageSummaryQ.isLoading || usageBySkuQ.isLoading}
        exportFilename={`cost-per-dbu-${groupBy}`}
        exportRows={() => cpdData.map((row) => {
          const out: Record<string, string | number> = { period: row.period as string };
          if (typeof row.aggregate === 'number') out.aggregate_cost_per_dbu = Number(row.aggregate.toFixed(4));
          for (const sku of skuList) {
            if (typeof row[sku] === 'number') {
              out[sku] = Number((row[sku] as number).toFixed(4));
            }
          }
          return out;
        })}
      >
        <ResponsiveContainer width="100%" height={340}>
          <ComposedChart data={cpdData} margin={{ top: 20, right: 20, left: 10, bottom: 5 }}>
            <defs>
              <linearGradient id="gradCostPerDbu" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={COLORS[0]} stopOpacity={0.18} />
                <stop offset="95%" stopColor={COLORS[0]} stopOpacity={0.01} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
            <XAxis dataKey="period" tick={{ fontSize: 11, fill: '#86868b' }} tickLine={false} />
            <YAxis
              tick={{ fontSize: 11, fill: '#86868b' }}
              tickLine={false}
              tickFormatter={(v: number) => `$${v.toFixed(2)}`}
              domain={[
                (dataMin: number) => Math.max(0, dataMin * 0.9),
                (dataMax: number) => dataMax * 1.05,
              ]}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#ffffff',
                border: '1px solid #e5e5ea',
                borderRadius: '0.75rem',
                fontSize: 12,
                boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)',
              }}
              formatter={(value: number, name: string) => [
                `$${value.toFixed(4)}`,
                name === 'aggregate' ? 'Aggregate' : name,
              ]}
            />
            <Legend
              wrapperStyle={{ fontSize: 11 }}
              formatter={(value: string) => (value === 'aggregate' ? 'Aggregate (all SKUs)' : value)}
            />
            {/* Aggregate as filled area + thick line */}
            <Area
              type="monotone"
              dataKey="aggregate"
              stroke={COLORS[0]}
              fill="url(#gradCostPerDbu)"
              strokeWidth={3}
              dot={false}
              isAnimationActive={false}
            />
            {/* Per-SKU dotted overlays */}
            {skuList.map((sku, i) => (
              <Line
                key={sku}
                type="monotone"
                dataKey={sku}
                stroke={COLORS[(i + 1) % COLORS.length]}
                strokeWidth={1.5}
                strokeDasharray="4 3"
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </ChartCard>

      {/* Chart 2 - Month-over-Month Growth */}
      <ChartCard
        title="Month-over-Month Growth"
        tooltip="Month-over-month cost changes. Growth percentage compares each month to the previous month. Consistent growth above 10% may indicate scaling needs or cost optimization opportunities."
        isLoading={momQ.isLoading}
        exportFilename="mom-growth"
        exportRows={() => (momQ.data?.data ?? []).map((d) => ({
          month: d.month,
          total_cost: d.total_cost,
          prior_month_cost: d.prior_month_cost,
          growth_pct: d.growth_pct,
        }))}
      >
        <ResponsiveContainer width="100%" height={360}>
          <ComposedChart data={momData} margin={{ top: 20, right: 20, left: 10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 11, fill: '#86868b' }}
              tickLine={false}
            />
            <YAxis
              yAxisId="cost"
              orientation="left"
              tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
              tick={{ fontSize: 11, fill: '#86868b' }}
              tickLine={false}
            />
            <YAxis
              yAxisId="pct"
              orientation="right"
              tickFormatter={(v: number) => `${v}%`}
              tick={{ fontSize: 11, fill: '#86868b' }}
              tickLine={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#ffffff',
                border: '1px solid #e5e5ea',
                borderRadius: '0.75rem',
                fontSize: 12,
                boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)',
              }}
              formatter={(value: number, name: string) => {
                if (name === 'total_cost') return [fmtCurrency(value), 'Monthly Cost'];
                if (name === 'growth_pct') return [fmtPct(value), 'Growth %'];
                return [value, name];
              }}
            />
            <Legend
              formatter={(value: string) =>
                value === 'total_cost' ? 'Monthly Cost' : 'Growth %'
              }
            />
            <ReferenceLine yAxisId="pct" y={0} stroke="#86868b" strokeDasharray="3 3" />
            <Bar
              yAxisId="cost"
              dataKey="total_cost"
              radius={[4, 4, 0, 0]}
              maxBarSize={48}
              fill={COLORS[0]}
              // Recharts Cell-level coloring via shape is complex; we color
              // the bar using the growth direction via a custom shape.
              shape={(props: Record<string, unknown>) => {
                const { x, y, width, height, payload } = props as {
                  x: number;
                  y: number;
                  width: number;
                  height: number;
                  payload: MoMGrowthItem;
                };
                const isPositive =
                  payload.growth_pct !== null && payload.growth_pct > 0;
                const fill = isPositive ? '#fee2e2' : '#dcfce7';
                const stroke = isPositive ? '#ef4444' : '#22c55e';
                return (
                  <rect
                    x={x}
                    y={y}
                    width={width}
                    height={height}
                    rx={4}
                    ry={4}
                    fill={payload.growth_pct === null ? COLORS[0] : fill}
                    stroke={payload.growth_pct === null ? COLORS[0] : stroke}
                    strokeWidth={1}
                  />
                );
              }}
            />
            <Line
              yAxisId="pct"
              type="monotone"
              dataKey="growth_pct"
              stroke={COLORS[2]}
              strokeWidth={2}
              dot={{ fill: COLORS[2], r: 4 }}
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>

        <FieldDefinitions
          fields={[
            { name: 'month', description: 'Calendar month of the billing period' },
            { name: 'total_cost', description: 'Total cost for the month in USD' },
            {
              name: 'prior_month_cost',
              description: 'Total cost from the previous month for comparison',
            },
            {
              name: 'growth_pct',
              description:
                'Percentage change from the prior month. Positive values indicate cost increase.',
            },
          ]}
        />
      </ChartCard>

      {/* Chart 3 - 30-Day Cost Forecast */}
      <ChartCard
        title="30-Day Cost Forecast"
        tooltip="Linear trend forecast based on the last 90 days. This is a simple projection - actual costs may vary due to workload changes, new projects, or cost optimization efforts. The shaded area represents the forecasted period."
        isLoading={forecastQ.isLoading || dailyTrendQ.isLoading}
        exportFilename="cost-forecast"
        exportRows={() => combinedForecast.map((r) => ({
          date: r.date,
          historical_cost: r.historical_cost,
          forecast_cost: r.forecast_cost,
        }))}
      >
        <ResponsiveContainer width="100%" height={360}>
          <AreaChart data={combinedForecast} margin={{ top: 20, right: 20, left: 10, bottom: 5 }}>
            <defs>
              <linearGradient id="gradHistorical" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={COLORS[0]} stopOpacity={0.15} />
                <stop offset="95%" stopColor={COLORS[0]} stopOpacity={0.01} />
              </linearGradient>
              <pattern
                id="forecastPattern"
                patternUnits="userSpaceOnUse"
                width="6"
                height="6"
                patternTransform="rotate(45)"
              >
                <rect width="6" height="6" fill="rgba(0, 113, 227, 0.08)" />
                <line x1="0" y1="0" x2="0" y2="6" stroke="rgba(0, 113, 227, 0.15)" strokeWidth="2" />
              </pattern>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11, fill: '#86868b' }}
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
              tick={{ fontSize: 11, fill: '#86868b' }}
              tickLine={false}
              domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.15)]}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#ffffff',
                border: '1px solid #e5e5ea',
                borderRadius: '0.75rem',
                fontSize: 12,
                boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)',
              }}
              formatter={(value: number | null, name: string) => [
                value !== null ? fmtCurrency(value) : 'N/A',
                name === 'historical_cost' ? 'Actual Cost' : 'Forecasted Cost',
              ]}
            />
            <Legend
              formatter={(value: string) =>
                value === 'historical_cost' ? 'Actual Cost' : 'Forecasted Cost'
              }
            />
            <Area
              type="monotone"
              dataKey="historical_cost"
              stroke={COLORS[0]}
              fill="url(#gradHistorical)"
              strokeWidth={2}
              connectNulls={false}
            />
            <Area
              type="monotone"
              dataKey="forecast_cost"
              stroke={COLORS[0]}
              strokeDasharray="6 3"
              strokeWidth={2}
              fill="url(#forecastPattern)"
              strokeOpacity={0.6}
              connectNulls={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </ChartCard>
    </div>
  );
}
