import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer,
} from 'recharts';
import { Users } from 'lucide-react';

import ChartCard from '../components/ChartCard';
import DateRangeFilter from '../components/DateRangeFilter';
import InfoTooltip from '../components/InfoTooltip';
import {
  fetchByUser,
  fetchBySkuUser,
  fetchDailyTrend,
  fetchUserUtilization,
} from '../api/client';
import type {
  SkuUserMatrixResponse,
  UserResourceUsage,
} from '../types/api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const COLORS = [
  '#0071e3', '#34c759', '#ff9500', '#af52de', '#ff3b30',
  '#5ac8fa', '#ff2d55', '#00856f', '#5856d6', '#ffcc00',
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

function truncate(s: string, max = 24): string {
  return s.length > max ? `${s.slice(0, max)}...` : s;
}

// Custom area chart tooltip
function TrendTooltipContent({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-3 shadow-lg text-xs">
      <p className="font-medium text-gray-900 mb-1.5">{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} className="text-gray-600">
          <span className="inline-block w-2 h-2 rounded-full mr-1.5" style={{ backgroundColor: p.stroke }} />
          <span style={{ color: p.stroke }}>{p.name}</span>:{' '}
          {p.dataKey === 'total_cost' ? fmtCost(p.value) : fmtNumber(p.value)}
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SKU x User matrix
// ---------------------------------------------------------------------------

type Cell = SkuUserMatrixResponse['cells'][number];
type SelectedPair = { sku: string; user: string } | null;

function cellColor(intensity: number): string {
  const alpha = 0.08 + 0.85 * intensity;
  return `rgba(0, 113, 227, ${alpha.toFixed(3)})`;
}

function SkuUserMatrix({
  matrix,
  selected,
  onSelect,
}: {
  matrix: SkuUserMatrixResponse;
  selected: SelectedPair;
  onSelect: (pair: SelectedPair) => void;
}) {
  const { skus, users, cells } = matrix;
  const lookup = new Map<string, Cell>();
  let maxCost = 0;
  for (const c of cells) {
    lookup.set(`${c.sku_name}|${c.run_as}`, c);
    if (c.total_cost > maxCost) maxCost = c.total_cost;
  }
  const skuTotals = new Map<string, number>();
  const userTotals = new Map<string, number>();
  for (const c of cells) {
    skuTotals.set(c.sku_name, (skuTotals.get(c.sku_name) ?? 0) + c.total_cost);
    userTotals.set(c.run_as, (userTotals.get(c.run_as) ?? 0) + c.total_cost);
  }

  if (skus.length === 0 || users.length === 0) {
    return (
      <p className="text-center text-xs text-[var(--color-text-muted)] py-8">
        No SKU x user data available for the selected range.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="border-separate border-spacing-0 text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-[var(--color-bg-card)] px-2 py-2 text-left font-semibold text-[var(--color-text-muted)] min-w-[200px]">
              SKU \ User
            </th>
            {users.map((u) => (
              <th
                key={u}
                title={u}
                className="px-2 py-2 font-medium text-[var(--color-text-secondary)] text-left whitespace-nowrap"
                style={{ minWidth: 110 }}
              >
                <div className="truncate max-w-[120px]">{u}</div>
                <div className="text-[10px] font-normal text-[var(--color-text-muted)] mt-0.5">
                  {fmtCost(userTotals.get(u) ?? 0)}
                </div>
              </th>
            ))}
            <th className="px-2 py-2 font-semibold text-[var(--color-text-muted)] text-right whitespace-nowrap bg-[var(--color-bg-secondary)]">
              Row total
            </th>
          </tr>
        </thead>
        <tbody>
          {skus.map((sku) => (
            <tr key={sku}>
              <td
                title={sku}
                className="sticky left-0 z-10 bg-[var(--color-bg-card)] px-2 py-1.5 font-mono text-[var(--color-text-primary)] border-t border-[var(--color-border)]"
              >
                <div className="truncate max-w-[220px]">{sku}</div>
              </td>
              {users.map((u) => {
                const c = lookup.get(`${sku}|${u}`);
                const cost = c?.total_cost ?? 0;
                const intensity = maxCost > 0 ? cost / maxCost : 0;
                const isSelected = selected?.sku === sku && selected?.user === u;
                return (
                  <td
                    key={u}
                    onClick={() => onSelect(cost > 0 ? (isSelected ? null : { sku, user: u }) : null)}
                    title={cost > 0 ? `${sku} x ${u}\n${fmtCost(cost)}` : 'No usage'}
                    className={`px-2 py-1.5 text-right font-mono cursor-pointer border-t border-[var(--color-border)] transition-all ${
                      isSelected ? 'ring-2 ring-[var(--color-primary)] ring-inset' : ''
                    } ${cost === 0 ? 'cursor-default' : 'hover:opacity-80'}`}
                    style={{
                      backgroundColor: cost > 0 ? cellColor(intensity) : 'transparent',
                      color: intensity > 0.55 ? 'white' : 'var(--color-text-primary)',
                    }}
                  >
                    {cost > 0 ? fmtCost(cost) : '-'}
                  </td>
                );
              })}
              <td className="px-2 py-1.5 text-right font-mono font-semibold text-[var(--color-text-primary)] border-t border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
                {fmtCost(skuTotals.get(sku) ?? 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// User breakdown table
// ---------------------------------------------------------------------------

interface UserBreakdownRow {
  primary: string;
  secondary: string | null;
  total_usage: number;
  total_cost: number;
}

function UserBreakdownTable({
  rows,
  primaryHeader,
}: {
  rows: UserBreakdownRow[];
  primaryHeader: string;
}) {
  if (rows.length === 0) {
    return <p className="text-xs text-[var(--color-text-muted)] text-center py-6">No usage in this category.</p>;
  }
  const total = rows.reduce((s, r) => s + r.total_cost, 0);
  return (
    <div className="overflow-y-auto max-h-[320px]">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-[var(--color-bg-secondary)] z-10">
          <tr>
            <th className="px-2 py-2 text-left font-semibold text-[var(--color-text-muted)]">{primaryHeader}</th>
            <th className="px-2 py-2 text-right font-semibold text-[var(--color-text-muted)] whitespace-nowrap">DBU</th>
            <th className="px-2 py-2 text-right font-semibold text-[var(--color-text-muted)] whitespace-nowrap">Cost</th>
            <th className="px-2 py-2 text-right font-semibold text-[var(--color-text-muted)] whitespace-nowrap">%</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const pct = total > 0 ? (r.total_cost / total) * 100 : 0;
            return (
              <tr key={`${r.primary}-${i}`} className="border-t border-[var(--color-border)]/50">
                <td className="px-2 py-1.5 text-[var(--color-text-primary)]">
                  <div className="font-medium truncate max-w-[200px]" title={r.primary}>{r.primary}</div>
                  {r.secondary && (
                    <div className="text-[10px] font-mono text-[var(--color-text-muted)] truncate max-w-[200px]" title={r.secondary}>
                      {r.secondary}
                    </div>
                  )}
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-[var(--color-text-secondary)]">
                  {fmtNumber(r.total_usage)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono font-semibold text-[var(--color-text-primary)]">
                  {fmtCost(r.total_cost)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-[var(--color-text-muted)]">
                  {fmtPct(pct)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function UserFootprint() {
  const [startDate, setStartDate] = useState(daysAgo(90));
  const [endDate, setEndDate] = useState(today());

  // SKU x user matrix state
  const [matrixTopSkus, setMatrixTopSkus] = useState(10);
  const [matrixTopUsers, setMatrixTopUsers] = useState(10);
  const [selectedPair, setSelectedPair] = useState<SelectedPair>(null);

  // User utilization pivot state
  const [selectedUser, setSelectedUser] = useState<string>('');

  // --- Queries ---
  const skuUserQuery = useQuery({
    queryKey: ['userFootprint', 'skuUserMatrix', startDate, endDate, matrixTopSkus, matrixTopUsers],
    queryFn: () => fetchBySkuUser(startDate, endDate, matrixTopSkus, matrixTopUsers),
  });

  const pairTrendQuery = useQuery({
    queryKey: ['userFootprint', 'pairTrend', startDate, endDate, selectedPair?.sku, selectedPair?.user],
    queryFn: () =>
      fetchDailyTrend(startDate, endDate, selectedPair!.sku, undefined, selectedPair!.user).then((r) => r.data),
    enabled: selectedPair !== null,
  });

  const usersListQuery = useQuery({
    queryKey: ['userFootprint', 'usersList', startDate, endDate],
    queryFn: () => fetchByUser(startDate, endDate, 100).then((r) => r.data),
  });

  const userUtilQuery = useQuery({
    queryKey: ['userFootprint', 'userUtil', startDate, endDate, selectedUser],
    queryFn: () => fetchUserUtilization(selectedUser, startDate, endDate),
    enabled: selectedUser !== '',
  });

  const userTrendQuery = useQuery({
    queryKey: ['userFootprint', 'userTrend', startDate, endDate, selectedUser],
    queryFn: () => fetchDailyTrend(startDate, endDate, undefined, undefined, selectedUser).then((r) => r.data),
    enabled: selectedUser !== '',
  });

  return (
    <div className="space-y-6 max-w-[1600px]">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <Users size={24} className="text-[var(--color-primary)]" />
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">User Footprint</h1>
        </div>
        <div className="bg-blue-50 border border-blue-200 rounded-2xl px-4 py-3 text-xs text-[var(--color-text-secondary)] leading-relaxed">
          Pivot Databricks spend on the run_as identity. The SKU x User matrix surfaces top spenders
          and what they buy; the per-user pivot drills into one user's full footprint across SKUs,
          clusters, and warehouses. All charts have CSV / Excel exports.
        </div>
      </div>

      {/* Date range */}
      <DateRangeFilter
        startDate={startDate}
        endDate={endDate}
        onStartChange={setStartDate}
        onEndChange={setEndDate}
      />

      {/* SKU x User matrix */}
      <ChartCard
        title="SKU x User Cost Matrix"
        tooltip="Cost in USD for each top-N SKU (rows) consumed by each top-N user (columns) over the selected date range. Cell shading is proportional to cost (darker = more spend). Click a cell to see the daily trend for that pair."
        isLoading={skuUserQuery.isLoading}
        exportFilename="sku-x-user-cost"
        exportRows={() => (skuUserQuery.data?.cells ?? []).map((c) => ({
          sku_name: c.sku_name,
          user: c.run_as,
          total_usage: c.total_usage,
          total_cost: c.total_cost,
        }))}
      >
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <div className="flex items-center gap-2">
            <label className="text-xs text-[var(--color-text-muted)]">Top SKUs:</label>
            <select
              value={matrixTopSkus}
              onChange={(e) => { setMatrixTopSkus(Number(e.target.value)); setSelectedPair(null); }}
              className="text-xs bg-white border border-[var(--color-border)] rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20"
            >
              {[5, 10, 15, 20, 30, 50].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-[var(--color-text-muted)]">Top users:</label>
            <select
              value={matrixTopUsers}
              onChange={(e) => { setMatrixTopUsers(Number(e.target.value)); setSelectedPair(null); }}
              className="text-xs bg-white border border-[var(--color-border)] rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20"
            >
              {[5, 10, 15, 20, 30, 50].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          {selectedPair && (
            <div className="ml-auto flex items-center gap-2 text-xs">
              <span className="text-[var(--color-text-muted)]">Selected:</span>
              <span className="font-mono text-[var(--color-text-primary)]" title={selectedPair.sku}>
                {truncate(selectedPair.sku, 32)}
              </span>
              <span className="text-[var(--color-text-muted)]">x</span>
              <span className="font-mono text-[var(--color-text-primary)]" title={selectedPair.user}>
                {truncate(selectedPair.user, 32)}
              </span>
              <button
                onClick={() => setSelectedPair(null)}
                className="text-[var(--color-primary-light)] hover:underline ml-2"
              >
                Clear
              </button>
            </div>
          )}
        </div>

        {skuUserQuery.data && (
          <SkuUserMatrix
            matrix={skuUserQuery.data}
            selected={selectedPair}
            onSelect={setSelectedPair}
          />
        )}

        {/* Per-pair trend */}
        {selectedPair && (
          <div className="mt-5 pt-5 border-t border-[var(--color-border)]">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-3">
              Daily trend - {truncate(selectedPair.sku, 28)} x {truncate(selectedPair.user, 28)}
            </h4>
            {pairTrendQuery.isLoading ? (
              <p className="text-xs text-[var(--color-text-muted)] text-center py-8">Loading trend...</p>
            ) : (pairTrendQuery.data ?? []).length === 0 ? (
              <p className="text-xs text-[var(--color-text-muted)] text-center py-8">No daily activity for this pair.</p>
            ) : (
              <div className="h-[220px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={pairTrendQuery.data ?? []} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
                    <defs>
                      <linearGradient id="gradPairCost" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={COLORS[0]} stopOpacity={0.25} />
                        <stop offset="95%" stopColor={COLORS[0]} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
                    <XAxis
                      dataKey="usage_date"
                      tick={{ fontSize: 11, fill: '#86868b' }}
                      tickFormatter={(v: string) => v.slice(5)}
                    />
                    <YAxis
                      tick={{ fontSize: 11, fill: '#86868b' }}
                      tickFormatter={(v) => fmtCost(v)}
                    />
                    <RechartsTooltip content={<TrendTooltipContent />} />
                    <Area
                      type="monotone"
                      dataKey="total_cost"
                      name="Cost ($)"
                      stroke={COLORS[0]}
                      fill="url(#gradPairCost)"
                      strokeWidth={2}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        )}
      </ChartCard>

      {/* User Utilization Pivot */}
      <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-2xl p-5 shadow-sm space-y-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
              User Utilization Pivot
              <InfoTooltip text="Pick any user (top 100 by spend in the selected range) to see their full utilization split across SKUs, clusters, and warehouses. Each table has its own CSV / Excel export." />
            </h3>
            <p className="text-xs text-[var(--color-text-muted)] mt-1">
              Drill into a single user's compute footprint.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-[var(--color-text-muted)]">User:</label>
            <select
              value={selectedUser}
              onChange={(e) => setSelectedUser(e.target.value)}
              className="text-xs bg-white border border-[var(--color-border)] rounded-lg px-2 py-1.5 min-w-[260px] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20"
            >
              <option value="">-- Select a user --</option>
              {(usersListQuery.data ?? []).map((u) => (
                <option key={u.user} value={u.user}>
                  {u.user} ({fmtCost(u.total_cost)})
                </option>
              ))}
            </select>
            {selectedUser && (
              <button
                onClick={() => setSelectedUser('')}
                className="text-xs text-[var(--color-primary-light)] hover:underline ml-1"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {!selectedUser ? (
          <p className="text-center text-xs text-[var(--color-text-muted)] py-10">
            Select a user above to see their utilization breakdown.
          </p>
        ) : userUtilQuery.isLoading ? (
          <p className="text-center text-xs text-[var(--color-text-muted)] py-10">Loading utilization...</p>
        ) : userUtilQuery.data ? (
          <>
            {/* Summary KPIs */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">Total Cost</p>
                <p className="text-lg font-bold text-[var(--color-text-primary)]">{fmtCost(userUtilQuery.data.total_cost)}</p>
              </div>
              <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">Total DBUs</p>
                <p className="text-lg font-bold text-[var(--color-text-primary)]">{fmtNumber(userUtilQuery.data.total_usage)}</p>
              </div>
              <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">SKUs / Clusters / Warehouses</p>
                <p className="text-lg font-bold text-[var(--color-text-primary)]">
                  {userUtilQuery.data.skus.length} / {userUtilQuery.data.clusters.length} / {userUtilQuery.data.warehouses.length}
                </p>
              </div>
              <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">Period</p>
                <p className="text-sm font-medium text-[var(--color-text-primary)]">{startDate} to {endDate}</p>
              </div>
            </div>

            {/* Three breakdown tables */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <ChartCard
                title="SKUs"
                tooltip="Every SKU consumed by this user in the selected range, sorted by cost desc."
                exportFilename={`user-${selectedUser}-skus`}
                exportRows={() => (userUtilQuery.data?.skus ?? []).map((s) => ({
                  sku_name: s.sku_name,
                  total_usage: s.total_usage,
                  total_cost: s.total_cost,
                }))}
              >
                <UserBreakdownTable
                  rows={(userUtilQuery.data?.skus ?? []).map((s) => ({
                    primary: s.sku_name,
                    secondary: null,
                    total_usage: s.total_usage,
                    total_cost: s.total_cost,
                  }))}
                  primaryHeader="SKU"
                />
              </ChartCard>

              <ChartCard
                title="Clusters"
                tooltip="Every cluster this user ran on, with the latest known cluster name."
                exportFilename={`user-${selectedUser}-clusters`}
                exportRows={() => (userUtilQuery.data?.clusters ?? []).map((c: UserResourceUsage) => ({
                  cluster_id: c.resource_id,
                  cluster_name: c.resource_name ?? '',
                  total_usage: c.total_usage,
                  total_cost: c.total_cost,
                }))}
              >
                <UserBreakdownTable
                  rows={(userUtilQuery.data?.clusters ?? []).map((c) => ({
                    primary: c.resource_name ?? c.resource_id,
                    secondary: c.resource_id,
                    total_usage: c.total_usage,
                    total_cost: c.total_cost,
                  }))}
                  primaryHeader="Cluster"
                />
              </ChartCard>

              <ChartCard
                title="Warehouses"
                tooltip="SQL warehouses owned by this user (warehouses.created_by = user) and the cost they incurred in the period. Note: Databricks rarely populates the run_as identity on warehouse usage rows, so this view attributes by ownership rather than by who ran the queries."
                exportFilename={`user-${selectedUser}-warehouses`}
                exportRows={() => (userUtilQuery.data?.warehouses ?? []).map((w: UserResourceUsage) => ({
                  warehouse_id: w.resource_id,
                  warehouse_name: w.resource_name ?? '',
                  total_usage: w.total_usage,
                  total_cost: w.total_cost,
                }))}
              >
                <UserBreakdownTable
                  rows={(userUtilQuery.data?.warehouses ?? []).map((w) => ({
                    primary: w.resource_name ?? w.resource_id,
                    secondary: w.resource_id,
                    total_usage: w.total_usage,
                    total_cost: w.total_cost,
                  }))}
                  primaryHeader="Warehouse"
                />
              </ChartCard>
            </div>

            {/* Daily trend for the user */}
            <ChartCard
              title={`Daily Trend - ${selectedUser}`}
              tooltip="Daily cost and DBU usage attributed to this user across all SKUs and resources."
              isLoading={userTrendQuery.isLoading}
              exportFilename={`user-${selectedUser}-daily-trend`}
              exportRows={() => (userTrendQuery.data ?? []).map((r) => ({
                usage_date: r.usage_date,
                total_cost: r.total_cost,
                total_usage: r.total_usage,
              }))}
            >
              {(userTrendQuery.data ?? []).length === 0 ? (
                <p className="text-center text-xs text-[var(--color-text-muted)] py-8">No daily activity for this user.</p>
              ) : (
                <div className="h-[240px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={userTrendQuery.data ?? []} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
                      <defs>
                        <linearGradient id="gradUserCost" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={COLORS[0]} stopOpacity={0.25} />
                          <stop offset="95%" stopColor={COLORS[0]} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
                      <XAxis
                        dataKey="usage_date"
                        tick={{ fontSize: 11, fill: '#86868b' }}
                        tickFormatter={(v: string) => v.slice(5)}
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: '#86868b' }}
                        tickFormatter={(v) => fmtCost(v)}
                      />
                      <RechartsTooltip content={<TrendTooltipContent />} />
                      <Area
                        type="monotone"
                        dataKey="total_cost"
                        name="Cost ($)"
                        stroke={COLORS[0]}
                        fill="url(#gradUserCost)"
                        strokeWidth={2}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </ChartCard>
          </>
        ) : (
          <p className="text-center text-xs text-[var(--color-text-muted)] py-10">No data available for this user.</p>
        )}
      </div>
    </div>
  );
}
