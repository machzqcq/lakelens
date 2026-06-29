import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ComposedChart,
  Line,
  Area,
  Scatter,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  Cell,
} from 'recharts';
import { AlertTriangle } from 'lucide-react';

import ChartCard from '../components/ChartCard';
import DateRangeFilter from '../components/DateRangeFilter';
import FieldDefinitions from '../components/FieldDefinitions';
import { useWorkspaceNames } from '../hooks/useWorkspaceNames';

import {
  fetchCostAnomalies,
  fetchCostMatrix,
  fetchUtilization,
} from '../api/client';

import type { CostAnomalyItem } from '../types/api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const COLORS = ['#0071e3', '#34c759', '#ff9500', '#af52de', '#ff3b30', '#5ac8fa', '#ff2d55', '#00856f', '#5856d6', '#ffcc00'];

const HEATMAP_LOW = [245, 245, 247]; // #f5f5f7
const HEATMAP_MID = [0, 113, 227];  // #0071e3
const HEATMAP_HIGH = [255, 59, 48]; // #ff3b30

const currencyFmt = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const compactCurrencyFmt = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  maximumFractionDigits: 1,
});
const numberFmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Heatmap color interpolation
// ---------------------------------------------------------------------------

function lerpColor(t: number): string {
  // t is 0..1 where 0 = low, 0.5 = mid, 1 = high
  const clamp = Math.max(0, Math.min(1, t));
  let r: number, g: number, b: number;
  if (clamp <= 0.5) {
    const f = clamp / 0.5;
    r = HEATMAP_LOW[0] + (HEATMAP_MID[0] - HEATMAP_LOW[0]) * f;
    g = HEATMAP_LOW[1] + (HEATMAP_MID[1] - HEATMAP_LOW[1]) * f;
    b = HEATMAP_LOW[2] + (HEATMAP_MID[2] - HEATMAP_LOW[2]) * f;
  } else {
    const f = (clamp - 0.5) / 0.5;
    r = HEATMAP_MID[0] + (HEATMAP_HIGH[0] - HEATMAP_MID[0]) * f;
    g = HEATMAP_MID[1] + (HEATMAP_HIGH[1] - HEATMAP_MID[1]) * f;
    b = HEATMAP_MID[2] + (HEATMAP_HIGH[2] - HEATMAP_MID[2]) * f;
  }
  return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
}

// ---------------------------------------------------------------------------
// Anomaly helpers
// ---------------------------------------------------------------------------

function severityLabel(z: number): { text: string; className: string } {
  if (z > 3) return { text: 'Critical', className: 'bg-red-100 text-red-700' };
  if (z > 2.5) return { text: 'High', className: 'bg-orange-100 text-orange-700' };
  return { text: 'Moderate', className: 'bg-yellow-100 text-yellow-700' };
}

// ---------------------------------------------------------------------------
// Custom Recharts tooltip
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
  labelFormatter?: (label: string) => string;
}

