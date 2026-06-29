/**
 * Shared building blocks for the Table-Lineage and Column-Lineage dashboards.
 *
 * The graph is plain SVG (no external lib): three columns of pill nodes,
 * bezier connectors, click-to-re-centre. Sufficient for depth-1 views;
 * deeper walks happen via re-centering. The Table and Column pages each
 * call <GraphCard> with their own `items` shape.
 */
import { useQuery } from '@tanstack/react-query';
import { Loader2, GitBranch, ArrowLeft } from 'lucide-react';
import {
  metaExplorer,
  type LineageNeighbour,
  type ColumnLineageNeighbour,
} from '../../api/client';

export const numberFmt = new Intl.NumberFormat('en-US');

export function truncate(s: string, n: number): string {
  if (!s) return '';
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

export interface GraphItem {
  id: string;
  title: string;
  subtitle: string;
  badge?: string;
  count: number;
  extra?: string;
}

export function neighbourToItem(n: LineageNeighbour): GraphItem {
  return {
    id: n.full_name,
    title: n.table_name ?? n.full_name,
    subtitle: [n.catalog, n.database].filter(Boolean).join('.') || n.full_name,
    badge: n.type ?? undefined,
    count: n.edge_count,
    extra: n.sample_entities.slice(0, 2).join(', '),
  };
}

export function columnNeighbourToItem(n: ColumnLineageNeighbour): GraphItem {
  return {
    id: `${n.full_name}::${n.column_name}`,
    title: n.column_name,
    subtitle: n.full_name,
    badge: undefined,
    count: n.edge_count,
    extra: '',
  };
}

// --------------------------------------------------------------------------
// Column-picker dropdown (used by the Column Lineage page).

export function ColumnPicker({
  tableFullName, value, onChange,
}: {
  tableFullName: string;
  value: string | null;
  onChange: (col: string | null) => void;
}) {
  const parts = tableFullName.split('.');
  const [catalog, database, table_name] = parts.length === 3 ? parts : [null, null, null];
  const detailQ = useQuery({
    queryKey: ['meta-table-detail', catalog, database, table_name],
    queryFn:  () => metaExplorer.tableDetail(catalog!, database!, table_name!),
    enabled: !!catalog && !!database && !!table_name,
  });
  const columns = detailQ.data?.columns ?? [];
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-[var(--color-text-muted)]">Centre column:</span>
      <select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        className="bg-white border border-[var(--color-border)] rounded-lg px-2 py-1 text-xs font-mono"
        disabled={!columns.length}
      >
        <option value="">— pick a column —</option>
        {columns.map((c) => (
          <option key={c.col_name} value={c.col_name}>{c.col_name}</option>
        ))}
      </select>
      <span className="text-[10px] text-[var(--color-text-muted)]">
        {numberFmt.format(columns.length)} column{columns.length === 1 ? '' : 's'} in <code>{tableFullName}</code>
      </span>
    </div>
  );
}


// --------------------------------------------------------------------------
// Three-column SVG graph card.

