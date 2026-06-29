/**
 * Meta Explorer > Lineage > Columns.
 *
 * Backed by `system.access.column_lineage`. The column table excludes events
 * that have no source (e.g., INSERT VALUES) — per Databricks docs — so the
 * tile counts here are NOT a strict subset of table_lineage.
 *
 * Surfaces column-specific signal:
 *   - Most-fanned-out columns  → flow OUT to many distinct (table, col) pairs.
 *   - Most-depended-on columns → many distinct upstream columns feed them.
 *   - Tables ranked by total column edges (data-product hot spots).
 *   - Top producers (entity_type:entity_id) at the column grain.
 *   - Depth-1 column graph centred on (table, column).
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BookOpen, GitBranch, Clock, FileText, ArrowRight, Layers, Database, Activity,
} from 'lucide-react';
import { metaExplorer, type ColumnLineageNeighbour } from '../../api/client';
import KpiCard from '../../components/KpiCard';
import InfoTooltip from '../../components/InfoTooltip';
import {
  numberFmt, columnNeighbourToItem,
  GraphCard, LineageSearchBox, TopList, ColumnPicker,
} from './_shared';

export default function ColumnLineagePage() {
  const [center, setCenter] = useState<string | null>(null);
  const [column, setColumn] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [activeSearch, setActiveSearch] = useState('');

  const statsQ = useQuery({ queryKey: ['lineage-stats'], queryFn: metaExplorer.lineageStats });
  const colTopsQ = useQuery({
    queryKey: ['lineage-column-tops'],
    queryFn: () => metaExplorer.lineageColumnTops(15),
  });
  const searchQ = useQuery({
    queryKey: ['lineage-search', activeSearch],
    queryFn: () => metaExplorer.lineageSearch(activeSearch, 25),
    enabled: activeSearch.length >= 2,
  });

  useEffect(() => {
    if (center == null && colTopsQ.data?.tables_by_col_edges?.length) {
      setCenter(colTopsQ.data.tables_by_col_edges[0].label);
    }
  }, [colTopsQ.data, center]);

  const graphQ = useQuery({
    queryKey: ['lineage-column-graph', center, column],
    queryFn:  () => metaExplorer.columnGraph(center!, column!, 25),
    enabled:  !!center && !!column,
  });

  const stats = statsQ.data;
  const tops = colTopsQ.data;
  const hasData = (stats?.column_edges ?? 0) > 0;

  return (
    <div className="space-y-6 max-w-[1500px]">
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
          <BookOpen size={20} className="text-cyan-600" />
          <GitBranch size={20} className="text-fuchsia-600" />
          Column Lineage
          <InfoTooltip text="Dashboards over system.access.column_lineage. Each row is a directed edge from a source column to a target column. Events that have no source (e.g., INSERT VALUES) are NOT captured — they appear in Table Lineage as write_only events but not here." />
        </h1>
        <p className="text-sm text-[var(--color-text-muted)] mt-1">
          Which columns flow into which — and which jobs / notebooks / pipelines
          contributed each edge.
          {stats?.column_last_event && (
            <span className="ml-2 inline-flex items-center gap-1">
              <Clock size={11} /> Last event: <strong>{stats.column_last_event}</strong>
            </span>
          )}
        </p>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <KpiCard title="Column edges" value={numberFmt.format(stats?.column_edges ?? 0)}
          icon={<GitBranch size={18} />} accentColor="#06b6d4"
          tooltip="Rows in column_lineage within the active view-mode partition." />
        <KpiCard title="Distinct columns" value={numberFmt.format(stats?.distinct_columns ?? 0)}
          icon={<FileText size={18} />} accentColor="#10b981"
          tooltip="Unique (table, column) pairs across the lineage graph (either side of any edge)." />
        <KpiCard title="Distinct tables" value={numberFmt.format(stats?.column_distinct_tables ?? 0)}
          icon={<Layers size={18} />} accentColor="#3b82f6"
          tooltip="Distinct tables that participate in column edges. Smaller than the table-lineage count because column_lineage skips write_only events." />
        <KpiCard title="Distinct producers" value={numberFmt.format(stats?.column_distinct_entities ?? 0)}
          icon={<Database size={18} />} accentColor="#f59e0b"
          tooltip="Distinct entity IDs (jobs / notebooks / pipelines / dashboards / queries) producing column edges." />
        <KpiCard title="Direct edges (tables)" value={numberFmt.format(stats?.direct_edges ?? 0)}
          icon={<Activity size={18} />} accentColor="#a855f7"
          tooltip="direct_access=true edges in the underlying table_lineage. Indirect-only edges in column_lineage usually mean the dependency was surfaced transitively." />
      </div>

      {!hasData && !statsQ.isLoading && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3">
          <p className="text-sm font-medium text-yellow-800">No column-lineage data yet.</p>
          <p className="text-xs text-yellow-700 mt-1">
            Run an extract that includes the <code>lineage</code> group (column_lineage is part of it).
            Then run <strong>Transform &gt; Lineage rollups</strong> to populate dashboard caches.
          </p>
        </div>
      )}

      {/* Column-specific tops */}
      {tops && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
          <TopList
            title="Most-fanned-out columns"
            subtitle="Source columns whose value reaches the most distinct downstream columns"
            items={tops.most_fanned_out}
            onPick={(label) => {
              const [fn, col] = label.split('::');
              if (fn && col) { setCenter(fn); setColumn(col); }
            }}
          />
          <TopList
            title="Most-depended-on columns"
            subtitle="Target columns with the most distinct upstream columns feeding them"
            items={tops.most_depended_on}
            onPick={(label) => {
              const [fn, col] = label.split('::');
              if (fn && col) { setCenter(fn); setColumn(col); }
            }}
          />
          <TopList
            title="Tables by column edges"
            subtitle="Tables ranked by how many column-level edges they originate"
            items={tops.tables_by_col_edges}
            onPick={(label) => { setCenter(label); setColumn(null); }}
          />
          <TopList
            title="Top producers (column-grain)"
            subtitle="Entities (entity_type:entity_id) producing the most column edges"
            items={tops.top_entities}
            onPick={() => undefined}
          />
        </div>
      )}

      {/* Search → centre table → column picker */}
      <div className="space-y-2">
        <LineageSearchBox
          search={search} setSearch={setSearch}
          activeSearch={activeSearch} setActiveSearch={setActiveSearch}
          results={searchQ.data} loading={searchQ.isLoading}
          onPick={(fn) => { setCenter(fn); setColumn(null); setActiveSearch(''); setSearch(''); }}
          placeholder="Find a table to drill into its columns (e.g. orders, customer)…"
        />
        {center && (
          <div className="bg-white border border-[var(--color-border)] rounded-2xl p-3 shadow-sm">
            <ColumnPicker
              tableFullName={center}
              value={column}
              onChange={setColumn}
            />
          </div>
        )}
      </div>

      {/* Graph */}
      {center && column && (
        <GraphCard
          title="Column lineage"
          subtitle={
            <>
              Centre: <code className="font-mono">{center}::{column}</code>{' '}
              · upstream cols: {numberFmt.format(graphQ.data?.upstream?.length ?? 0)}{' '}
              · downstream cols: {numberFmt.format(graphQ.data?.downstream?.length ?? 0)}
            </>
          }
          loading={graphQ.isLoading}
          leftLabel={`Upstream columns (${numberFmt.format(graphQ.data?.upstream?.length ?? 0)})`}
          rightLabel={`Downstream columns (${numberFmt.format(graphQ.data?.downstream?.length ?? 0)})`}
          centerLabel={`${center}::${column}`}
          leftItems={(graphQ.data?.upstream ?? []).map((n: ColumnLineageNeighbour) => columnNeighbourToItem(n))}
          rightItems={(graphQ.data?.downstream ?? []).map((n: ColumnLineageNeighbour) => columnNeighbourToItem(n))}
          onPickItem={(it) => {
            const [fn, col] = it.id.split('::');
            if (fn && col) { setCenter(fn); setColumn(col); }
          }}
        />
      )}

      {!column && center && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl px-4 py-3 text-xs text-blue-800">
          Pick a column from the dropdown above to render the lineage graph.
        </div>
      )}
    </div>
  );
}

// Silence unused-icon warnings — reserved for future widgets.
void ArrowRight;
