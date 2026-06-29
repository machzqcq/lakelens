/**
 * Meta Explorer > Node Pool — dashboards over the system.compute.* tables:
 *   - node_timeline       (per-minute utilization, the heaviest)
 *   - warehouse_events    (SQL warehouse lifecycle)
 *   - node_types          (reference: cpu / memory / gpu specs per SKU)
 *   - instance_events     (VM lifecycle — node-add / terminating / spot-loss)
 *   - instance_pools      (reference: pool capacity + idle behaviour)
 *
 * Layout:
 *   - KPI tiles (one per table) + last-seen timestamps
 *   - Three breakdown bars (warehouse event types, instance event types,
 *     node-type categories)
 *   - Cluster utilization table (top N clusters by sample count)
 *   - Recent warehouse_events table
 *   - Recent instance_events table
 *   - Full node_types catalog
 *   - Full instance_pools catalog
 *
 * View-mode scoped like every Meta Explorer endpoint — the backend filters
 * on `data_origin = user.viewing_data_mode` so toggling REAL ↔ DEMO in the
 * top-right partitions the data cleanly.
 */
import { useQuery } from '@tanstack/react-query';
import {
  Cpu, Activity, Database, Layers, Server, Clock, AlertTriangle,
} from 'lucide-react';
import { metaExplorer } from '../api/client';
import KpiCard from '../components/KpiCard';
import InfoTooltip from '../components/InfoTooltip';
import { BreakdownBar, numberFmt } from './lineage/_shared';