export function GraphCard({
  title, subtitle, loading,
  leftLabel, rightLabel, centerLabel,
  leftItems, rightItems,
  onPickItem,
}: {
  title: string;
  subtitle: React.ReactNode;
  loading: boolean;
  leftLabel: string;
  rightLabel: string;
  centerLabel: string;
  leftItems: GraphItem[];
  rightItems: GraphItem[];
  onPickItem: (it: GraphItem) => void;
}) {
  const ROW_H = 56;
  const PAD_TOP = 40;
  const W = 1200;
  const COL_W = 320;
  const LEFT_X = 30;
  const RIGHT_X = W - 30 - COL_W;
  const CENTER_X = (LEFT_X + COL_W + RIGHT_X) / 2;
  const maxRows = Math.max(leftItems.length, rightItems.length, 1);
  const H = PAD_TOP + maxRows * ROW_H + 30;
  const centerY = PAD_TOP + (maxRows * ROW_H) / 2 - ROW_H / 2;

  return (
    <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-[var(--color-text-primary)] flex items-center gap-1">
            <GitBranch size={14} className="text-fuchsia-600" /> {title}
          </h3>
          <p className="text-[11px] text-[var(--color-text-muted)] mt-0.5">{subtitle}</p>
        </div>
        {loading && (
          <p className="text-xs text-[var(--color-text-muted)] flex items-center gap-1">
            <Loader2 size={12} className="animate-spin" /> Loading…
          </p>
        )}
      </div>

      <div className="overflow-auto">
        <svg width={W} height={H} role="img" aria-label={title}
          className="bg-[var(--color-bg-secondary)]/40 rounded-xl">
          <text x={LEFT_X + COL_W / 2} y={20} textAnchor="middle"
            className="fill-[var(--color-text-secondary)]" style={{ fontSize: 11, fontWeight: 600 }}>
            {leftLabel} →
          </text>
          <text x={CENTER_X} y={20} textAnchor="middle"
            className="fill-fuchsia-700" style={{ fontSize: 11, fontWeight: 700 }}>
            CENTRE
          </text>
          <text x={RIGHT_X + COL_W / 2} y={20} textAnchor="middle"
            className="fill-[var(--color-text-secondary)]" style={{ fontSize: 11, fontWeight: 600 }}>
            → {rightLabel}
          </text>

          <g>
            <rect x={CENTER_X - 110} y={centerY} width={220} height={40} rx={10} fill="#a21caf" />
            <text x={CENTER_X} y={centerY + 25} textAnchor="middle"
              fill="white" style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 600 }}>
              {truncate(centerLabel, 28)}
            </text>
          </g>

          {leftItems.map((it, i) => (
            <GraphNode
              key={`L${it.id}`} side="left"
              x={LEFT_X} y={PAD_TOP + i * ROW_H} w={COL_W} item={it}
              centerX={CENTER_X - 110} centerY={centerY + 20}
              onPick={() => onPickItem(it)}
            />
          ))}
          {rightItems.map((it, i) => (
            <GraphNode
              key={`R${it.id}`} side="right"
              x={RIGHT_X} y={PAD_TOP + i * ROW_H} w={COL_W} item={it}
              centerX={CENTER_X + 110} centerY={centerY + 20}
              onPick={() => onPickItem(it)}
            />
          ))}

          {leftItems.length === 0 && (
            <text x={LEFT_X + COL_W / 2} y={centerY + 25} textAnchor="middle"
              className="fill-[var(--color-text-muted)] italic" style={{ fontSize: 11 }}>
              no upstream edges
            </text>
          )}
          {rightItems.length === 0 && (
            <text x={RIGHT_X + COL_W / 2} y={centerY + 25} textAnchor="middle"
              className="fill-[var(--color-text-muted)] italic" style={{ fontSize: 11 }}>
              no downstream edges
            </text>
          )}
        </svg>
      </div>
      <p className="text-[10px] text-[var(--color-text-muted)] mt-2 flex items-center gap-1">
        <ArrowLeft size={10} /> Click any neighbour to re-centre on it.
      </p>
    </div>
  );
}

function GraphNode({
  side, x, y, w, item, centerX, centerY, onPick,
}: {
  side: 'left' | 'right';
  x: number; y: number; w: number;
  item: GraphItem;
  centerX: number; centerY: number;
  onPick: () => void;
}) {
  const NODE_H = 44;
  const anchorX = side === 'left' ? x + w : x;
  const anchorY = y + NODE_H / 2;
  const dx = (centerX - anchorX) / 2;
  const path = `M ${anchorX} ${anchorY} C ${anchorX + dx} ${anchorY}, ${centerX - dx} ${centerY}, ${centerX} ${centerY}`;
  const strokeW = Math.min(4, 0.8 + Math.log10(item.count + 1) * 1.2);
  return (
    <g onClick={onPick} style={{ cursor: 'pointer' }}>
      <path d={path} fill="none" stroke="#c026d3" strokeOpacity={0.5} strokeWidth={strokeW} />
      <rect x={x} y={y} width={w} height={NODE_H} rx={8}
        fill="white" stroke="#d8b4fe" strokeWidth={1.5}
        className="transition-colors hover:fill-fuchsia-50" />
      <text x={x + 10} y={y + 16} fill="#1f2937"
        style={{ fontSize: 11, fontFamily: 'monospace', fontWeight: 600 }}>
        {truncate(item.title, 32)}
      </text>
      <text x={x + 10} y={y + 32} fill="#6b7280"
        style={{ fontSize: 10, fontFamily: 'monospace' }}>
        {truncate(item.subtitle, 38)}
      </text>
      <text x={x + w - 10} y={y + 16} fill="#a21caf" textAnchor="end"
        style={{ fontSize: 10, fontWeight: 600 }}>
        ×{numberFmt.format(item.count)}
      </text>
      {item.badge && (
        <text x={x + w - 10} y={y + 32} fill="#6b7280" textAnchor="end"
          style={{ fontSize: 9 }}>
          {truncate(item.badge, 20)}
        </text>
      )}
    </g>
  );
}