function ChartTooltip({ active, payload, label, formatter, labelFormatter }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white shadow-lg rounded-xl px-3 py-2 text-xs">
      {label && (
        <p className="text-[var(--color-text-secondary)] mb-1 font-medium">
          {labelFormatter ? labelFormatter(label) : label}
        </p>
      )}
      {payload.map((entry, i) => (
        <p key={i} className="text-[var(--color-text-primary)]" style={{ color: entry.color }}>
          {entry.name}: {formatter ? formatter(entry.value, entry.name) : entry.value}
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field definitions
// ---------------------------------------------------------------------------

const ANOMALY_FIELDS = [
  { name: 'actual_cost', description: 'The observed total cost for that day.' },
  { name: 'expected_cost', description: '30-day rolling average cost (the "normal" baseline).' },
  { name: 'std_dev', description: 'Standard deviation of the rolling window, measures typical daily variance.' },
  { name: 'z_score', description: 'Number of standard deviations from the mean. Values > 2 are flagged as anomalies.' },
];

const UTILIZATION_FIELDS = [
  { name: 'avg_dbu_per_day', description: 'Average daily DBU consumption across the selected period.' },
  { name: 'peak_dbu_per_day', description: 'Maximum single-day DBU consumption - indicates burst capacity needs.' },
  { name: 'total_cost', description: 'Cumulative estimated cost for the workspace in the period.' },
];

// ---------------------------------------------------------------------------
// Analytics page
// ---------------------------------------------------------------------------

export default function Analytics() {
  const [startDate, setStartDate] = useState(daysAgo(90));
  const [endDate, setEndDate] = useState(today());

  // Workspace name resolver (id -> human-readable label, falls back to id).
  const { resolver: wsName } = useWorkspaceNames();

  // --- Data fetching ---

  const anomalyQuery = useQuery({
    queryKey: ['cost-anomalies'],
    queryFn: () => fetchCostAnomalies(),
  });

  const matrixQuery = useQuery({
    queryKey: ['cost-matrix', startDate, endDate],
    queryFn: () => fetchCostMatrix(startDate, endDate),
  });

  const utilizationQuery = useQuery({
    queryKey: ['utilization', startDate, endDate],
    queryFn: () => fetchUtilization(startDate, endDate),
  });

  // --- Derived data ---

  // Anomaly chart data: merge actual cost line with anomaly scatter points
  const anomalyData = useMemo(() => {
    const items = anomalyQuery.data?.data ?? [];
    return items.map((d: CostAnomalyItem) => ({
      ...d,
      date: d.usage_date,
      range_low: Math.max(0, d.expected_cost - 2 * d.std_dev),
      range_high: d.expected_cost + 2 * d.std_dev,
      // Only populate anomaly_cost for scatter dots when z_score > 2
      anomaly_cost: d.z_score > 2 ? d.actual_cost : undefined,
    }));
  }, [anomalyQuery.data]);

  const anomalyTableData = useMemo(() => {
    return anomalyData
      .filter(d => d.z_score > 2)
      .sort((a, b) => b.z_score - a.z_score);
  }, [anomalyData]);

  // Heatmap data
  const heatmapData = useMemo(() => {
    const matrix = matrixQuery.data;
    if (!matrix) return null;
    const cellMap = new Map<string, number>();
    let maxCost = 0;
    for (const cell of matrix.cells) {
      const key = `${cell.workspace_id}::${cell.billing_origin}`;
      cellMap.set(key, cell.total_cost);
      if (cell.total_cost > maxCost) maxCost = cell.total_cost;
    }
    return {
      workspaces: matrix.workspaces,
      billingOrigins: matrix.billing_origins,
      cellMap,
      maxCost,
    };
  }, [matrixQuery.data]);

  // Utilization data
  const utilizationData = useMemo(
    () => utilizationQuery.data?.data ?? [],
    [utilizationQuery.data],
  );

  // --- Formatters ---

  const costFormatter = (value: number, name: string) => {
    if (name.toLowerCase().includes('dbu')) return numberFmt.format(value);
    if (name.toLowerCase().includes('z_score') || name.toLowerCase().includes('deviation'))
      return numberFmt.format(value);
    return currencyFmt.format(value);
  };

  // --- Render ---

  return (
    <div className="space-y-6 max-w-[1400px]">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Advanced Analytics</h1>
        <p className="text-sm text-[var(--color-text-muted)] mt-1">
          Deep insights into anomalies, cost distribution, and resource utilization
        </p>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-2xl px-4 py-3">
        <AlertTriangle size={18} className="text-[var(--color-warning)] mt-0.5 shrink-0" />
        <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
          Advanced analytics provide deeper insights into your Databricks spending. Anomaly detection
          identifies unusual spending days. The cost heatmap reveals which workspace-product
          combinations drive costs. Utilization metrics help right-size your compute resources.
        </p>
      </div>

      {/* Date range filter */}
      <DateRangeFilter
        startDate={startDate}
        endDate={endDate}
        onStartChange={setStartDate}
        onEndChange={setEndDate}
      />

      {/* ================================================================= */}
      {/* Section 1: Cost Anomalies                                         */}
      {/* ================================================================= */}

      <ChartCard
        title="Cost Anomalies Detection"
        tooltip="Days where the actual cost deviated more than 2 standard deviations from the 30-day rolling average. Red dots indicate anomalies. Investigate these days for unexpected batch jobs, data processing spikes, or configuration changes."
        isLoading={anomalyQuery.isLoading}
        exportFilename="cost-anomalies"
        exportRows={() => anomalyData.map((d) => ({
          date: d.date,
          actual_cost: d.actual_cost,
          expected_cost: d.expected_cost,
          range_low: d.range_low,
          range_high: d.range_high,
          z_score: d.z_score,
          is_anomaly: d.anomaly_cost !== undefined,
        }))}
      >
        {anomalyData.length === 0 ? (
          <div className="flex items-center justify-center h-64 text-sm text-[var(--color-text-muted)]">
            No anomaly data available
          </div>
        ) : (
          <>
            <ResponsiveContainer width="100%" height={360}>
              <ComposedChart data={anomalyData} margin={{ top: 20, right: 20, left: 10, bottom: 5 }}>
                <defs>
                  <linearGradient id="rangeGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0071e3" stopOpacity={0.06} />
                    <stop offset="95%" stopColor="#0071e3" stopOpacity={0.06} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: '#86868b' }}
                  tickFormatter={(v: string) => v.slice(5)}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: '#86868b' }}
                  tickFormatter={(v: number) => compactCurrencyFmt.format(v)}
                  domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.15)]}
                />
                <Tooltip content={<ChartTooltip formatter={costFormatter} />} />
                <Legend
                  wrapperStyle={{ fontSize: 11 }}
                  formatter={(value: string) => (
                    <span className="text-xs text-[var(--color-text-secondary)]">{value}</span>
                  )}
                />

                {/* Normal range band */}
                <Area
                  type="monotone"
                  dataKey="range_high"
                  name="Normal Range (upper)"
                  stroke="none"
                  fill="url(#rangeGradient)"
                  fillOpacity={1}
                />
                <Area
                  type="monotone"
                  dataKey="range_low"
                  name="Normal Range (lower)"
                  stroke="none"
                  fill="var(--color-bg-card)"
                  fillOpacity={1}
                />

                {/* Expected cost rolling average */}
                <Line
                  type="monotone"
                  dataKey="expected_cost"
                  name="Expected (30d avg)"
                  stroke="#64748b"
                  strokeWidth={1.5}
                  strokeDasharray="6 3"
                  dot={false}
                />

                {/* Actual cost */}
                <Line
                  type="monotone"
                  dataKey="actual_cost"
                  name="Actual Cost"
                  stroke="#0071e3"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, fill: '#0071e3' }}
                />

                {/* Anomaly scatter dots */}
                <Scatter
                  dataKey="anomaly_cost"
                  name="Anomaly"
                  fill="#ff3b30"
                  shape="circle"
                  legendType="circle"
                >
                  {anomalyData.map((entry, index) => (
                    <Cell
                      key={`anomaly-${index}`}
                      fill={entry.anomaly_cost !== undefined ? '#ff3b30' : 'transparent'}
                      strokeWidth={entry.anomaly_cost !== undefined ? 2 : 0}
                      stroke={entry.anomaly_cost !== undefined ? '#ff3b30' : 'transparent'}
                    />
                  ))}
                </Scatter>
              </ComposedChart>
            </ResponsiveContainer>

            {/* Anomalies table */}
            {anomalyTableData.length > 0 && (
              <div className="mt-5 overflow-x-auto">
                <h4 className="text-xs font-medium text-[var(--color-text-secondary)] mb-3">
                  Detected Anomalies ({anomalyTableData.length})
                </h4>
                <table className="w-full text-xs bg-white">
                  <thead>
                    <tr className="border-b border-[var(--color-border)]">
                      <th className="text-left py-2 px-3 font-medium text-[var(--color-text-muted)]">Date</th>
                      <th className="text-right py-2 px-3 font-medium text-[var(--color-text-muted)]">Actual Cost</th>
                      <th className="text-right py-2 px-3 font-medium text-[var(--color-text-muted)]">Expected Cost</th>
                      <th className="text-right py-2 px-3 font-medium text-[var(--color-text-muted)]">Deviation (z)</th>
                      <th className="text-center py-2 px-3 font-medium text-[var(--color-text-muted)]">Severity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {anomalyTableData.map((row, idx) => {
                      const sev = severityLabel(row.z_score);
                      return (
                        <tr
                          key={row.date}
                          className={`border-b border-[var(--color-border)]/50 transition-colors ${idx % 2 === 0 ? 'bg-white' : 'bg-[#f5f5f7]'}`}
                        >
                          <td className="py-2.5 px-3 text-[var(--color-text-primary)] font-mono">{row.date}</td>
                          <td className="py-2.5 px-3 text-right text-[var(--color-text-primary)]">
                            {currencyFmt.format(row.actual_cost)}
                          </td>
                          <td className="py-2.5 px-3 text-right text-[var(--color-text-secondary)]">
                            {currencyFmt.format(row.expected_cost)}
                          </td>
                          <td className="py-2.5 px-3 text-right font-mono text-[var(--color-text-primary)]">
                            {row.z_score.toFixed(2)}
                          </td>
                          <td className="py-2.5 px-3 text-center">
                            <span
                              className={`inline-block px-2.5 py-0.5 rounded-full text-[10px] font-semibold ${sev.className}`}
                            >
                              {sev.text}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        <FieldDefinitions fields={ANOMALY_FIELDS} />
      </ChartCard>

      {/* ================================================================= */}
      {/* Section 2: Cost Heatmap                                           */}
      {/* ================================================================= */}

      <ChartCard
        title="Cost Allocation Heatmap"
        tooltip="This heatmap shows the cost distribution across workspaces (rows) and billing origin products (columns). Darker cells indicate higher costs. Use this to identify which teams (workspaces) are spending the most on which products."
        isLoading={matrixQuery.isLoading}
        exportFilename="cost-allocation-heatmap"
        exportRows={() => {
          if (!heatmapData) return [];
          const rows: Array<Record<string, string | number>> = [];
          for (const ws of heatmapData.workspaces) {
            for (const origin of heatmapData.billingOrigins) {
              const cost = heatmapData.cellMap.get(`${ws}::${origin}`) ?? 0;
              if (cost > 0) {
                rows.push({ workspace_id: ws, billing_origin: origin, total_cost: cost });
              }
            }
          }
          return rows;
        }}
      >
        {!heatmapData || heatmapData.workspaces.length === 0 ? (
          <div className="flex items-center justify-center h-64 text-sm text-[var(--color-text-muted)]">
            No heatmap data available
          </div>
        ) : (
          <div className="overflow-x-auto">
            {/* Heatmap grid */}
            <div className="inline-block min-w-full">
              {/* Column headers */}
              <div className="flex">
                {/* Empty corner cell */}
                <div className="shrink-0 w-36" />
                {heatmapData.billingOrigins.map((origin) => (
                  <div
                    key={origin}
                    className="flex-1 min-w-[90px] px-1 py-2 text-center"
                  >
                    <span className="text-[10px] font-medium text-[var(--color-text-muted)] uppercase tracking-wide">
                      {origin.length > 14 ? `${origin.slice(0, 14)}...` : origin}
                    </span>
                  </div>
                ))}
              </div>

              {/* Rows */}
              {heatmapData.workspaces.map((ws) => {
                const label = wsName(ws);
                const display = label === ws ? ws : label;
                const hoverTitle = label === ws ? ws : `${label} (${ws})`;
                return (
                  <div key={ws} className="flex">
                    {/* Row header */}
                    <div className="shrink-0 w-36 flex items-center px-2 py-1">
                      <span
                        className="text-[10px] text-[var(--color-text-secondary)] truncate"
                        title={hoverTitle}
                      >
                        {display.length > 18 ? `${display.slice(0, 18)}...` : display}
                      </span>
                    </div>
                    {/* Cells */}
                    {heatmapData.billingOrigins.map((origin) => {
                      const key = `${ws}::${origin}`;
                      const cost = heatmapData.cellMap.get(key) ?? 0;
                      const t = heatmapData.maxCost > 0 ? cost / heatmapData.maxCost : 0;
                      const bgColor = lerpColor(t);
                      // Choose text color based on intensity for readability
                      const textColor = t > 0.4 ? '#ffffff' : '#1d1d1f';
                      return (
                        <div
                          key={key}
                          className="flex-1 min-w-[90px] m-[1px] rounded flex items-center justify-center py-3 transition-all duration-200 hover:scale-105 hover:shadow-lg hover:z-10 relative cursor-default"
                          style={{ backgroundColor: bgColor }}
                          title={`${hoverTitle} / ${origin}: ${currencyFmt.format(cost)}`}
                        >
                          <span className="text-[10px] font-medium" style={{ color: textColor }}>
                            {cost > 0 ? compactCurrencyFmt.format(cost) : '-'}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>

            {/* Color legend */}
            <div className="flex items-center gap-3 mt-4 pt-3 border-t border-[var(--color-border)]">
              <span className="text-[10px] text-[var(--color-text-muted)]">Low</span>
              <div
                className="flex-1 h-3 rounded-full max-w-[300px]"
                style={{
                  background: `linear-gradient(to right, #f5f5f7, #0071e3, #ff3b30)`,
                }}
              />
              <span className="text-[10px] text-[var(--color-text-muted)]">High</span>
              <span className="text-[10px] text-[var(--color-text-muted)] ml-2">
                Max: {currencyFmt.format(heatmapData.maxCost)}
              </span>
            </div>
          </div>
        )}
      </ChartCard>

      {/* ================================================================= */}
      {/* Section 3: Workspace Utilization                                   */}
      {/* ================================================================= */}

      <ChartCard
        title="Workspace Utilization Metrics"
        tooltip="Compare DBU consumption patterns across workspaces. Average DBU/day shows typical usage, while Peak DBU/day reveals burst capacity needs. Large gaps between average and peak suggest opportunities to use autoscaling or serverless compute."
        isLoading={utilizationQuery.isLoading}
        exportFilename="workspace-utilization"
        exportRows={() => utilizationData.map((u) => ({
          workspace_id: u.workspace_id,
          avg_dbu_per_day: u.avg_dbu_per_day,
          peak_dbu_per_day: u.peak_dbu_per_day,
          total_cost: u.total_cost,
        }))}
      >
        {utilizationData.length === 0 ? (
          <div className="flex items-center justify-center h-64 text-sm text-[var(--color-text-muted)]">
            No utilization data available
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={360}>
            <BarChart
              data={utilizationData}
              margin={{ top: 20, right: 20, left: 10, bottom: 40 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
              <XAxis
                dataKey="workspace_id"
                tick={{ fontSize: 10, fill: '#86868b' }}
                tickFormatter={(v: string) => {
                  const nm = wsName(v);
                  return nm.length > 14 ? `${nm.slice(0, 14)}...` : nm;
                }}
                interval={0}
                angle={-30}
                textAnchor="end"
                height={60}
              />
              <YAxis
                tick={{ fontSize: 11, fill: '#86868b' }}
                tickFormatter={(v: number) => `${numberFmt.format(v)} DBU`}
                domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.15)]}
              />
              <Tooltip
                content={
                  <ChartTooltip
                    formatter={costFormatter}
                    labelFormatter={(id) => {
                      const nm = wsName(id);
                      return nm === id ? id : `${nm} (${id})`;
                    }}
                  />
                }
              />
              <Legend
                wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                formatter={(value: string) => (
                  <span className="text-xs text-[var(--color-text-secondary)]">{value}</span>
                )}
              />
              <Bar
                dataKey="avg_dbu_per_day"
                name="Avg DBU/day"
                fill="#0071e3"
                radius={[4, 4, 0, 0]}
              >
                {utilizationData.map((_entry, index) => (
                  <Cell key={`avg-${index}`} fill={COLORS[0]} />
                ))}
              </Bar>
              <Bar
                dataKey="peak_dbu_per_day"
                name="Peak DBU/day"
                fill="#ff9500"
                radius={[4, 4, 0, 0]}
              >
                {utilizationData.map((_entry, index) => (
                  <Cell key={`peak-${index}`} fill={COLORS[2]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}

        <FieldDefinitions fields={UTILIZATION_FIELDS} />
      </ChartCard>
    </div>
  );
}
