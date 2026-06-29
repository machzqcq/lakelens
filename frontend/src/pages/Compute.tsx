import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { Server, Database, Search, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, X, Cpu, MemoryStick, HardDrive, Zap, ArrowUpDown, SlidersHorizontal } from 'lucide-react';

import ChartCard from '../components/ChartCard';
import InfoTooltip from '../components/InfoTooltip';
import FieldDefinitions from '../components/FieldDefinitions';
import DateRangeFilter from '../components/DateRangeFilter';
import { useWorkspaceNames } from '../hooks/useWorkspaceNames';
import {
  fetchClusters,
  fetchClusterDetail,
  fetchWarehouses,
  fetchWarehouseDetail,
  fetchClusterCost,
  fetchWarehouseCost,
} from '../api/client';
import type { ClusterDetail, WarehouseDetail, ComputeCostResponse, ClusterFullDetail, ClusterSortBy, SortOrder, WarehouseFullDetail } from '../types/api';

type Tab = 'clusters' | 'warehouses';

type ClusterFilters = {
  clusterSource: string;
  dataSecurityMode: string;
  nodeFamily: string;
  hasGpu: '' | 'true' | 'false';
  minVcpus: string;
  minMemoryGb: string;
};

const EMPTY_FILTERS: ClusterFilters = {
  clusterSource: '',
  dataSecurityMode: '',
  nodeFamily: '',
  hasGpu: '',
  minVcpus: '',
  minMemoryGb: '',
};

const SORT_OPTIONS: { value: ClusterSortBy; order: SortOrder; label: string }[] = [
  { value: 'name',             order: 'asc',  label: 'Name (A-Z)' },
  { value: 'name',             order: 'desc', label: 'Name (Z-A)' },
  { value: 'created',          order: 'desc', label: 'Newest first' },
  { value: 'created',          order: 'asc',  label: 'Oldest first' },
  { value: 'total_vcpus',      order: 'desc', label: 'Total vCPUs (high-low)' },
  { value: 'total_vcpus',      order: 'asc',  label: 'Total vCPUs (low-high)' },
  { value: 'total_memory_gb',  order: 'desc', label: 'Total memory (high-low)' },
  { value: 'total_memory_gb',  order: 'asc',  label: 'Total memory (low-high)' },
  { value: 'driver_vcpus',     order: 'desc', label: 'Driver vCPUs (high-low)' },
  { value: 'driver_memory_gb', order: 'desc', label: 'Driver memory (high-low)' },
  { value: 'workers',          order: 'desc', label: 'Workers (high-low)' },
];

const CLUSTER_SOURCES = ['JOB', 'UI', 'PIPELINE', 'PIPELINE_MAINTENANCE'];
const SECURITY_MODES = ['SINGLE_USER', 'USER_ISOLATION', 'NONE', 'LEGACY_PASSTHROUGH'];
const NODE_FAMILIES = ['general-purpose', 'memory-optimized', 'compute-optimized', 'storage-optimized', 'gpu'];