// --------------------------------------------------------------------------
// Search box + result list shared by both pages.

export function LineageSearchBox({
  search, setSearch, activeSearch, setActiveSearch,
  results, loading, onPick, placeholder,
}: {
  search: string;
  setSearch: (s: string) => void;
  activeSearch: string;
  setActiveSearch: (s: string) => void;
  results: { full_name: string; table_edges_in: number; table_edges_out: number }[] | undefined;
  loading: boolean;
  onPick: (fn: string) => void;
  placeholder: string;
}) {
  return (
    <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4 shadow-sm space-y-2">
      <div className="flex gap-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') setActiveSearch(search.trim()); }}
          placeholder={placeholder}
          className="flex-1 bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm"
        />
        <button
          onClick={() => setActiveSearch(search.trim())}
          disabled={search.trim().length < 2}
          className="flex items-center gap-1 px-3 py-2 rounded-full bg-fuchsia-600 text-white text-sm font-medium hover:bg-fuchsia-700 disabled:opacity-50"
        >
          Search
        </button>
      </div>
      {activeSearch && (
        <div className="border border-[var(--color-border)] rounded-lg max-h-56 overflow-auto">
          {loading && <p className="px-3 py-2 text-xs text-[var(--color-text-muted)]"><Loader2 size={12} className="animate-spin inline mr-1" /> Searching…</p>}
          {!loading && (results ?? []).length === 0 && (
            <p className="px-3 py-2 text-xs text-[var(--color-text-muted)]">No matches.</p>
          )}
          {(results ?? []).map((h) => (
            <button
              key={h.full_name}
              onClick={() => onPick(h.full_name)}
              className="w-full flex items-center justify-between gap-3 px-3 py-1.5 text-xs text-left hover:bg-fuchsia-50 border-b border-[var(--color-border)]/40 last:border-b-0"
            >
              <span className="font-mono truncate">{h.full_name}</span>
              <span className="shrink-0 text-[10px] text-[var(--color-text-muted)]">
                in:{numberFmt.format(h.table_edges_in)} · out:{numberFmt.format(h.table_edges_out)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Top list — used for source/target/entity/column rollups.

export function TopList({
  title, subtitle, items, onPick,
}: {
  title: string;
  subtitle: string;
  items: { label: string; edge_count: number }[];
  onPick: (label: string) => void;
}) {
  return (
    <div className="bg-white border border-[var(--color-border)] rounded-2xl p-3 shadow-sm">
      <h3 className="text-xs font-semibold text-[var(--color-text-primary)]">{title}</h3>
      <p className="text-[10px] text-[var(--color-text-muted)] mt-0.5 mb-2">{subtitle}</p>
      <ul className="divide-y divide-[var(--color-border)]/60 max-h-72 overflow-auto">
        {items.length === 0 && (
          <li className="text-xs text-[var(--color-text-muted)] italic py-1.5">no rows</li>
        )}
        {items.map((it) => (
          <li key={it.label}>
            <button
              onClick={() => onPick(it.label)}
              className="w-full flex items-center justify-between gap-2 px-1.5 py-1 text-xs hover:bg-fuchsia-50 text-left"
            >
              <span className="font-mono truncate" title={it.label}>{it.label}</span>
              <span className="shrink-0 text-[10px] text-[var(--color-text-muted)]">
                {numberFmt.format(it.edge_count)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// --------------------------------------------------------------------------
// Compact breakdown bar — used for source_type / entity_type histograms.

export function BreakdownBar({
  title, items, total, accent,
}: {
  title: string;
  items: { label: string; count: number }[];
  total: number;
  accent: string;
}) {
  return (
    <div className="bg-white border border-[var(--color-border)] rounded-2xl p-3 shadow-sm">
      <h3 className="text-xs font-semibold text-[var(--color-text-primary)] mb-2">{title}</h3>
      {items.length === 0 ? (
        <p className="text-xs text-[var(--color-text-muted)] italic">no rows</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((it) => {
            const pct = total > 0 ? Math.round((it.count / total) * 100) : 0;
            return (
              <li key={it.label}>
                <div className="flex items-center justify-between text-[11px] font-mono mb-0.5">
                  <span className="truncate">{it.label}</span>
                  <span className="text-[var(--color-text-muted)]">{numberFmt.format(it.count)} ({pct}%)</span>
                </div>
                <div className="h-1.5 bg-[var(--color-bg-secondary)] rounded">
                  <div
                    className="h-full rounded"
                    style={{ width: `${Math.max(2, pct)}%`, background: accent }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
