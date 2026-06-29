import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  Treemap,
  XAxis,
  YAxis,
} from 'recharts';
import { Coins, Info, X } from 'lucide-react';

import ChartCard from '../components/ChartCard';
import DateRangeFilter from '../components/DateRangeFilter';
import { useWorkspaceNames } from '../hooks/useWorkspaceNames';

import {
  fetchSoConcentration,
  fetchSoDrilldown,
  fetchSoOriginIdentity,
  fetchSoOriginLeaderboard,
  fetchSoOriginWorkspaceMatrix,
  fetchSoServerlessShare,
  fetchSoSkuIdentity,
  fetchSoSkuLeaderboard,
  fetchSoSkuWorkspaceMatrix,
  fetchSoTreemap,
  fetchSoTrend,
} from '../api/client';

import type {
  ConcentrationRow,
  OriginLeaderboardItem,
  PivotResponse,
  SkuLeaderboardItem,
  SkuOriginTreemapItem,
} from '../types/api';

// ---------------------------------------------------------------------------
// Formatters & helpers
// ---------------------------------------------------------------------------

const currencyFmt = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const compactCurrencyFmt = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1,
});
const numberFmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

const COLORS = [
  '#0071e3', '#34c759', '#ff9500', '#af52de', '#ff3b30',
  '#5ac8fa', '#ff2d55', '#00856f', '#5856d6', '#ffcc00',
  '#8b5cf6', '#06b6d4', '#10b981', '#f59e0b', '#ec4899',
];

const HEATMAP_LOW = [245, 245, 247];
const HEATMAP_MID = [0, 113, 227];
const HEATMAP_HIGH = [255, 59, 48];

function lerpColor(t: number): string {
  const c = Math.max(0, Math.min(1, t));
  let r: number, g: number, b: number;
  if (c <= 0.5) {
    const f = c / 0.5;
    r = HEATMAP_LOW[0] + (HEATMAP_MID[0] - HEATMAP_LOW[0]) * f;
    g = HEATMAP_LOW[1] + (HEATMAP_MID[1] - HEATMAP_LOW[1]) * f;
    b = HEATMAP_LOW[2] + (HEATMAP_MID[2] - HEATMAP_LOW[2]) * f;
  } else {
    const f = (c - 0.5) / 0.5;
    r = HEATMAP_MID[0] + (HEATMAP_HIGH[0] - HEATMAP_MID[0]) * f;
    g = HEATMAP_MID[1] + (HEATMAP_HIGH[1] - HEATMAP_MID[1]) * f;
    b = HEATMAP_MID[2] + (HEATMAP_HIGH[2] - HEATMAP_MID[2]) * f;
  }
  return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
}

// ---------------------------------------------------------------------------
// Sparkline (tiny inline SVG)
// ---------------------------------------------------------------------------