function countActiveFilters(f: ClusterFilters): number {
  return Object.values(f).filter((v) => v !== '').length;
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

const fmtCurrency = (v: number) =>
  `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const CLUSTER_SOURCE_COLORS: Record<string, { bg: string; text: string }> = {
  JOB: { bg: '#dbeafe', text: '#1d4ed8' },
  UI: { bg: '#dcfce7', text: '#15803d' },
  PIPELINE: { bg: '#f3e8ff', text: '#7e22ce' },
  PIPELINE_MAINTENANCE: { bg: '#fef3c7', text: '#92400e' },
};

const WAREHOUSE_TYPE_COLORS: Record<string, { bg: string; text: string }> = {
  CLASSIC: { bg: '#f3f4f6', text: '#374151' },
  PRO: { bg: '#dbeafe', text: '#1d4ed8' },
  SERVERLESS: { bg: '#f3e8ff', text: '#7e22ce' },
};

const CLUSTER_FIELD_DEFS = [
  { name: 'cluster_id', description: 'Unique identifier for the compute cluster' },
  { name: 'cluster_name', description: 'Human-readable name assigned to the cluster' },
  { name: 'owned_by', description: 'Email of the user who owns this cluster' },
  { name: 'driver_node_type', description: 'VM type for the driver node (e.g., Standard_DS3_v2)' },
  { name: 'worker_node_type', description: 'VM type for worker nodes' },
  { name: 'worker_count', description: 'Fixed number of workers (for non-autoscaling clusters)' },
  { name: 'min/max_autoscale_workers', description: 'Autoscaling range for the cluster' },
  { name: 'dbr_version', description: 'Databricks Runtime version (e.g., 14.3.x-scala2.12)' },
  { name: 'cluster_source', description: 'How the cluster was created - JOB (automated), UI (interactive), PIPELINE (DLT)' },
  { name: 'data_security_mode', description: 'Access control mode (SINGLE_USER, USER_ISOLATION)' },
  { name: 'total_vcpus', description: 'Driver + (max_workers x worker) vCPUs, derived from a static node-spec lookup. Empty when node type is unknown.' },
  { name: 'total_memory_gb', description: 'Driver + (max_workers x worker) memory in GiB, derived from the same lookup.' },
  { name: 'driver_family', description: 'Hardware family of the driver node (general-purpose, memory-optimized, compute-optimized, storage-optimized, gpu).' },
];

const WAREHOUSE_FIELD_DEFS = [
  { name: 'warehouse_id', description: 'Unique identifier for the SQL warehouse' },
  { name: 'warehouse_name', description: 'Human-readable name assigned to the warehouse' },
  { name: 'warehouse_type', description: 'Compute tier - CLASSIC (basic), PRO (advanced features), SERVERLESS (fully managed)' },
  { name: 'warehouse_size', description: 'T-shirt sizing from 2X_SMALL to 5X_LARGE, determines compute capacity' },
  { name: 'min/max_clusters', description: 'Scaling range for concurrent query capacity' },
  { name: 'auto_stop_minutes', description: 'Idle timeout before the warehouse shuts down to save costs' },
];

const PAGE_SIZE = 18;

function Badge({ label, colorMap }: { label: string | null; colorMap: Record<string, { bg: string; text: string }> }) {
  const key = label?.toUpperCase() ?? '';
  const colors = colorMap[key] ?? { bg: '#f3f4f6', text: '#6b7280' };
  return (
    <span
      className="px-2 py-0.5 text-[10px] font-semibold uppercase rounded-full"
      style={{ backgroundColor: colors.bg, color: colors.text }}
    >
      {label ?? 'Unknown'}
    </span>
  );
}

function Pagination({ page, totalPages, total, pageSize, onPageChange }: {
  page: number; totalPages: number; total: number; pageSize: number;
  onPageChange: (p: number) => void;
}) {
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  return (
    <div className="flex items-center justify-between pt-4 border-t border-[var(--color-border)]">
      <p className="text-xs text-[var(--color-text-muted)]">
        Showing <span className="font-medium text-[var(--color-text-secondary)]">{from}-{to}</span> of{' '}
        <span className="font-medium text-[var(--color-text-secondary)]">{total.toLocaleString()}</span>
      </p>
      <div className="flex items-center gap-1">
        <button onClick={() => onPageChange(1)} disabled={page <= 1}
          className="p-1.5 rounded-lg hover:bg-[var(--color-bg-secondary)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
          <ChevronsLeft size={16} className="text-[var(--color-text-secondary)]" />
        </button>
        <button onClick={() => onPageChange(page - 1)} disabled={page <= 1}
          className="p-1.5 rounded-lg hover:bg-[var(--color-bg-secondary)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
          <ChevronLeft size={16} className="text-[var(--color-text-secondary)]" />
        </button>
        <span className="px-3 py-1 text-xs text-[var(--color-text-secondary)]">
          Page <span className="font-medium">{page}</span> of <span className="font-medium">{totalPages}</span>
        </span>
        <button onClick={() => onPageChange(page + 1)} disabled={page >= totalPages}
          className="p-1.5 rounded-lg hover:bg-[var(--color-bg-secondary)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
          <ChevronRight size={16} className="text-[var(--color-text-secondary)]" />
        </button>
        <button onClick={() => onPageChange(totalPages)} disabled={page >= totalPages}
          className="p-1.5 rounded-lg hover:bg-[var(--color-bg-secondary)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
          <ChevronsRight size={16} className="text-[var(--color-text-secondary)]" />
        </button>
      </div>
    </div>
  );
}

function ClusterCard({ cluster, onClick, isSelected }: {
  cluster: ClusterDetail; onClick: () => void; isSelected: boolean;
}) {
  const { resolver: wsName } = useWorkspaceNames();
  const workers =
    cluster.min_autoscale_workers != null && cluster.max_autoscale_workers != null
      ? `${cluster.min_autoscale_workers}-${cluster.max_autoscale_workers} (auto)`
      : cluster.worker_count != null ? `${cluster.worker_count}` : 'N/A';

  return (
    <button onClick={onClick}
      className={`w-full text-left bg-white border rounded-2xl shadow-sm hover:shadow-md p-4 transition-all hover:border-[var(--color-primary)] ${
        isSelected ? 'border-[var(--color-primary)] ring-1 ring-[var(--color-primary)]/30' : 'border-[var(--color-border)]'
      }`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <Server size={16} className="text-[var(--color-primary)] shrink-0" />
          <span className="text-sm font-medium text-[var(--color-text-primary)] truncate">{cluster.cluster_name}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {cluster.driver_has_gpu && (
            <span className="px-1.5 py-0.5 text-[9px] font-semibold uppercase rounded-full bg-amber-100 text-amber-800">GPU</span>
          )}
          <Badge label={cluster.cluster_source} colorMap={CLUSTER_SOURCE_COLORS} />
        </div>
      </div>
      <div className="flex items-center gap-3 mb-3 pb-3 border-b border-[var(--color-border)]">
        <div className="flex items-center gap-1 text-xs text-[var(--color-text-secondary)]">
          <Cpu size={12} className="text-[var(--color-text-muted)]" />
          <span className="font-medium">{cluster.total_vcpus ?? '?'}</span>
          <span className="text-[var(--color-text-muted)]">vCPU</span>
        </div>
        <div className="flex items-center gap-1 text-xs text-[var(--color-text-secondary)]">
          <MemoryStick size={12} className="text-[var(--color-text-muted)]" />
          <span className="font-medium">{cluster.total_memory_gb != null ? `${cluster.total_memory_gb.toLocaleString()}` : '?'}</span>
          <span className="text-[var(--color-text-muted)]">GiB</span>
        </div>
        {cluster.driver_family && (
          <span className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] ml-auto">{cluster.driver_family}</span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
        <div>
          <span className="text-[var(--color-text-muted)]">WS: </span>
          <span className="text-[var(--color-text-secondary)] truncate" title={cluster.workspace_id}>
            {wsName(cluster.workspace_id)}
          </span>
        </div>
        <div><span className="text-[var(--color-text-muted)]">Owner: </span><span className="text-[var(--color-text-secondary)] truncate">{cluster.owned_by ?? 'N/A'}</span></div>
        <div><span className="text-[var(--color-text-muted)]">Workers: </span><span className="text-[var(--color-text-secondary)]">{workers}</span></div>
        <div><span className="text-[var(--color-text-muted)]">Node: </span><span className="text-[var(--color-text-secondary)] truncate">{cluster.worker_node_type ?? 'N/A'}</span></div>
        <div><span className="text-[var(--color-text-muted)]">Runtime: </span><span className="text-[var(--color-text-secondary)]">{cluster.dbr_version ?? 'N/A'}</span></div>
        <div><span className="text-[var(--color-text-muted)]">Security: </span><span className="text-[var(--color-text-secondary)]">{cluster.data_security_mode ?? 'N/A'}</span></div>
      </div>
    </button>
  );
}

function WarehouseCard({ warehouse, onClick, isSelected }: {
  warehouse: WarehouseDetail; onClick: () => void; isSelected: boolean;
}) {
  return (
    <button onClick={onClick}
      className={`w-full text-left bg-white border rounded-2xl shadow-sm hover:shadow-md p-4 transition-all hover:border-[var(--color-primary)] ${
        isSelected ? 'border-[var(--color-primary)] ring-1 ring-[var(--color-primary)]/30' : 'border-[var(--color-border)]'
      }`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <Database size={16} className="text-[var(--color-accent)] shrink-0" />
          <span className="text-sm font-medium text-[var(--color-text-primary)] truncate">{warehouse.warehouse_name}</span>
        </div>
        <Badge label={warehouse.warehouse_type} colorMap={WAREHOUSE_TYPE_COLORS} />
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
        <div><span className="text-[var(--color-text-muted)]">ID: </span><span className="text-[var(--color-text-secondary)] font-mono">{warehouse.warehouse_id}</span></div>
        <div><span className="text-[var(--color-text-muted)]">Size: </span><span className="text-[var(--color-text-secondary)]">{warehouse.warehouse_size ?? 'N/A'}</span></div>
        <div><span className="text-[var(--color-text-muted)]">Clusters: </span><span className="text-[var(--color-text-secondary)]">{warehouse.min_clusters ?? '?'}-{warehouse.max_clusters ?? '?'}</span></div>
        <div><span className="text-[var(--color-text-muted)]">Auto Stop: </span><span className="text-[var(--color-text-secondary)]">{warehouse.auto_stop_minutes != null ? `${warehouse.auto_stop_minutes}m` : 'N/A'}</span></div>
        <div className="col-span-2"><span className="text-[var(--color-text-muted)]">Created by: </span><span className="text-[var(--color-text-secondary)]">{warehouse.created_by ?? 'N/A'}</span></div>
      </div>
    </button>
  );
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return 'N/A';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

function NodeSpecBlock({ label, nodeType, spec }: {
  label: string;
  nodeType: string | null;
  spec: ClusterFullDetail['driver_spec'];
}) {
  return (
    <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
      <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-2">{label}</p>
      <p className="text-sm font-medium text-[var(--color-text-primary)] font-mono mb-2">{nodeType ?? 'N/A'}</p>
      {spec ? (
        <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
          <div className="flex items-center gap-1.5 text-[var(--color-text-secondary)]">
            <Cpu size={12} className="text-[var(--color-text-muted)]" /> {spec.vcpus} vCPU
          </div>
          <div className="flex items-center gap-1.5 text-[var(--color-text-secondary)]">
            <MemoryStick size={12} className="text-[var(--color-text-muted)]" /> {spec.memory_gb} GiB
          </div>
          {spec.local_disk_gb != null && (
            <div className="flex items-center gap-1.5 text-[var(--color-text-secondary)]">
              <HardDrive size={12} className="text-[var(--color-text-muted)]" /> {spec.local_disk_gb} GB SSD
            </div>
          )}
          {spec.gpu_count != null && spec.gpu_count > 0 && (
            <div className="flex items-center gap-1.5 text-[var(--color-text-secondary)] col-span-2">
              <Zap size={12} className="text-[var(--color-text-muted)]" /> {spec.gpu_count} x {spec.gpu_type ?? 'GPU'}
            </div>
          )}
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] col-span-2 pt-1">
            {spec.cloud} - {spec.family}
          </div>
        </div>
      ) : (
        <p className="text-xs text-[var(--color-text-muted)]">Specs not available for this node type.</p>
      )}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="flex justify-between items-baseline gap-3 py-1.5 border-b border-[var(--color-border)] last:border-0">
      <span className="text-xs text-[var(--color-text-muted)]">{label}</span>
      <span className="text-xs text-[var(--color-text-secondary)] text-right font-mono break-all">{value ?? 'N/A'}</span>
    </div>
  );
}

function ClusterDetailPanel({ clusterId, onClose }: { clusterId: string; onClose: () => void }) {
  const detailQ = useQuery({
    queryKey: ['clusterDetail', clusterId],
    queryFn: () => fetchClusterDetail(clusterId),
  });
  const { label: wsLabel } = useWorkspaceNames();

  const d = detailQ.data;

  return (
    <>
      {/* backdrop */}
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      {/* panel */}
      <aside className="fixed top-0 right-0 h-full w-full max-w-xl bg-white border-l border-[var(--color-border)] shadow-xl z-50 overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-[var(--color-border)] px-5 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <Server size={18} className="text-[var(--color-primary)] shrink-0" />
            <h2 className="text-base font-semibold text-[var(--color-text-primary)] truncate">
              {d?.cluster_name ?? 'Cluster Details'}
            </h2>
          </div>
          <button onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-[var(--color-bg-secondary)] transition-colors">
            <X size={18} className="text-[var(--color-text-secondary)]" />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {detailQ.isLoading && (
            <p className="text-center py-12 text-sm text-[var(--color-text-muted)]">Loading cluster details...</p>
          )}
          {detailQ.isError && (
            <p className="text-center py-12 text-sm text-red-600">Failed to load cluster details.</p>
          )}
          {d && (
            <>
              {/* Aggregate hardware */}
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2">
                  Aggregate Capacity
                  <InfoTooltip text="Total CPU and memory across the driver and all workers. For autoscaling clusters this uses the maximum worker count." />
                </h3>
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                    <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">
                      <Cpu size={12} /> Total vCPUs
                    </div>
                    <p className="text-lg font-bold text-[var(--color-text-primary)]">
                      {d.total_vcpus ?? 'N/A'}
                    </p>
                  </div>
                  <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                    <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">
                      <MemoryStick size={12} /> Total Memory
                    </div>
                    <p className="text-lg font-bold text-[var(--color-text-primary)]">
                      {d.total_memory_gb != null ? `${d.total_memory_gb.toLocaleString()} GiB` : 'N/A'}
                    </p>
                  </div>
                </div>
              </section>

              {/* Per-node specs */}
              <section className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                  Node Hardware
                </h3>
                <NodeSpecBlock label="Driver" nodeType={d.driver_node_type} spec={d.driver_spec} />
                <NodeSpecBlock label="Worker" nodeType={d.worker_node_type} spec={d.worker_spec} />
              </section>

              {/* Configuration */}
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2">
                  Configuration
                </h3>
                <div className="bg-white border border-[var(--color-border)] rounded-xl px-3">
                  <DetailRow label="Cluster ID" value={d.cluster_id} />
                  <DetailRow label="Workspace" value={wsLabel(d.workspace_id)} />
                  <DetailRow label="Account ID" value={d.account_id} />
                  <DetailRow label="Owned by" value={d.owned_by} />
                  <DetailRow label="DBR version" value={d.dbr_version} />
                  <DetailRow label="Cluster source" value={d.cluster_source} />
                  <DetailRow label="Security mode" value={d.data_security_mode} />
                  <DetailRow
                    label="Workers"
                    value={
                      d.min_autoscale_workers != null && d.max_autoscale_workers != null
                        ? `${d.min_autoscale_workers}-${d.max_autoscale_workers} (auto)`
                        : d.worker_count != null ? d.worker_count : 'N/A'
                    }
                  />
                </div>
              </section>

              {/* Timestamps */}
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2">
                  Lifecycle
                </h3>
                <div className="bg-white border border-[var(--color-border)] rounded-xl px-3">
                  <DetailRow label="Created" value={fmtDateTime(d.create_time)} />
                  <DetailRow label="Last changed" value={fmtDateTime(d.change_time)} />
                  <DetailRow label="Deleted" value={fmtDateTime(d.delete_time)} />
                  <DetailRow label="Last billed" value={d.last_usage_date ?? 'No usage'} />
                </div>
              </section>

              {/* Lifetime billing */}
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2">
                  Lifetime Billing
                  <InfoTooltip text="Sum of all billed usage across the entire history of this cluster, joined to list_prices." />
                </h3>
                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                    <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">Total Cost</p>
                    <p className="text-lg font-bold text-[var(--color-text-primary)]">{fmtCurrency(d.total_cost)}</p>
                  </div>
                  <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                    <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">Total DBUs</p>
                    <p className="text-lg font-bold text-[var(--color-text-primary)]">
                      {d.total_usage.toLocaleString(undefined, { maximumFractionDigits: 1 })}
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {d.is_photon_observed && (
                    <span className="px-2 py-0.5 text-[10px] font-semibold uppercase rounded-full bg-amber-100 text-amber-800">
                      Photon
                    </span>
                  )}
                  {d.is_serverless_observed && (
                    <span className="px-2 py-0.5 text-[10px] font-semibold uppercase rounded-full bg-purple-100 text-purple-800">
                      Serverless
                    </span>
                  )}
                </div>
                {d.sku_breakdown.length > 0 && (
                  <div className="mt-3 bg-white border border-[var(--color-border)] rounded-xl px-3">
                    {d.sku_breakdown.map((s) => (
                      <div key={s.sku_name}
                        className="flex justify-between items-baseline gap-3 py-1.5 border-b border-[var(--color-border)] last:border-0">
                        <span className="text-xs text-[var(--color-text-secondary)] truncate">{s.sku_name}</span>
                        <span className="text-xs font-medium text-[var(--color-text-primary)] shrink-0">
                          {fmtCurrency(s.total_cost)}
                          <span className="text-[var(--color-text-muted)] ml-1">
                            ({s.total_usage.toLocaleString(undefined, { maximumFractionDigits: 1 })} DBU)
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

function WarehouseSizeBlock({ d }: { d: WarehouseFullDetail }) {
  if (!d.size_spec) {
    return (
      <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
        <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-2">Size</p>
        <p className="text-sm font-medium text-[var(--color-text-primary)] mb-1">{d.warehouse_size ?? 'N/A'}</p>
        <p className="text-xs text-[var(--color-text-muted)]">No spec mapping for this size.</p>
      </div>
    );
  }
  const spec = d.size_spec;
  return (
    <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
      <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-2">Size</p>
      <p className="text-sm font-medium text-[var(--color-text-primary)] mb-2">{spec.label}</p>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
        <div className="flex items-center gap-1.5 text-[var(--color-text-secondary)]">
          <Zap size={12} className="text-[var(--color-text-muted)]" /> {spec.max_dbu_per_hour} DBU/hr
        </div>
        <div className="flex items-center gap-1.5 text-[var(--color-text-secondary)]">
          <Server size={12} className="text-[var(--color-text-muted)]" /> {spec.cluster_count} cluster{spec.cluster_count > 1 ? 's' : ''}
        </div>
      </div>
    </div>
  );
}

function WarehouseDetailPanel({ warehouseId, onClose }: { warehouseId: string; onClose: () => void }) {
  const detailQ = useQuery({
    queryKey: ['warehouseDetail', warehouseId],
    queryFn: () => fetchWarehouseDetail(warehouseId),
  });
  const { label: wsLabel } = useWorkspaceNames();

  const d = detailQ.data;

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <aside className="fixed top-0 right-0 h-full w-full max-w-xl bg-white border-l border-[var(--color-border)] shadow-xl z-50 overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-[var(--color-border)] px-5 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <Database size={18} className="text-[var(--color-accent)] shrink-0" />
            <h2 className="text-base font-semibold text-[var(--color-text-primary)] truncate">
              {d?.warehouse_name ?? 'Warehouse Details'}
            </h2>
          </div>
          <button onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-[var(--color-bg-secondary)] transition-colors">
            <X size={18} className="text-[var(--color-text-secondary)]" />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {detailQ.isLoading && (
            <p className="text-center py-12 text-sm text-[var(--color-text-muted)]">Loading warehouse details...</p>
          )}
          {detailQ.isError && (
            <p className="text-center py-12 text-sm text-red-600">Failed to load warehouse details.</p>
          )}
          {d && (
            <>
              {/* Capacity */}
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2">
                  Peak Capacity
                  <InfoTooltip text="Peak DBU/hr at the maximum scale: size's per-cluster DBU rate multiplied by max_clusters. This is the upper bound, not the typical consumption." />
                </h3>
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                    <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">
                      <Zap size={12} /> Peak DBU/hr
                    </div>
                    <p className="text-lg font-bold text-[var(--color-text-primary)]">
                      {d.max_dbu_per_hour ?? 'N/A'}
                    </p>
                  </div>
                  <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                    <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">
                      <Server size={12} /> Cluster Range
                    </div>
                    <p className="text-lg font-bold text-[var(--color-text-primary)]">
                      {d.min_clusters ?? '?'}-{d.max_clusters ?? '?'}
                    </p>
                  </div>
                </div>
              </section>

              {/* Size + Type */}
              <section className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                  Hardware
                </h3>
                <WarehouseSizeBlock d={d} />
                <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                  <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-2">Type</p>
                  <p className="text-sm font-medium text-[var(--color-text-primary)]">{d.warehouse_type ?? 'N/A'}</p>
                </div>
              </section>

              {/* Configuration */}
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2">
                  Configuration
                </h3>
                <div className="bg-white border border-[var(--color-border)] rounded-xl px-3">
                  <DetailRow label="Warehouse ID" value={d.warehouse_id} />
                  <DetailRow label="Workspace" value={wsLabel(d.workspace_id)} />
                  <DetailRow label="Account ID" value={d.account_id} />
                  <DetailRow label="Created by" value={d.created_by} />
                  <DetailRow label="Auto stop" value={d.auto_stop_minutes != null ? `${d.auto_stop_minutes} min` : 'N/A'} />
                </div>
              </section>

              {/* Lifecycle */}
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2">
                  Lifecycle
                </h3>
                <div className="bg-white border border-[var(--color-border)] rounded-xl px-3">
                  <DetailRow label="Last changed" value={fmtDateTime(d.change_time)} />
                  <DetailRow label="Deleted" value={fmtDateTime(d.delete_time)} />
                  <DetailRow label="Last billed" value={d.last_usage_date ?? 'No usage'} />
                </div>
              </section>

              {/* Lifetime billing */}
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2">
                  Lifetime Billing
                  <InfoTooltip text="Sum of all billed usage across the entire history of this warehouse, joined to list_prices." />
                </h3>
                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                    <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">Total Cost</p>
                    <p className="text-lg font-bold text-[var(--color-text-primary)]">{fmtCurrency(d.total_cost)}</p>
                  </div>
                  <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                    <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">Total DBUs</p>
                    <p className="text-lg font-bold text-[var(--color-text-primary)]">
                      {d.total_usage.toLocaleString(undefined, { maximumFractionDigits: 1 })}
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {d.is_photon_observed && (
                    <span className="px-2 py-0.5 text-[10px] font-semibold uppercase rounded-full bg-amber-100 text-amber-800">
                      Photon
                    </span>
                  )}
                  {d.is_serverless_observed && (
                    <span className="px-2 py-0.5 text-[10px] font-semibold uppercase rounded-full bg-purple-100 text-purple-800">
                      Serverless
                    </span>
                  )}
                </div>
                {d.sku_breakdown.length > 0 && (
                  <div className="mt-3 bg-white border border-[var(--color-border)] rounded-xl px-3">
                    {d.sku_breakdown.map((s) => (
                      <div key={s.sku_name}
                        className="flex justify-between items-baseline gap-3 py-1.5 border-b border-[var(--color-border)] last:border-0">
                        <span className="text-xs text-[var(--color-text-secondary)] truncate">{s.sku_name}</span>
                        <span className="text-xs font-medium text-[var(--color-text-primary)] shrink-0">
                          {fmtCurrency(s.total_cost)}
                          <span className="text-[var(--color-text-muted)] ml-1">
                            ({s.total_usage.toLocaleString(undefined, { maximumFractionDigits: 1 })} DBU)
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

export default function Compute() {
  const [tab, setTab] = useState<Tab>('clusters');
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [searchTimeout, setSearchTimeout] = useState<ReturnType<typeof setTimeout> | null>(null);
  const [clusterPage, setClusterPage] = useState(1);
  const [warehousePage, setWarehousePage] = useState(1);
  const [startDate, setStartDate] = useState(daysAgo(30));
  const [endDate, setEndDate] = useState(today());
  const [selectedCluster, setSelectedCluster] = useState<string | null>(null);
  const [selectedWarehouse, setSelectedWarehouse] = useState<string | null>(null);

  // Sort + filter state for Clusters tab
  const [sortIdx, setSortIdx] = useState(0);
  const [filters, setFilters] = useState<ClusterFilters>(EMPTY_FILTERS);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const activeFilterCount = countActiveFilters(filters);

  function updateFilter<K extends keyof ClusterFilters>(key: K, value: ClusterFilters[K]) {
    setFilters((f) => ({ ...f, [key]: value }));
    setClusterPage(1);
  }

  function clearFilters() {
    setFilters(EMPTY_FILTERS);
    setClusterPage(1);
  }

  function handleSearchChange(value: string) {
    setSearchTerm(value);
    if (searchTimeout) clearTimeout(searchTimeout);
    setSearchTimeout(setTimeout(() => {
      setDebouncedSearch(value);
      setClusterPage(1);
      setWarehousePage(1);
    }, 400));
  }

  // Server-side paginated queries
  const sortChoice = SORT_OPTIONS[sortIdx];
  const clustersQ = useQuery({
    queryKey: ['clusters', clusterPage, PAGE_SIZE, debouncedSearch, sortIdx, filters],
    queryFn: () => fetchClusters({
      page: clusterPage,
      pageSize: PAGE_SIZE,
      search: debouncedSearch || undefined,
      clusterSource: filters.clusterSource || undefined,
      dataSecurityMode: filters.dataSecurityMode || undefined,
      nodeFamily: filters.nodeFamily || undefined,
      hasGpu: filters.hasGpu === '' ? undefined : filters.hasGpu === 'true',
      minVcpus: filters.minVcpus ? Number(filters.minVcpus) : undefined,
      minMemoryGb: filters.minMemoryGb ? Number(filters.minMemoryGb) : undefined,
      sortBy: sortChoice.value,
      sortOrder: sortChoice.order,
    }),
  });

  const warehousesQ = useQuery({
    queryKey: ['warehouses', warehousePage, PAGE_SIZE, debouncedSearch],
    queryFn: () => fetchWarehouses(warehousePage, PAGE_SIZE, debouncedSearch || undefined),
  });

  const clusterCostQ = useQuery({
    queryKey: ['clusterCost', selectedCluster, startDate, endDate],
    queryFn: () => fetchClusterCost(selectedCluster!, startDate, endDate),
    enabled: selectedCluster !== null,
  });

  const warehouseCostQ = useQuery({
    queryKey: ['warehouseCost', selectedWarehouse, startDate, endDate],
    queryFn: () => fetchWarehouseCost(selectedWarehouse!, startDate, endDate),
    enabled: selectedWarehouse !== null,
  });

  const clusters: ClusterDetail[] = clustersQ.data?.data ?? [];
  const warehouses: WarehouseDetail[] = warehousesQ.data?.data ?? [];
  const clusterTotal = clustersQ.data?.total ?? 0;
  const clusterTotalPages = clustersQ.data?.total_pages ?? 1;
  const warehouseTotal = warehousesQ.data?.total ?? 0;
  const warehouseTotalPages = warehousesQ.data?.total_pages ?? 1;

  const selectedCostData: ComputeCostResponse | undefined =
    tab === 'clusters' ? clusterCostQ.data : warehouseCostQ.data;

  const selectedResourceName =
    tab === 'clusters'
      ? clusters.find((c) => c.cluster_id === selectedCluster)?.cluster_name
      : warehouses.find((w) => w.warehouse_id === selectedWarehouse)?.warehouse_name;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <Server size={24} className="text-[var(--color-primary)]" />
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Compute Resources</h1>
        </div>
        <div className="bg-blue-50 border border-blue-200 rounded-2xl px-4 py-3 text-xs text-[var(--color-text-secondary)] leading-relaxed">
          View and analyze your Databricks compute infrastructure. Clusters are used for notebooks
          and jobs, while SQL Warehouses handle BI queries. Click any resource to see its cost breakdown.
          <InfoTooltip text="The clusters table contains one row per cluster change event (not one per cluster). The same cluster_id may appear multiple times if its configuration changed. Search by name, ID, or owner." />
        </div>
      </div>

      {/* Date filter */}
      <DateRangeFilter startDate={startDate} endDate={endDate} onStartChange={setStartDate} onEndChange={setEndDate} />

      {/* Tabs */}
      <div className="flex gap-2">
        <button
          onClick={() => { setTab('clusters'); setSearchTerm(''); setDebouncedSearch(''); }}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors rounded-full ${
            tab === 'clusters' ? 'bg-[var(--color-primary)] text-white' : 'bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]'
          }`}>
          <Server size={16} />
          Clusters
          <span className="ml-1 px-1.5 py-0.5 text-[10px] font-semibold rounded-full bg-white/20">{clusterTotal.toLocaleString()}</span>
        </button>
        <button
          onClick={() => { setTab('warehouses'); setSearchTerm(''); setDebouncedSearch(''); }}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors rounded-full ${
            tab === 'warehouses' ? 'bg-[var(--color-primary)] text-white' : 'bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]'
          }`}>
          <Database size={16} />
          SQL Warehouses
          <span className="ml-1 px-1.5 py-0.5 text-[10px] font-semibold rounded-full bg-white/20">{warehouseTotal.toLocaleString()}</span>
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
        <input
          type="text"
          placeholder={`Search ${tab} by name, ID, or owner...`}
          value={searchTerm}
          onChange={(e) => handleSearchChange(e.target.value)}
          className="w-full pl-9 pr-4 py-2 text-sm bg-white border border-[var(--color-border)] rounded-lg text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
        />
      </div>

      {/* Clusters tab */}
      {tab === 'clusters' && (
        <>
          {/* Sort + filter controls */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-2 bg-white border border-[var(--color-border)] rounded-lg px-3 py-1.5">
              <ArrowUpDown size={14} className="text-[var(--color-text-muted)]" />
              <span className="text-xs text-[var(--color-text-muted)]">Sort:</span>
              <select
                value={sortIdx}
                onChange={(e) => { setSortIdx(Number(e.target.value)); setClusterPage(1); }}
                className="text-xs text-[var(--color-text-primary)] bg-transparent focus:outline-none cursor-pointer"
              >
                {SORT_OPTIONS.map((opt, i) => (
                  <option key={i} value={i}>{opt.label}</option>
                ))}
              </select>
            </div>
            <button
              onClick={() => setFiltersOpen((v) => !v)}
              className={`flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                filtersOpen || activeFilterCount > 0
                  ? 'bg-[var(--color-primary)] text-white border-[var(--color-primary)]'
                  : 'bg-white text-[var(--color-text-secondary)] border-[var(--color-border)]'
              }`}
            >
              <SlidersHorizontal size={14} />
              Filters
              {activeFilterCount > 0 && (
                <span className="px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-white/20">{activeFilterCount}</span>
              )}
            </button>
            {activeFilterCount > 0 && (
              <button
                onClick={clearFilters}
                className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] underline"
              >
                Clear all
              </button>
            )}
          </div>

          {filtersOpen && (
            <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-1.5">Cluster Source</label>
                <select
                  value={filters.clusterSource}
                  onChange={(e) => updateFilter('clusterSource', e.target.value)}
                  className="w-full text-xs bg-white border border-[var(--color-border)] rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
                >
                  <option value="">Any</option>
                  {CLUSTER_SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-1.5">Security Mode</label>
                <select
                  value={filters.dataSecurityMode}
                  onChange={(e) => updateFilter('dataSecurityMode', e.target.value)}
                  className="w-full text-xs bg-white border border-[var(--color-border)] rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
                >
                  <option value="">Any</option>
                  {SECURITY_MODES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-1.5">Node Family</label>
                <select
                  value={filters.nodeFamily}
                  onChange={(e) => updateFilter('nodeFamily', e.target.value)}
                  className="w-full text-xs bg-white border border-[var(--color-border)] rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
                >
                  <option value="">Any</option>
                  {NODE_FAMILIES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-1.5">GPU</label>
                <select
                  value={filters.hasGpu}
                  onChange={(e) => updateFilter('hasGpu', e.target.value as ClusterFilters['hasGpu'])}
                  className="w-full text-xs bg-white border border-[var(--color-border)] rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
                >
                  <option value="">Any</option>
                  <option value="true">GPU only</option>
                  <option value="false">No GPU</option>
                </select>
              </div>
              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-1.5">
                  Min Total vCPUs
                  <InfoTooltip text="Filters out clusters whose driver + workers fall below this vCPU count. Excludes clusters with unknown node types." />
                </label>
                <input
                  type="number"
                  min="0"
                  value={filters.minVcpus}
                  onChange={(e) => updateFilter('minVcpus', e.target.value)}
                  placeholder="e.g. 8"
                  className="w-full text-xs bg-white border border-[var(--color-border)] rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
                />
              </div>
              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-1.5">
                  Min Total Memory (GiB)
                  <InfoTooltip text="Filters out clusters whose driver + workers fall below this memory threshold. Excludes clusters with unknown node types." />
                </label>
                <input
                  type="number"
                  min="0"
                  value={filters.minMemoryGb}
                  onChange={(e) => updateFilter('minMemoryGb', e.target.value)}
                  placeholder="e.g. 32"
                  className="w-full text-xs bg-white border border-[var(--color-border)] rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
                />
              </div>
            </div>
          )}

          {clustersQ.isLoading ? (
            <div className="text-center py-12 text-sm text-[var(--color-text-muted)]">Loading clusters...</div>
          ) : clusters.length === 0 ? (
            <div className="text-center py-12 text-sm text-[var(--color-text-muted)]">
              No clusters found{debouncedSearch ? ` matching "${debouncedSearch}"` : ''}.
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {clusters.map((c) => (
                  <ClusterCard
                    key={`${c.cluster_id}-${c.create_time}`}
                    cluster={c}
                    isSelected={selectedCluster === c.cluster_id}
                    onClick={() => setSelectedCluster(selectedCluster === c.cluster_id ? null : c.cluster_id)}
                  />
                ))}
              </div>
              <Pagination
                page={clusterPage}
                totalPages={clusterTotalPages}
                total={clusterTotal}
                pageSize={PAGE_SIZE}
                onPageChange={setClusterPage}
              />
            </>
          )}
          <FieldDefinitions title="Cluster Field Definitions" fields={CLUSTER_FIELD_DEFS} />
        </>
      )}

      {/* Warehouses tab */}
      {tab === 'warehouses' && (
        <>
          {warehousesQ.isLoading ? (
            <div className="text-center py-12 text-sm text-[var(--color-text-muted)]">Loading warehouses...</div>
          ) : warehouses.length === 0 ? (
            <div className="text-center py-12 text-sm text-[var(--color-text-muted)]">
              No warehouses found{debouncedSearch ? ` matching "${debouncedSearch}"` : ''}.
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {warehouses.map((w) => (
                  <WarehouseCard
                    key={w.warehouse_id}
                    warehouse={w}
                    isSelected={selectedWarehouse === w.warehouse_id}
                    onClick={() => setSelectedWarehouse(selectedWarehouse === w.warehouse_id ? null : w.warehouse_id)}
                  />
                ))}
              </div>
              <Pagination
                page={warehousePage}
                totalPages={warehouseTotalPages}
                total={warehouseTotal}
                pageSize={PAGE_SIZE}
                onPageChange={setWarehousePage}
              />
            </>
          )}
          <FieldDefinitions title="Warehouse Field Definitions" fields={WAREHOUSE_FIELD_DEFS} />
        </>
      )}

      {/* Cost breakdown */}
      {((tab === 'clusters' && selectedCluster) || (tab === 'warehouses' && selectedWarehouse)) && (
        <ChartCard
          title={`Cost Breakdown: ${selectedResourceName ?? 'Selected Resource'}`}
          tooltip={`Cost and DBU usage for the selected ${tab === 'clusters' ? 'cluster' : 'warehouse'} over the chosen date range.`}
          isLoading={tab === 'clusters' ? clusterCostQ.isLoading : warehouseCostQ.isLoading}
          exportFilename={`cost-breakdown-${selectedResourceName || 'resource'}`}
          exportRows={() => selectedCostData ? [{
            resource_id: selectedCostData.resource_id,
            resource_name: selectedResourceName ?? '',
            start_date: selectedCostData.start_date,
            end_date: selectedCostData.end_date,
            total_cost: selectedCostData.total_cost,
            total_usage: selectedCostData.total_usage,
          }] : []}
        >
          {selectedCostData ? (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                  <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">Total Cost</p>
                  <p className="text-lg font-bold text-[var(--color-text-primary)]">{fmtCurrency(selectedCostData.total_cost)}</p>
                </div>
                <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                  <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">Total DBUs</p>
                  <p className="text-lg font-bold text-[var(--color-text-primary)]">{selectedCostData.total_usage.toLocaleString(undefined, { maximumFractionDigits: 1 })}</p>
                </div>
                <div className="bg-[var(--color-bg-secondary)] rounded-xl p-3 border border-[var(--color-border)]">
                  <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">Period</p>
                  <p className="text-sm font-medium text-[var(--color-text-primary)]">{selectedCostData.start_date} to {selectedCostData.end_date}</p>
                </div>
              </div>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={[{ name: 'Cost ($)', value: selectedCostData.total_cost }, { name: 'DBUs', value: selectedCostData.total_usage }]} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e5ea" />
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#86868b' }} />
                  <YAxis tick={{ fontSize: 11, fill: '#86868b' }} />
                  <Tooltip contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e5ea', borderRadius: '0.75rem', boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)' }} formatter={(value: number) => [value.toLocaleString(), 'Value']} />
                  <Bar dataKey="value" fill="#0071e3" radius={[4, 4, 0, 0]} maxBarSize={64} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-sm text-[var(--color-text-muted)] text-center py-8">No cost data available for this resource.</p>
          )}
        </ChartCard>
      )}

      {/* Cluster detail panel */}
      {tab === 'clusters' && selectedCluster && (
        <ClusterDetailPanel
          clusterId={selectedCluster}
          onClose={() => setSelectedCluster(null)}
        />
      )}

      {/* Warehouse detail panel */}
      {tab === 'warehouses' && selectedWarehouse && (
        <WarehouseDetailPanel
          warehouseId={selectedWarehouse}
          onClose={() => setSelectedWarehouse(null)}
        />
      )}
    </div>
  );
}
