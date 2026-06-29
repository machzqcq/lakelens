/**
 * Shared layout + utilities for the Query Profiler pages.
 *
 * Every Query Profiler page is rendered inside `<QiShell title>...</QiShell>`
 * so the header style and section spacing are consistent. We also export
 * a small set of formatters so chart tooltips agree on number/byte/duration
 * presentation across the whole module.
 */
import { ReactNode } from 'react';
import InfoTooltip from '../../components/InfoTooltip';

export function QiShell({ title, intro, children }: { title: string; intro?: string; children: ReactNode }) {
  return (
    <div className="space-y-6 max-w-[1400px]">
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">{title}</h1>
        {intro && <p className="text-sm text-[var(--color-text-muted)] mt-1">{intro}</p>}
      </div>
      {children}
    </div>
  );
}

export function QiCard({ title, tooltip, children, className = '' }: {
  title: string;
  tooltip?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`bg-white border border-[var(--color-border)] rounded-2xl p-5 shadow-sm ${className}`}>
      <h2 className="text-sm font-semibold text-[var(--color-text-primary)] mb-4 flex items-center gap-2">
        {title}
        {tooltip && <InfoTooltip text={tooltip} />}
      </h2>
      {children}
    </div>
  );
}

export const fmtInt = new Intl.NumberFormat('en-US');
export const fmtPct = (n: number | null | undefined, digits = 1) =>
  n === null || n === undefined ? '—' : `${(n * 100).toFixed(digits)}%`;

export function fmtBytes(b: number | null | undefined): string {
  if (b == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = b;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${(ms / 60_000).toFixed(1)} min`;
}

export const CHART_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#84cc16', '#ec4899', '#6366f1', '#14b8a6',
];

export function NoDataNote() {
  return (
    <div className="bg-yellow-50 border border-yellow-200 rounded-2xl px-4 py-6 text-center">
      <p className="text-sm text-yellow-800 font-medium">No Query Profiler data yet.</p>
      <p className="text-xs text-yellow-700 mt-1">
        Go to <strong>Data Management → Extract query profiler</strong> to populate the qi_* tables, then come back.
      </p>
    </div>
  );
}

export function LoadingNote() {
  return <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>;
}

export function ErrorNote({ error }: { error: Error }) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-2xl px-4 py-3">
      <p className="text-sm font-medium text-red-700">Error</p>
      <p className="text-xs text-red-600 mt-1">{error.message}</p>
    </div>
  );
}

export function MiniTable({ rows, columns, emptyMessage = 'No rows.' }: {
  rows: any[];
  columns: { key: string; label: string; align?: 'left' | 'right'; render?: (v: any, row: any) => ReactNode }[];
  emptyMessage?: string;
}) {
  if (!rows || rows.length === 0) {
    return <p className="text-sm text-[var(--color-text-muted)]">{emptyMessage}</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left border-b border-[var(--color-border)]">
            {columns.map((c) => (
              <th key={c.key}
                  className={`py-2 px-3 text-xs font-medium text-[var(--color-text-muted)] ${c.align === 'right' ? 'text-right' : ''}`}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-[var(--color-border)]/40 hover:bg-[var(--color-bg-secondary)]">
              {columns.map((c) => (
                <td key={c.key} className={`py-2 px-3 ${c.align === 'right' ? 'text-right tabular-nums' : ''}`}>
                  {c.render ? c.render(row[c.key], row) : (row[c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