function fmtTs(s: string | null | undefined): string {
  if (!s) return '—';
  // Backend returns ISO string. Render the date-time portion in the user's
  // locale; full precision is rarely useful on these dashboards.
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString();
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${v.toFixed(1)}%`;
}

function fmtNum(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return numberFmt.format(v);
}


export default function MetaNodePool() {
  const statsQ      = useQuery({ queryKey: ['np-stats'],     queryFn: () => metaExplorer.nodePoolStats() });
  const utilQ       = useQuery({ queryKey: ['np-util'],      queryFn: () => metaExplorer.nodePoolUtilization(25) });
  const whEventsQ   = useQuery({ queryKey: ['np-wh-ev'],     queryFn: () => metaExplorer.nodePoolWarehouseEvents(50) });
  const instEventsQ = useQuery({ queryKey: ['np-inst-ev'],   queryFn: () => metaExplorer.nodePoolInstanceEvents(50) });
  const nodeTypesQ  = useQuery({ queryKey: ['np-types'],     queryFn: () => metaExplorer.nodePoolNodeTypes() });
  const poolsQ      = useQuery({ queryKey: ['np-pools'],     queryFn: () => metaExplorer.nodePoolInstancePools() });

  const stats = statsQ.data;
  const hasAnyData =
    (stats?.node_timeline_rows ?? 0)
    + (stats?.warehouse_event_rows ?? 0)
    + (stats?.instance_event_rows ?? 0)
    + (stats?.node_type_rows ?? 0)
    + (stats?.instance_pool_rows ?? 0) > 0;

  return (
    <div className="space-y-6 max-w-[1500px]">
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
          <Cpu size={20} className="text-teal-600" />
          Node Pool
          <InfoTooltip text="Dashboards over the system.compute.* tables: per-minute node_timeline utilization, warehouse and instance lifecycle events, and the reference catalogs for node types and instance pools. View-mode scoped." />
        </h1>
        <p className="text-sm text-[var(--color-text-muted)] mt-1">
          Cluster utilization, warehouse and instance lifecycle. Driven by
          <code> system.compute.node_timeline</code>, <code> warehouse_events</code>,
          <code> node_types</code>, <code> node_events</code> (surfaced as
          <code> instance_events</code>), and <code> instance_pools</code>.
          {stats?.last_node_timeline && (
            <span className="ml-2 inline-flex items-center gap-1">
              <Clock size={11} /> Last node_timeline sample: <strong>{fmtTs(stats.last_node_timeline)}</strong>
            </span>
          )}
        </p>
      </div>

      {/* KPI tiles — one per table. */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <KpiCard title="node_timeline rows" value={fmtNum(stats?.node_timeline_rows ?? 0)}
          icon={<Activity size={18} />} accentColor="#0d9488"
          tooltip="Per-minute utilization samples across all clusters in the resident window." />
        <KpiCard title="warehouse_events" value={fmtNum(stats?.warehouse_event_rows ?? 0)}
          icon={<Server size={18} />} accentColor="#3b82f6"
          tooltip="SQL warehouse lifecycle events (STARTING/RUNNING/STOPPED/SCALED_*)." />
        <KpiCard title="instance_events" value={fmtNum(stats?.instance_event_rows ?? 0)}
          icon={<AlertTriangle size={18} />} accentColor="#f97316"
          tooltip="VM lifecycle events (sourced from system.compute.node_events)." />
        <KpiCard title="node_types" value={fmtNum(stats?.node_type_rows ?? 0)}
          icon={<Database size={18} />} accentColor="#a855f7"
          tooltip="Reference catalog of cloud node SKUs (cpu / memory / gpu)." />
        <KpiCard title="instance_pools" value={fmtNum(stats?.instance_pool_rows ?? 0)}
          icon={<Layers size={18} />} accentColor="#0891b2"
          tooltip="Instance pool catalog (min idle / max capacity / autotermination)." />
      </div>

      {/* Inline counters strip — distinct entities surfaced from the data. */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs text-[var(--color-text-muted)]">
        <div className="bg-white border border-[var(--color-border)] rounded-xl px-3 py-2">
          Distinct clusters in timeline: <strong className="text-[var(--color-text-primary)]">{fmtNum(stats?.distinct_clusters_in_timeline ?? 0)}</strong>
        </div>
        <div className="bg-white border border-[var(--color-border)] rounded-xl px-3 py-2">
          Distinct instances in timeline: <strong className="text-[var(--color-text-primary)]">{fmtNum(stats?.distinct_instances_in_timeline ?? 0)}</strong>
        </div>
        <div className="bg-white border border-[var(--color-border)] rounded-xl px-3 py-2">
          Distinct warehouses in events: <strong className="text-[var(--color-text-primary)]">{fmtNum(stats?.distinct_warehouses_in_events ?? 0)}</strong>
        </div>
        <div className="bg-white border border-[var(--color-border)] rounded-xl px-3 py-2">
          Distinct pools referenced: <strong className="text-[var(--color-text-primary)]">{fmtNum(stats?.distinct_pools_referenced ?? 0)}</strong>
        </div>
      </div>

      {!hasAnyData && !statsQ.isLoading && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3">
          <p className="text-sm font-medium text-yellow-800">No node-pool data yet.</p>
          <p className="text-xs text-yellow-700 mt-1">
            Trigger an extract that includes the <code>node_pool</code> group
            (Admin → Data Management → Extract from Databricks), or run
            <code> python scripts/simulate_demo_data.py </code> and switch to demo view-mode.
          </p>
        </div>
      )}

      {/* Breakdown bars — event-type / category distributions. */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <BreakdownBar
          title="By warehouse event_type"
          total={stats?.warehouse_event_rows ?? 0}
          accent="#3b82f6"
          items={(stats?.by_warehouse_event_type ?? []).map((b) => ({ label: b.label, count: b.count }))}
        />
        <BreakdownBar
          title="By instance event_type"
          total={stats?.instance_event_rows ?? 0}
          accent="#f97316"
          items={(stats?.by_instance_event_type ?? []).map((b) => ({ label: b.label, count: b.count }))}
        />
        <BreakdownBar
          title="By node_type category"
          total={stats?.node_type_rows ?? 0}
          accent="#a855f7"
          items={(stats?.by_node_type_category ?? []).map((b) => ({ label: b.label, count: b.count }))}
        />
      </div>

      {/* Cluster utilization. */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4 shadow-sm">
        <h2 className="text-base font-semibold text-[var(--color-text-primary)] flex items-center gap-2 mb-3">
          <Activity size={16} className="text-teal-600" />
          Cluster utilization (top by sample count)
          <InfoTooltip text="Aggregate CPU and memory usage over the resident node_timeline window. Sample count is the number of 1-minute snapshots ingested for the cluster." />
        </h2>
        {utilQ.isLoading ? (
          <div className="text-xs text-[var(--color-text-muted)]">Loading…</div>
        ) : (utilQ.data ?? []).length === 0 ? (
          <div className="text-xs text-[var(--color-text-muted)]">No utilization samples in the active partition.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="text-left text-[var(--color-text-muted)] border-b border-[var(--color-border)]">
                <tr>
                  <th className="py-2 pr-3">cluster_id</th>
                  <th className="py-2 pr-3 text-right">samples</th>
                  <th className="py-2 pr-3 text-right">avg cpu_user</th>
                  <th className="py-2 pr-3 text-right">avg cpu_sys</th>
                  <th className="py-2 pr-3 text-right">avg mem_used</th>
                  <th className="py-2 pr-3 text-right">max cpu_user</th>
                  <th className="py-2 pr-3 text-right">max mem_used</th>
                  <th className="py-2 pr-3">last sample</th>
                </tr>
              </thead>
              <tbody>
                {(utilQ.data ?? []).map((r) => (
                  <tr key={r.cluster_id ?? '(none)'} className="border-b border-[var(--color-border)] last:border-0">
                    <td className="py-1.5 pr-3 font-mono">{r.cluster_id ?? '(none)'}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtNum(r.sample_count)}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtPct(r.avg_cpu_user_percent)}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtPct(r.avg_cpu_system_percent)}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtPct(r.avg_mem_used_percent)}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtPct(r.max_cpu_user_percent)}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtPct(r.max_mem_used_percent)}</td>
                    <td className="py-1.5 pr-3 text-[var(--color-text-muted)]">{fmtTs(r.last_sample)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recent warehouse events. */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4 shadow-sm">
        <h2 className="text-base font-semibold text-[var(--color-text-primary)] flex items-center gap-2 mb-3">
          <Server size={16} className="text-blue-600" />
          Recent warehouse events
        </h2>
        {whEventsQ.isLoading ? (
          <div className="text-xs text-[var(--color-text-muted)]">Loading…</div>
        ) : (whEventsQ.data ?? []).length === 0 ? (
          <div className="text-xs text-[var(--color-text-muted)]">No warehouse events in the active partition.</div>
        ) : (
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="min-w-full text-xs">
              <thead className="text-left text-[var(--color-text-muted)] border-b border-[var(--color-border)] sticky top-0 bg-white">
                <tr>
                  <th className="py-2 pr-3">event_time</th>
                  <th className="py-2 pr-3">warehouse_id</th>
                  <th className="py-2 pr-3">event_type</th>
                  <th className="py-2 pr-3 text-right">cluster_count</th>
                  <th className="py-2 pr-3">workspace_id</th>
                </tr>
              </thead>
              <tbody>
                {(whEventsQ.data ?? []).map((r, i) => (
                  <tr key={`${r.warehouse_id}-${r.event_time}-${i}`} className="border-b border-[var(--color-border)] last:border-0">
                    <td className="py-1.5 pr-3 text-[var(--color-text-muted)]">{fmtTs(r.event_time)}</td>
                    <td className="py-1.5 pr-3 font-mono">{r.warehouse_id ?? '—'}</td>
                    <td className="py-1.5 pr-3"><code>{r.event_type ?? '—'}</code></td>
                    <td className="py-1.5 pr-3 text-right">{fmtNum(r.cluster_count)}</td>
                    <td className="py-1.5 pr-3 font-mono text-[var(--color-text-muted)]">{r.workspace_id ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recent instance events. */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4 shadow-sm">
        <h2 className="text-base font-semibold text-[var(--color-text-primary)] flex items-center gap-2 mb-3">
          <AlertTriangle size={16} className="text-orange-600" />
          Recent instance events
          <InfoTooltip text="VM-level lifecycle events sourced from system.compute.node_events (surfaced here as instance_events to match the Databricks UI label)." />
        </h2>
        {instEventsQ.isLoading ? (
          <div className="text-xs text-[var(--color-text-muted)]">Loading…</div>
        ) : (instEventsQ.data ?? []).length === 0 ? (
          <div className="text-xs text-[var(--color-text-muted)]">No instance events in the active partition.</div>
        ) : (
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="min-w-full text-xs">
              <thead className="text-left text-[var(--color-text-muted)] border-b border-[var(--color-border)] sticky top-0 bg-white">
                <tr>
                  <th className="py-2 pr-3">event_time</th>
                  <th className="py-2 pr-3">event_type</th>
                  <th className="py-2 pr-3">cluster_id</th>
                  <th className="py-2 pr-3">instance_id</th>
                  <th className="py-2 pr-3">instance_pool_id</th>
                  <th className="py-2 pr-3">node_type</th>
                </tr>
              </thead>
              <tbody>
                {(instEventsQ.data ?? []).map((r, i) => (
                  <tr key={`${r.instance_id}-${r.event_time}-${i}`} className="border-b border-[var(--color-border)] last:border-0">
                    <td className="py-1.5 pr-3 text-[var(--color-text-muted)]">{fmtTs(r.event_time)}</td>
                    <td className="py-1.5 pr-3"><code>{r.event_type ?? '—'}</code></td>
                    <td className="py-1.5 pr-3 font-mono">{r.cluster_id ?? '—'}</td>
                    <td className="py-1.5 pr-3 font-mono text-[var(--color-text-muted)]">{r.instance_id ?? '—'}</td>
                    <td className="py-1.5 pr-3 font-mono text-[var(--color-text-muted)]">{r.instance_pool_id ?? '—'}</td>
                    <td className="py-1.5 pr-3">{r.node_type ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Node types catalog. */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4 shadow-sm">
        <h2 className="text-base font-semibold text-[var(--color-text-primary)] flex items-center gap-2 mb-3">
          <Database size={16} className="text-purple-600" />
          Node types
          <InfoTooltip text="Full reference catalog of cloud node SKUs available to this account, with cpu / memory / gpu specs." />
        </h2>
        {nodeTypesQ.isLoading ? (
          <div className="text-xs text-[var(--color-text-muted)]">Loading…</div>
        ) : (nodeTypesQ.data ?? []).length === 0 ? (
          <div className="text-xs text-[var(--color-text-muted)]">No node_types rows in the active partition.</div>
        ) : (
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="min-w-full text-xs">
              <thead className="text-left text-[var(--color-text-muted)] border-b border-[var(--color-border)] sticky top-0 bg-white">
                <tr>
                  <th className="py-2 pr-3">node_type</th>
                  <th className="py-2 pr-3">category</th>
                  <th className="py-2 pr-3 text-right">cores</th>
                  <th className="py-2 pr-3 text-right">memory (MB)</th>
                  <th className="py-2 pr-3 text-right">gpus</th>
                </tr>
              </thead>
              <tbody>
                {(nodeTypesQ.data ?? []).map((r, i) => (
                  <tr key={`${r.node_type}-${i}`} className="border-b border-[var(--color-border)] last:border-0">
                    <td className="py-1.5 pr-3 font-mono">{r.node_type ?? '—'}</td>
                    <td className="py-1.5 pr-3">{r.category ?? '—'}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtNum(r.core_count)}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtNum(r.memory_mb)}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtNum(r.gpu_count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Instance pools catalog. */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4 shadow-sm">
        <h2 className="text-base font-semibold text-[var(--color-text-primary)] flex items-center gap-2 mb-3">
          <Layers size={16} className="text-cyan-600" />
          Instance pools
          <InfoTooltip text="Pooled-VM definitions used to amortise VM acquisition. min_idle / max_capacity / autotermination drive the pool autoscaler." />
        </h2>
        {poolsQ.isLoading ? (
          <div className="text-xs text-[var(--color-text-muted)]">Loading…</div>
        ) : (poolsQ.data ?? []).length === 0 ? (
          <div className="text-xs text-[var(--color-text-muted)]">No instance_pools rows in the active partition.</div>
        ) : (
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="min-w-full text-xs">
              <thead className="text-left text-[var(--color-text-muted)] border-b border-[var(--color-border)] sticky top-0 bg-white">
                <tr>
                  <th className="py-2 pr-3">name</th>
                  <th className="py-2 pr-3">node_type</th>
                  <th className="py-2 pr-3 text-right">min_idle</th>
                  <th className="py-2 pr-3 text-right">max_capacity</th>
                  <th className="py-2 pr-3 text-right">idle term (min)</th>
                  <th className="py-2 pr-3">elastic disk</th>
                  <th className="py-2 pr-3">workspace</th>
                  <th className="py-2 pr-3">created</th>
                </tr>
              </thead>
              <tbody>
                {(poolsQ.data ?? []).map((r, i) => (
                  <tr key={`${r.instance_pool_id}-${i}`} className="border-b border-[var(--color-border)] last:border-0">
                    <td className="py-1.5 pr-3 font-medium">{r.instance_pool_name ?? r.instance_pool_id ?? '—'}</td>
                    <td className="py-1.5 pr-3 font-mono">{r.node_type ?? '—'}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtNum(r.min_idle_instances)}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtNum(r.max_capacity)}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtNum(r.idle_instance_autotermination_minutes)}</td>
                    <td className="py-1.5 pr-3">{r.enable_elastic_disk === null ? '—' : r.enable_elastic_disk ? 'yes' : 'no'}</td>
                    <td className="py-1.5 pr-3 font-mono text-[var(--color-text-muted)]">{r.workspace_id ?? '—'}</td>
                    <td className="py-1.5 pr-3 text-[var(--color-text-muted)]">{fmtTs(r.create_time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
