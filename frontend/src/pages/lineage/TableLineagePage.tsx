/**
 * Meta Explorer > Lineage > Tables.
 *
 * Backed by `system.access.table_lineage` (see Databricks docs at
 * /aws/en/admin/system-tables/lineage). Surfaces the dimensions that are
 * specific to the table grain: source/target type breakdown, event class
 * (read_only / write_only / read_write), direct vs indirect, entity-type
 * attribution, plus the depth-1 graph view.
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BookOpen, GitBranch, Clock, AlertTriangle, ArrowRight, Layers,
  Table2, Database, FileText, Activity,
} from 'lucide-react';
import { metaExplorer, type LineageNeighbour } from '../../api/client';
import KpiCard from '../../components/KpiCard';
import InfoTooltip from '../../components/InfoTooltip';
import {
  numberFmt, neighbourToItem,
  GraphCard, LineageSearchBox, TopList, BreakdownBar,
} from './_shared';

export default function TableLineagePage() {
  const [center, setCenter] = useState<string | null>(null);
  const [directOnly, setDirectOnly] = useState(false);
  const [search, setSearch] = useState('');
  const [activeSearch, setActiveSearch] = useState('');

  const statsQ = useQuery({ queryKey: ['lineage-stats'], queryFn: metaExplorer.lineageStats });
  const topsQ  = useQuery({ queryKey: ['lineage-tops'],  queryFn: () => metaExplorer.lineageTops(15) });
  const searchQ = useQuery({
    queryKey: ['lineage-search', activeSearch],
    queryFn: () => metaExplorer.lineageSearch(activeSearch, 25),
    enabled: activeSearch.length >= 2,
  });

  useEffect(() => {
    if (center == null && topsQ.data?.top_targets?.length) {
      setCenter(topsQ.data.top_targets[0].label);
    }
  }, [topsQ.data, center]);

  const graphQ = useQuery({
    queryKey: ['lineage-table-graph', center, directOnly],
    queryFn:  () => metaExplorer.tableGraph(center!, 25, directOnly),
    enabled:  !!center,
  });

  const stats = statsQ.data;
  const tops = topsQ.data;
  const hasData = (stats?.table_edges ?? 0) > 0;

  // Event-class totals from /lineage/stats (computed server-side from
  // source/target nullability — see Databricks event classification).
  const eventTotal =
    (stats?.read_only_events ?? 0) +
    (stats?.write_only_events ?? 0) +
    (stats?.read_write_events ?? 0);

  return (
    <div className="space-y-6 max-w-[1500px]">
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
          <BookOpen size={20} className="text-cyan-600" />
          <GitBranch size={20} className="text-fuchsia-600" />
          Table Lineage
          <InfoTooltip text="Dashboards over system.access.table_lineage. Each row is a directed edge from a source object to a target object emitted by a single statement. Source or target may be NULL — see the event-class breakdown below." />
        </h1>
        <p className="text-sm text-[var(--color-text-muted)] mt-1">
          What writes to / reads from each table — annotated with the Databricks
          entity (job / notebook / pipeline / dashboard / DBSQL query) that
          produced the edge.
          {stats?.last_event && (
            <span className="ml-2 inline-flex items-center gap-1">
              <Clock size={11} /> Last event: <strong>{stats.last_event}</strong>
            </span>
          )}
        </p>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <KpiCard title="Table edges" value={numberFmt.format(stats?.table_edges ?? 0)}
          icon={<GitBranch size={18} />} accentColor="#a855f7"
          tooltip="Rows in table_lineage within the active view-mode partition." />
        <KpiCard title="Distinct tables" value={numberFmt.format(stats?.distinct_tables ?? 0)}
          icon={<Table2 size={18} />} accentColor="#3b82f6"
          tooltip="Unique source-or-target table FQNs across the lineage graph." />
        <KpiCard title="Direct edges" value={numberFmt.format(stats?.direct_edges ?? 0)}
          icon={<Activity size={18} />} accentColor="#10b981"
          tooltip="direct_access=true. The source/target was referenced directly by the statement." />
        <KpiCard title="Indirect edges" value={numberFmt.format(stats?.indirect_edges ?? 0)}
          icon={<Layers size={18} />} accentColor="#f97316"
          tooltip="direct_access=false. Transitive dependency surfaced by lineage analysis." />
        <KpiCard title="Distinct producers" value={numberFmt.format(stats?.distinct_entities ?? 0)}
          icon={<Database size={18} />} accentColor="#f59e0b"
          tooltip="Distinct entity IDs (jobs / notebooks / pipelines / dashboards / queries) generating lineage." />
      </div>

      {!hasData && !statsQ.isLoading && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3">
          <p className="text-sm font-medium text-yellow-800">No lineage data yet.</p>
          <p className="text-xs text-yellow-700 mt-1">
            Trigger an extract that includes the <code>lineage</code> group, or run
            <code> python scripts/simulate_demo_data.py</code> and switch view-mode to demo.
            Run <strong>Transform &gt; Lineage rollups</strong> after the extract to populate the cache.
          </p>
        </div>
      )}

      {/* Event-class + type breakdowns */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <BreakdownBar
          title="Event class"
          total={eventTotal}
          accent="#a855f7"
          items={[
            { label: 'read_write', count: stats?.read_write_events ?? 0 },
            { label: 'read_only',  count: stats?.read_only_events ?? 0 },
            { label: 'write_only', count: stats?.write_only_events ?? 0 },
          ]}
        />
        <BreakdownBar
          title="By entity_type (producer)"
          total={stats?.table_edges ?? 0}
          accent="#3b82f6"
          items={(stats?.by_entity_type ?? []).map((b) => ({ label: b.label, count: b.count }))}
        />
        <BreakdownBar
          title="By source_type"
          total={stats?.table_edges ?? 0}
          accent="#0891b2"
          items={(stats?.by_source_type ?? []).map((b) => ({ label: b.label, count: b.count }))}
        />
      </div>

      {/* Tops */}
      {tops && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
          <TopList title="Top sources (most read)" subtitle="Tables that feed many pipelines"
            items={tops.top_sources} onPick={(label) => setCenter(label)} />
          <TopList title="Top targets (most written)" subtitle="Tables that absorb many writes"
            items={tops.top_targets} onPick={(label) => setCenter(label)} />
          <TopList title="Top producers" subtitle="Jobs / notebooks / pipelines emitting edges"
            items={tops.top_entities} onPick={() => undefined} />
          <TopList title="Top column edges" subtitle="(table::column) most depended-on — see Column Lineage"
            items={tops.top_columns} onPick={() => undefined} />
        </div>
      )}

      {/* Orphans + terminals */}
      {tops && (tops.orphan_tables.length > 0 || tops.terminal_tables.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <OrphanList icon={<AlertTriangle size={14} className="text-amber-600" />}
            title="Orphan tables"
            subtitle="In databricks_meta but absent from lineage — never read OR written by tracked entities."
            items={tops.orphan_tables} />
          <OrphanList icon={<ArrowRight size={14} className="text-emerald-600" />}
            title="Terminal tables"
            subtitle="Appear as a target but never as a source — leaf nodes / dead-ends."
            items={tops.terminal_tables} />
        </div>
      )}

      {/* Search + direct-only toggle */}
      <div className="space-y-2">
        <LineageSearchBox
          search={search} setSearch={setSearch}
          activeSearch={activeSearch} setActiveSearch={setActiveSearch}
          results={searchQ.data} loading={searchQ.isLoading}
          onPick={(fn) => { setCenter(fn); setActiveSearch(''); setSearch(''); }}
          placeholder="Find a table by substring (e.g. orders, gold, customer)…"
        />
        <label className="inline-flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
          <input
            type="checkbox"
            checked={directOnly}
            onChange={(e) => setDirectOnly(e.target.checked)}
            className="rounded"
          />
          Show only <code>direct_access = true</code> edges
          <InfoTooltip text="Direct = source/target was referenced directly by the statement. Indirect = surfaced by lineage analysis as a transitive dependency." />
        </label>
      </div>

      {/* Graph */}
      {center && (
        <GraphCard
          title="Table lineage"
          subtitle={
            <>
              Centre: <code className="font-mono">{center}</code>{' '}
              · upstream: {numberFmt.format(graphQ.data?.upstream?.length ?? 0)}{' '}
              · downstream: {numberFmt.format(graphQ.data?.downstream?.length ?? 0)}
              {directOnly && <span className="ml-2 text-fuchsia-700">[direct only]</span>}
            </>
          }
          loading={graphQ.isLoading}
          leftLabel={`Upstream (${numberFmt.format(graphQ.data?.upstream?.length ?? 0)})`}
          rightLabel={`Downstream (${numberFmt.format(graphQ.data?.downstream?.length ?? 0)})`}
          centerLabel={center}
          leftItems={(graphQ.data?.upstream ?? []).map((n: LineageNeighbour) => neighbourToItem(n))}
          rightItems={(graphQ.data?.downstream ?? []).map((n: LineageNeighbour) => neighbourToItem(n))}
          onPickItem={(it) => setCenter(it.id)}
        />
      )}
    </div>
  );
}

function OrphanList({
  icon, title, subtitle, items,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  items: string[];
}) {
  return (
    <div className="bg-white border border-[var(--color-border)] rounded-2xl p-3 shadow-sm">
      <h3 className="text-xs font-semibold text-[var(--color-text-primary)] flex items-center gap-1">
        {icon} {title}
      </h3>
      <p className="text-[10px] text-[var(--color-text-muted)] mt-0.5 mb-2">{subtitle}</p>
      {items.length === 0 ? (
        <p className="text-xs text-[var(--color-text-muted)] italic">none</p>
      ) : (
        <ul className="max-h-56 overflow-auto space-y-0.5">
          {items.map((fn) => (
            <li key={fn} className="text-[11px] font-mono text-[var(--color-text-secondary)] truncate" title={fn}>
              {fn}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Silence unused-icon warnings for icons reserved for future widgets.
void FileText;