function Sparkline({ values, width = 80, height = 22, color = '#0071e3' }: {
  values: number[]; width?: number; height?: number; color?: string;
}) {
  if (!values.length) return <span className="text-[10px] text-[var(--color-text-muted)]">—</span>;
  const max = Math.max(...values, 1e-9);
  const pts = values.map((v, i) => {
    const x = (i / Math.max(values.length - 1, 1)) * (width - 2) + 1;
    const y = height - 2 - (Math.max(0, v) / max) * (height - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const polyline = pts.join(' ');
  // area fill (rough)
  const areaPath = `M${pts[0]} L${polyline.replace(/\s/g, ' L')} L${width - 1},${height - 1} L1,${height - 1} Z`;
  return (
    <svg width={width} height={height} className="inline-block align-middle">
      <path d={areaPath} fill={color} opacity={0.12} />
      <polyline points={polyline} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Heatmap (CSS grid)
// ---------------------------------------------------------------------------

function Heatmap({
  pivot, rowLabel, colLabel, onCellClick, colDisplay,
}: {
  pivot: PivotResponse;
  rowLabel: string;
  colLabel: string;
  onCellClick?: (row: string, col: string) => void;
  colDisplay?: (col: string) => string;
}) {
  const cellMap = useMemo(() => {
    const m = new Map<string, number>();
    let max = 0;
    for (const c of pivot.cells) {
      m.set(`${c.row}::${c.col}`, c.total_cost);
      if (c.total_cost > max) max = c.total_cost;
    }
    return { m, max };
  }, [pivot.cells]);

  if (pivot.rows.length === 0 || pivot.cols.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-sm text-[var(--color-text-muted)]">
        No data
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <div className="inline-block min-w-full">
        {/* Header */}
        <div className="flex">
          <div className="shrink-0 w-44 px-2 py-2 text-[10px] uppercase tracking-wide text-[var(--color-text-muted)]">
            {rowLabel} ▾ / {colLabel} ▸
          </div>
          {pivot.cols.map((c) => {
            const label = colDisplay ? colDisplay(c) : c;
            const titleText = colDisplay && label !== c ? `${label} (${c})` : c;
            return (
              <div key={c} className="flex-1 min-w-[80px] px-1 py-2 text-center" title={titleText}>
                <span className="text-[10px] font-medium text-[var(--color-text-muted)] uppercase tracking-wide">
                  {label.length > 12 ? `${label.slice(0, 12)}…` : label}
                </span>
              </div>
            );
          })}
        </div>
        {pivot.rows.map((r) => (
          <div key={r} className="flex">
            <div className="shrink-0 w-44 flex items-center px-2 py-1">
              <span className="text-[10px] font-mono text-[var(--color-text-secondary)] truncate" title={r}>
                {r.length > 22 ? `${r.slice(0, 22)}…` : r}
              </span>
            </div>
            {pivot.cols.map((c) => {
              const key = `${r}::${c}`;
              const cost = cellMap.m.get(key) ?? 0;
              const t = cellMap.max > 0 ? cost / cellMap.max : 0;
              const bg = lerpColor(t);
              const textColor = t > 0.4 ? '#fff' : '#1d1d1f';
              return (
                <div
                  key={key}
                  className="flex-1 min-w-[80px] m-[1px] rounded flex items-center justify-center py-3 transition-transform hover:scale-105 hover:z-10"
                  style={{ backgroundColor: bg, cursor: onCellClick ? 'pointer' : 'default' }}
                  title={`${r} / ${c}: ${currencyFmt.format(cost)}`}
                  onClick={() => onCellClick?.(r, c)}
                >
                  <span className="text-[10px] font-medium" style={{ color: textColor }}>
                    {cost > 0 ? compactCurrencyFmt.format(cost) : '–'}
                  </span>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Drill drawer
// ---------------------------------------------------------------------------

function DrillDrawer({
  kind, target, startDate, endDate, onClose, wsName,
}: {
  kind: 'sku' | 'origin';
  target: string;
  startDate: string;
  endDate: string;
  onClose: () => void;
  wsName: (id: string) => string;
}) {
  const query = useQuery({
    queryKey: ['so-drill', kind, target, startDate, endDate],
    queryFn: () => fetchSoDrilldown({
      startDate, endDate,
      skuName: kind === 'sku' ? target : undefined,
      billingOrigin: kind === 'origin' ? target : undefined,
    }),
    enabled: !!target,
  });

  const data = query.data;

  return (
    <div className="fixed inset-0 z-40 flex" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative ml-auto w-full max-w-[640px] h-full overflow-y-auto bg-[var(--color-bg-card)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 px-5 py-4 bg-[var(--color-bg-card)] border-b border-[var(--color-border)] flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">
              {kind === 'sku' ? 'SKU' : 'Billing Origin'} drill-in
            </p>
            <h3 className="text-sm font-semibold font-mono text-[var(--color-text-primary)] break-all">{target}</h3>
            <p className="text-xs text-[var(--color-text-muted)] mt-1">{startDate} → {endDate}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-secondary)] transition-colors"
            aria-label="Close drill drawer"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-5">
          {query.isLoading && <div className="text-xs text-[var(--color-text-muted)]">Loading…</div>}
          {data && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3">
                  <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Total cost</p>
                  <p className="text-lg font-semibold text-[var(--color-text-primary)] mt-1">
                    {currencyFmt.format(data.total_cost)}
                  </p>
                </div>
                <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3">
                  <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">Total usage</p>
                  <p className="text-lg font-semibold text-[var(--color-text-primary)] mt-1">
                    {numberFmt.format(data.total_usage)}
                  </p>
                </div>
              </div>

              <section>
                <h4 className="text-xs font-semibold text-[var(--color-text-secondary)] mb-2">Daily trend</h4>
                {data.trend.length === 0 ? (
                  <p className="text-xs text-[var(--color-text-muted)]">No daily data in period.</p>
                ) : (
                  <ResponsiveContainer width="100%" height={140}>
                    <AreaChart data={data.trend} margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
                      <defs>
                        <linearGradient id="drillFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#0071e3" stopOpacity={0.4} />
                          <stop offset="100%" stopColor="#0071e3" stopOpacity={0.02} />
                        </linearGradient>
                      </defs>
                      <XAxis
                        dataKey="usage_date"
                        tick={{ fontSize: 10, fill: '#86868b' }}
                        tickFormatter={(v: string) => v.slice(5)}
                      />
                      <YAxis tick={{ fontSize: 10, fill: '#86868b' }} tickFormatter={(v: number) => compactCurrencyFmt.format(v)} />
                      <Tooltip formatter={(v: number) => currencyFmt.format(v)} />
                      <Area type="monotone" dataKey="total_cost" stroke="#0071e3" fill="url(#drillFill)" />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </section>

              <DrillList title="Top workspaces" rows={data.top_workspaces.map((w) => {
                const name = wsName(w.label);
                const showId = name !== w.label;
                return {
                  label: name,
                  title: showId ? w.label : undefined,
                  value: w.total_cost,
                  sub: numberFmt.format(w.total_usage),
                };
              })} />

              <section>
                <h4 className="text-xs font-semibold text-[var(--color-text-secondary)] mb-2">
                  Top identities (run_as)
                </h4>
                {data.top_identities.length === 0 ? (
                  <p className="text-xs text-[var(--color-text-muted)]">No job-run identities attached.</p>
                ) : (
                  <DrillList rows={data.top_identities.map((i) => ({
                    label: i.label, value: i.total_cost, sub: numberFmt.format(i.total_usage),
                  }))} />
                )}
                {data.null_identity_cost > 0 && (
                  <p className="text-[10px] text-[var(--color-text-muted)] mt-1.5 flex items-center gap-1">
                    <Info size={11} />
                    {currencyFmt.format(data.null_identity_cost)} of cost has no <code>run_as</code> identity (interactive workloads, model serving, vector search…).
                  </p>
                )}
              </section>

              <section>
                <h4 className="text-xs font-semibold text-[var(--color-text-secondary)] mb-2">Compute owners (joined via cluster/warehouse/job tables)</h4>
                {data.related_owners.length === 0 ? (
                  <p className="text-xs text-[var(--color-text-muted)]">No matching compute owners.</p>
                ) : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-[var(--color-text-muted)] uppercase tracking-wide">
                        <th className="text-left py-1.5 px-2 font-medium">Owner</th>
                        <th className="text-left py-1.5 px-2 font-medium">Source</th>
                        <th className="text-right py-1.5 px-2 font-medium">Resources</th>
                        <th className="text-right py-1.5 px-2 font-medium">Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.related_owners.map((o, idx) => (
                        <tr key={`${o.source}-${o.owner}-${idx}`} className="border-t border-[var(--color-border)]/60">
                          <td className="py-1.5 px-2 text-[var(--color-text-primary)] break-all">{o.owner}</td>
                          <td className="py-1.5 px-2">
                            <span className="px-1.5 py-0.5 rounded text-[10px] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]">
                              {o.source}
                            </span>
                          </td>
                          <td className="py-1.5 px-2 text-right text-[var(--color-text-secondary)]">{o.resource_count}</td>
                          <td className="py-1.5 px-2 text-right text-[var(--color-text-primary)] font-medium">
                            {currencyFmt.format(o.total_cost)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function DrillList({ title, rows }: {
  title?: string;
  rows: { label: string; value: number; sub?: string; title?: string }[];
}) {
  if (rows.length === 0) {
    return (
      <section>
        {title && <h4 className="text-xs font-semibold text-[var(--color-text-secondary)] mb-2">{title}</h4>}
        <p className="text-xs text-[var(--color-text-muted)]">None.</p>
      </section>
    );
  }
  const max = Math.max(...rows.map((r) => r.value), 1e-9);
  return (
    <section>
      {title && <h4 className="text-xs font-semibold text-[var(--color-text-secondary)] mb-2">{title}</h4>}
      <ul className="space-y-1.5">
        {rows.map((r, i) => (
          <li key={`${r.label}-${i}`} className="text-xs" title={r.title}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[var(--color-text-primary)] break-all">{r.label}</span>
              <span className="text-[var(--color-text-secondary)] font-medium whitespace-nowrap">
                {currencyFmt.format(r.value)}
                {r.sub && <span className="text-[var(--color-text-muted)] ml-1">· {r.sub}</span>}
              </span>
            </div>
            <div className="mt-1 h-1.5 rounded-full bg-[var(--color-bg-secondary)] overflow-hidden">
              <div className="h-full rounded-full bg-[var(--color-primary)]" style={{ width: `${(r.value / max) * 100}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Treemap content
// ---------------------------------------------------------------------------

interface TreemapNode {
  name: string;
  value: number;
  sku?: string;
  origin?: string;
  children?: TreemapNode[];
}

interface TreemapContentProps {
  x?: number; y?: number; width?: number; height?: number;
  name?: string;
  value?: number;
  depth?: number;
  index?: number;
  payload?: TreemapNode;
  origin?: string;
  sku?: string;
}

function TreemapContent(props: TreemapContentProps) {
  const { name, depth = 0, value, index = 0 } = props;
  // Round to integer pixels — fractional coords + sub-pixel positioning is
  // what makes SVG <text> render blurry on hi-DPI screens.
  const x = Math.round(props.x ?? 0);
  const y = Math.round(props.y ?? 0);
  const width = Math.round(props.width ?? 0);
  const height = Math.round(props.height ?? 0);
  if (width < 1 || height < 1) return null;
  const isLeaf = depth >= 2;
  const fill = isLeaf
    ? COLORS[index % COLORS.length]
    : 'rgba(0, 0, 0, 0)';
  // Hi-DPI-friendly text rendering.
  const textStyle: React.CSSProperties = {
    pointerEvents: 'none',
    textRendering: 'geometricPrecision',
    fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
  };
  // ~7px per character at 11px font (slightly conservative for kerning).
  const maxChars = Math.max(0, Math.floor((width - 12) / 7));
  const label =
    name && maxChars > 1 && name.length > maxChars
      ? `${name.slice(0, maxChars - 1)}…`
      : name;
  return (
    <g>
      <rect
        x={x} y={y} width={width} height={height}
        style={{ fill, stroke: '#ffffff', strokeWidth: depth === 1 ? 2 : 1, opacity: isLeaf ? 0.82 : 1, shapeRendering: 'crispEdges' }}
      />
      {width > 70 && height > 22 && label && (
        <>
          <text
            x={x + 8}
            y={y + 16}
            fill="#ffffff"
            fontSize={11}
            fontWeight={600}
            style={textStyle}
          >
            {label}
          </text>
          {height > 38 && value !== undefined && (
            <text
              x={x + 8}
              y={y + 31}
              fill="rgba(255, 255, 255, 0.9)"
              fontSize={10}
              fontWeight={500}
              style={textStyle}
            >
              {compactCurrencyFmt.format(value)}
            </text>
          )}
        </>
      )}
    </g>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type DrillTarget = { kind: 'sku' | 'origin'; target: string } | null;

export default function SkuOrigin() {
  const [startDate, setStartDate] = useState(daysAgo(90));
  const [endDate, setEndDate] = useState(today());
  const [drill, setDrill] = useState<DrillTarget>(null);

  // --- queries ---
  const treemapQ = useQuery({ queryKey: ['so-tree', startDate, endDate], queryFn: () => fetchSoTreemap(startDate, endDate) });
  const skuLbQ = useQuery({ queryKey: ['so-sku-lb', startDate, endDate], queryFn: () => fetchSoSkuLeaderboard(startDate, endDate) });
  const origLbQ = useQuery({ queryKey: ['so-orig-lb', startDate, endDate], queryFn: () => fetchSoOriginLeaderboard(startDate, endDate) });
  const skuWsQ = useQuery({ queryKey: ['so-sku-ws', startDate, endDate], queryFn: () => fetchSoSkuWorkspaceMatrix(startDate, endDate) });
  const origWsQ = useQuery({ queryKey: ['so-orig-ws', startDate, endDate], queryFn: () => fetchSoOriginWorkspaceMatrix(startDate, endDate) });
  const skuIdQ = useQuery({ queryKey: ['so-sku-id', startDate, endDate], queryFn: () => fetchSoSkuIdentity(startDate, endDate) });
  const origIdQ = useQuery({ queryKey: ['so-orig-id', startDate, endDate], queryFn: () => fetchSoOriginIdentity(startDate, endDate) });
  const concQ = useQuery({ queryKey: ['so-conc', startDate, endDate], queryFn: () => fetchSoConcentration(startDate, endDate) });
  const trendQ = useQuery({ queryKey: ['so-trend', startDate, endDate], queryFn: () => fetchSoTrend({ startDate, endDate }) });
  const slQ = useQuery({ queryKey: ['so-sl', startDate, endDate], queryFn: () => fetchSoServerlessShare(startDate, endDate) });

  // Workspace_id → human name resolver (shared hook, cached 10 min).
  const { resolver: wsName } = useWorkspaceNames();

  // --- derived ---
  const treemapData = useMemo<TreemapNode[]>(() => {
    const items: SkuOriginTreemapItem[] = treemapQ.data?.items ?? [];
    const byOrigin = new Map<string, SkuOriginTreemapItem[]>();
    for (const it of items) {
      const arr = byOrigin.get(it.billing_origin_product) ?? [];
      arr.push(it);
      byOrigin.set(it.billing_origin_product, arr);
    }
    return [...byOrigin.entries()]
      .map(([origin, rows]) => ({
        name: origin,
        value: rows.reduce((s, r) => s + r.total_cost, 0),
        children: rows
          .map((r) => ({
            name: r.sku_name,
            value: r.total_cost,
            sku: r.sku_name,
            origin: r.billing_origin_product,
          }))
          .sort((a, b) => b.value - a.value),
      }))
      .sort((a, b) => b.value - a.value);
  }, [treemapQ.data]);

  const slChartData = useMemo(() => {
    return (slQ.data?.data ?? []).map((d) => ({
      label: d.billing_origin_product,
      serverless: d.serverless_cost,
      classic: d.classic_cost,
      unknown: d.unknown_cost,
      pct: d.serverless_pct,
    }));
  }, [slQ.data]);

  const trendChartData = useMemo(() => {
    const r = trendQ.data;
    if (!r) return { rows: [], workspaces: [] as string[] };
    const rows = r.points.map((p) => {
      const row: Record<string, string | number> = { date: p.usage_date };
      let sum = 0;
      for (const w of r.workspaces) {
        const v = Number(p.values[w] ?? 0);
        row[w] = v;
        sum += v;
      }
      const other = Number(p.other_cost ?? 0);
      row['__other'] = other;
      row['__total'] = sum + other;
      return row;
    });
    return { rows, workspaces: r.workspaces };
  }, [trendQ.data]);

  return (
    <div className="space-y-6 max-w-[1400px]">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">SKU &amp; Billing Origin</h1>
        <p className="text-sm text-[var(--color-text-muted)] mt-1">
          A 360° view pivoted on SKU and billing origin: what you're buying, who's buying it, and where the concentration sits.
        </p>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-2xl px-4 py-3">
        <Coins size={18} className="text-[var(--color-primary)] mt-0.5 shrink-0" />
        <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
          Click any SKU or billing-origin row, identity cell, or treemap tile to open a drill-in panel with daily trend, top workspaces, top
          identities, and compute-owner attribution joined from cluster / warehouse / job tables.
          Identity rows (<code>run_as</code>) only exist for job-driven workloads — interactive clusters, model
          serving, and vector search have no per-row user, so spend can appear under "no identity".
        </p>
      </div>

      <DateRangeFilter
        startDate={startDate}
        endDate={endDate}
        onStartChange={setStartDate}
        onEndChange={setEndDate}
      />

      {/* ====== Section A: Where the money goes ====== */}

      <ChartCard
        title="1 · SKU × Billing-Origin treemap"
        tooltip="Top SKU/origin combinations sized by cost. Outer tiles are billing origins; inner tiles are SKUs inside that origin. Click a tile to drill in on that SKU."
        isLoading={treemapQ.isLoading}
        exportFilename="sku-origin-treemap"
        exportRows={() => (treemapQ.data?.items ?? []).map((i) => ({
          sku_name: i.sku_name,
          billing_origin: i.billing_origin_product,
          total_cost: i.total_cost,
          total_usage: i.total_usage,
        }))}
      >
        {treemapData.length === 0 ? (
          <div className="flex items-center justify-center h-64 text-sm text-[var(--color-text-muted)]">No data</div>
        ) : (
          <ResponsiveContainer width="100%" height={460}>
            <Treemap
              data={treemapData}
              dataKey="value"
              nameKey="name"
              stroke="#fff"
              content={<TreemapContent />}
              onClick={(node: unknown) => {
                const n = node as TreemapNode | undefined;
                if (n?.sku) setDrill({ kind: 'sku', target: n.sku });
                else if (n?.name) setDrill({ kind: 'origin', target: n.name });
              }}
            />
          </ResponsiveContainer>
        )}
      </ChartCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ChartCard
          title="2 · Top SKUs"
          tooltip="Ranked by total cost over the period. Cost/unit gives a per-DBU price proxy. Click a row to drill in."
          isLoading={skuLbQ.isLoading}
          exportFilename="top-skus"
          exportRows={() => (skuLbQ.data?.data ?? []).map((s) => ({
            sku_name: s.sku_name,
            total_cost: s.total_cost,
            total_usage: s.total_usage,
            cost_per_unit: s.cost_per_unit ?? '',
            workspace_count: s.workspace_count,
            primary_billing_origin: s.primary_billing_origin ?? '',
          }))}
        >
          <Leaderboard
            rows={skuLbQ.data?.data ?? []}
            label="SKU"
            rowKey={(r: SkuLeaderboardItem) => r.sku_name}
            secondary={(r: SkuLeaderboardItem) => r.primary_billing_origin ?? '—'}
            secondaryLabel="Primary origin"
            getSparkline={(r: SkuLeaderboardItem) => r.sparkline}
            getCost={(r: SkuLeaderboardItem) => r.total_cost}
            getUsage={(r: SkuLeaderboardItem) => r.total_usage}
            getCpu={(r: SkuLeaderboardItem) => r.cost_per_unit}
            getWsCount={(r: SkuLeaderboardItem) => r.workspace_count}
            onClick={(r) => setDrill({ kind: 'sku', target: r.sku_name })}
          />
        </ChartCard>

        <ChartCard
          title="3 · Top Billing Origins"
          tooltip="Ranked by total cost. Serverless % shows how much of this origin's spend ran on serverless. Click to drill."
          isLoading={origLbQ.isLoading}
          exportFilename="top-origins"
          exportRows={() => (origLbQ.data?.data ?? []).map((o) => ({
            billing_origin: o.billing_origin_product,
            total_cost: o.total_cost,
            total_usage: o.total_usage,
            sku_count: o.sku_count,
            workspace_count: o.workspace_count,
            serverless_share_pct: o.serverless_share_pct ?? '',
          }))}
        >
          <Leaderboard
            rows={origLbQ.data?.data ?? []}
            label="Billing origin"
            rowKey={(r: OriginLeaderboardItem) => r.billing_origin_product}
            secondary={(r: OriginLeaderboardItem) => (r.serverless_share_pct == null ? '—' : `${r.serverless_share_pct.toFixed(0)}%`)}
            secondaryLabel="Serverless"
            getSparkline={(r: OriginLeaderboardItem) => r.sparkline}
            getCost={(r: OriginLeaderboardItem) => r.total_cost}
            getUsage={(r: OriginLeaderboardItem) => r.total_usage}
            getCpu={() => null}
            getWsCount={(r: OriginLeaderboardItem) => r.workspace_count}
            extraCol={{ label: 'SKUs', value: (r: OriginLeaderboardItem) => r.sku_count }}
            onClick={(r) => setDrill({ kind: 'origin', target: r.billing_origin_product })}
          />
        </ChartCard>
      </div>

      {/* ====== Section B: Who & where (heatmaps) ====== */}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <ChartCard
          title="4 · SKU × Workspace heatmap"
          tooltip="Cost intensity by SKU (rows) × workspace (columns). Top 15 of each. Click a cell to drill into the SKU."
          isLoading={skuWsQ.isLoading}
        >
          {skuWsQ.data && (
            <Heatmap
              pivot={skuWsQ.data}
              rowLabel="SKU"
              colLabel="WS"
              colDisplay={wsName}
              onCellClick={(row) => setDrill({ kind: 'sku', target: row })}
            />
          )}
        </ChartCard>

        <ChartCard
          title="5 · Billing Origin × Workspace heatmap"
          tooltip="Cost by billing origin (rows) × workspace (columns). Click to drill into the origin."
          isLoading={origWsQ.isLoading}
        >
          {origWsQ.data && (
            <Heatmap
              pivot={origWsQ.data}
              rowLabel="Origin"
              colLabel="WS"
              colDisplay={wsName}
              onCellClick={(row) => setDrill({ kind: 'origin', target: row })}
            />
          )}
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <ChartCard
          title="6 · SKU × Identity (run_as)"
          tooltip="Per-row run_as identity (mostly job runs). Cost with no identity is shown separately below the grid."
          isLoading={skuIdQ.isLoading}
        >
          {skuIdQ.data && (
            <>
              <Heatmap
                pivot={skuIdQ.data}
                rowLabel="SKU"
                colLabel="run_as"
                onCellClick={(row) => setDrill({ kind: 'sku', target: row })}
              />
              <NullIdentityFootnote cost={skuIdQ.data.null_identity_cost ?? 0} />
            </>
          )}
        </ChartCard>

        <ChartCard
          title="7 · Billing Origin × Identity (run_as)"
          tooltip="Identity attribution per billing origin. Vector search, model serving, and interactive workloads usually have no run_as."
          isLoading={origIdQ.isLoading}
        >
          {origIdQ.data && (
            <>
              <Heatmap
                pivot={origIdQ.data}
                rowLabel="Origin"
                colLabel="run_as"
                onCellClick={(row) => setDrill({ kind: 'origin', target: row })}
              />
              <NullIdentityFootnote cost={origIdQ.data.null_identity_cost ?? 0} />
            </>
          )}
        </ChartCard>
      </div>

      {/* ====== Section C: Patterns ====== */}

      <ChartCard
        title="8 · Concentration (Pareto)"
        tooltip="For each top billing origin / SKU, how much of its cost is concentrated in a few SKUs, origins, or workspaces. High top-1% means a small number of items drive most of the spend."
        isLoading={concQ.isLoading}
        exportFilename="concentration"
        exportRows={() => {
          const o = concQ.data?.by_origin ?? [];
          const s = concQ.data?.by_sku ?? [];
          return [
            ...o.map((r) => ({ section: 'by_origin', ...r })),
            ...s.map((r) => ({ section: 'by_sku', ...r })),
          ];
        }}
      >
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ConcentrationTable title="By Billing Origin" rows={concQ.data?.by_origin ?? []} variant="origin" />
          <ConcentrationTable title="By SKU" rows={concQ.data?.by_sku ?? []} variant="sku" />
        </div>
      </ChartCard>

      <ChartCard
        title="9 · Daily cost trend, stacked by workspace"
        tooltip="Daily cost split by top-5 workspaces with the remainder bucketed as 'Other'. Use this with the date filter to spot bumps."
        isLoading={trendQ.isLoading}
        exportFilename="sku-origin-trend"
        exportRows={() => trendChartData.rows as Record<string, string | number>[]}
      >
        {trendChartData.rows.length === 0 ? (
          <div className="flex items-center justify-center h-64 text-sm text-[var(--color-text-muted)]">No data</div>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <AreaChart data={trendChartData.rows} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#86868b' }} tickFormatter={(v: string) => String(v).slice(5)} />
              <YAxis tick={{ fontSize: 11, fill: '#86868b' }} tickFormatter={(v: number) => compactCurrencyFmt.format(v)} />
              <Tooltip formatter={(v: number) => currencyFmt.format(v)} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {trendChartData.workspaces.map((w, i) => (
                <Area key={w} type="monotone" dataKey={w} name={wsName(w)} stackId="1" stroke={COLORS[i % COLORS.length]}
                      fill={COLORS[i % COLORS.length]} fillOpacity={0.65} />
              ))}
              <Area key="__other" type="monotone" dataKey="__other" stackId="1" name="Other"
                    stroke="#9ca3af" fill="#9ca3af" fillOpacity={0.55} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      <ChartCard
        title="10 · Serverless vs classic share per billing origin"
        tooltip="Stacked bars show serverless vs classic cost per billing origin. Unknown is rows where is_serverless is NULL."
        isLoading={slQ.isLoading}
        exportFilename="serverless-share"
        exportRows={() => (slQ.data?.data ?? []).map((d) => ({
          billing_origin: d.billing_origin_product,
          serverless_cost: d.serverless_cost,
          classic_cost: d.classic_cost,
          unknown_cost: d.unknown_cost,
          total_cost: d.total_cost,
          serverless_pct: d.serverless_pct ?? '',
        }))}
      >
        {slChartData.length === 0 ? (
          <div className="flex items-center justify-center h-64 text-sm text-[var(--color-text-muted)]">No data</div>
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(280, slChartData.length * 28 + 40)}>
            <BarChart data={slChartData} layout="vertical" margin={{ top: 5, right: 20, left: 110, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
              <XAxis type="number" tick={{ fontSize: 10, fill: '#86868b' }} tickFormatter={(v: number) => compactCurrencyFmt.format(v)} />
              <YAxis dataKey="label" type="category" tick={{ fontSize: 10, fill: '#1d1d1f' }} width={110}
                     tickFormatter={(v: string) => (v.length > 16 ? `${v.slice(0, 16)}…` : v)} />
              <Tooltip formatter={(v: number, n: string) => [currencyFmt.format(v), n]} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="serverless" stackId="x" name="Serverless" fill="#34c759">
                {slChartData.map((_, i) => <Cell key={i} fill="#34c759" />)}
              </Bar>
              <Bar dataKey="classic" stackId="x" name="Classic" fill="#0071e3" />
              <Bar dataKey="unknown" stackId="x" name="Unknown" fill="#9ca3af" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      {drill && (
        <DrillDrawer
          kind={drill.kind}
          target={drill.target}
          startDate={startDate}
          endDate={endDate}
          onClose={() => setDrill(null)}
          wsName={wsName}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface LeaderboardProps<T> {
  rows: T[];
  label: string;
  rowKey: (r: T) => string;
  secondary: (r: T) => string;
  secondaryLabel: string;
  getSparkline: (r: T) => number[];
  getCost: (r: T) => number;
  getUsage: (r: T) => number;
  getCpu: (r: T) => number | null;
  getWsCount: (r: T) => number;
  extraCol?: { label: string; value: (r: T) => number | string };
  onClick: (r: T) => void;
}

function Leaderboard<T>(props: LeaderboardProps<T>) {
  const { rows } = props;
  if (rows.length === 0) {
    return <div className="flex items-center justify-center h-40 text-sm text-[var(--color-text-muted)]">No data</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[var(--color-text-muted)] uppercase tracking-wide border-b border-[var(--color-border)]">
            <th className="text-left py-2 px-2 font-medium">{props.label}</th>
            <th className="text-left py-2 px-2 font-medium">{props.secondaryLabel}</th>
            <th className="text-right py-2 px-2 font-medium">Cost</th>
            <th className="text-right py-2 px-2 font-medium">Usage</th>
            <th className="text-right py-2 px-2 font-medium">$ / unit</th>
            <th className="text-right py-2 px-2 font-medium">WS</th>
            {props.extraCol && <th className="text-right py-2 px-2 font-medium">{props.extraCol.label}</th>}
            <th className="text-right py-2 px-2 font-medium">Trend</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const cpu = props.getCpu(r);
            return (
              <tr
                key={props.rowKey(r)}
                onClick={() => props.onClick(r)}
                className={`border-b border-[var(--color-border)]/40 cursor-pointer transition-colors hover:bg-[var(--color-bg-secondary)] ${i % 2 === 0 ? 'bg-white' : 'bg-[#fafafa]'}`}
              >
                <td className="py-2 px-2 font-mono text-[var(--color-text-primary)] break-all max-w-[200px]">
                  {props.rowKey(r)}
                </td>
                <td className="py-2 px-2 text-[var(--color-text-secondary)]">{props.secondary(r)}</td>
                <td className="py-2 px-2 text-right font-medium text-[var(--color-text-primary)]">{currencyFmt.format(props.getCost(r))}</td>
                <td className="py-2 px-2 text-right text-[var(--color-text-secondary)]">{numberFmt.format(props.getUsage(r))}</td>
                <td className="py-2 px-2 text-right text-[var(--color-text-secondary)] font-mono">
                  {cpu == null ? '—' : `$${numberFmt.format(cpu)}`}
                </td>
                <td className="py-2 px-2 text-right text-[var(--color-text-secondary)]">{props.getWsCount(r)}</td>
                {props.extraCol && (
                  <td className="py-2 px-2 text-right text-[var(--color-text-secondary)]">{props.extraCol.value(r)}</td>
                )}
                <td className="py-2 px-2 text-right">
                  <Sparkline values={props.getSparkline(r)} color={COLORS[i % COLORS.length]} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function NullIdentityFootnote({ cost }: { cost: number }) {
  if (cost <= 0) return null;
  return (
    <p className="text-[10px] text-[var(--color-text-muted)] mt-3 flex items-center gap-1">
      <Info size={11} />
      Plus {currencyFmt.format(cost)} with no <code>run_as</code> identity (interactive clusters, serving, vector search).
    </p>
  );
}

function ConcentrationTable({ title, rows, variant }: {
  title: string;
  rows: ConcentrationRow[];
  variant: 'origin' | 'sku';
}) {
  if (rows.length === 0) {
    return <div className="text-xs text-[var(--color-text-muted)]">No data</div>;
  }
  return (
    <div>
      <h4 className="text-xs font-semibold text-[var(--color-text-secondary)] mb-2">{title}</h4>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[var(--color-text-muted)] uppercase tracking-wide border-b border-[var(--color-border)]">
              <th className="text-left py-1.5 px-2 font-medium">{variant === 'origin' ? 'Origin' : 'SKU'}</th>
              <th className="text-right py-1.5 px-2 font-medium">Cost</th>
              <th className="text-right py-1.5 px-2 font-medium">
                {variant === 'origin' ? 'Top-1 SKU' : 'Top-1 Origin'}
              </th>
              <th className="text-right py-1.5 px-2 font-medium">
                {variant === 'origin' ? 'Top-3 SKUs' : 'Top-3 Origins'}
              </th>
              <th className="text-right py-1.5 px-2 font-medium">Top-1 WS</th>
              <th className="text-right py-1.5 px-2 font-medium">Top-3 WS</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const t1 = variant === 'origin' ? r.top1_sku_pct : r.top1_origin_pct;
              const t3 = variant === 'origin' ? r.top3_sku_pct : r.top3_origin_pct;
              return (
                <tr key={r.label} className="border-b border-[var(--color-border)]/40">
                  <td className="py-1.5 px-2 font-mono text-[var(--color-text-primary)] break-all max-w-[180px]">{r.label}</td>
                  <td className="py-1.5 px-2 text-right text-[var(--color-text-primary)] font-medium">
                    {currencyFmt.format(r.total_cost)}
                  </td>
                  <td className="py-1.5 px-2 text-right"><PctBar pct={t1} /></td>
                  <td className="py-1.5 px-2 text-right"><PctBar pct={t3} /></td>
                  <td className="py-1.5 px-2 text-right"><PctBar pct={r.top1_workspace_pct} /></td>
                  <td className="py-1.5 px-2 text-right"><PctBar pct={r.top3_workspace_pct} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PctBar({ pct }: { pct: number | null | undefined }) {
  if (pct == null) return <span className="text-[var(--color-text-muted)]">—</span>;
  const color = pct >= 80 ? '#ff3b30' : pct >= 50 ? '#ff9500' : '#0071e3';
  return (
    <div className="inline-flex items-center gap-1.5 min-w-[64px] justify-end">
      <div className="h-1.5 w-10 rounded-full bg-[var(--color-bg-secondary)] overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${Math.min(100, pct)}%`, backgroundColor: color }} />
      </div>
      <span className="font-mono text-[var(--color-text-secondary)]">{pct.toFixed(0)}%</span>
    </div>
  );
}
