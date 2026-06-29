import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Database,
  Download,
  RefreshCw,
  FileDown,
  Sparkles,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  Info,
  Brain,
  Cpu,
  Flame,
  Trash2,
  RotateCcw,
  PlusCircle,
} from 'lucide-react';
import InfoTooltip from '../components/InfoTooltip';
import {
  fetchDataSourceStatus,
  fetchTableCounts,
  triggerExtract,
  triggerIngestParquet,
  triggerSeedDemo,
  triggerExtractQueryIntel,
  triggerTransformLineage,
  triggerMaterializePostgresToSpark,
  fetchEngine,
  setEngine,
  dataOps,
  ALL_EXTRACT_GROUPS,
  type DataOrigin,
  type ExtractGroup,
  type SparkMode,
} from '../api/client';
import type { ExtractionResult, IngestResult, QueryIntelResult, EngineState, LineageRollupResult, ProgressEntry, MaterializeResult } from '../api/client';
import { useProgress } from '../hooks/useProgress';
import { ProgressCard } from '../components/ProgressCard';

const EXTRACT_GROUP_LABELS: Record<ExtractGroup, { label: string; help: string }> = {
  billing: {
    label: 'Billing',
    help: 'system.billing.usage + list_prices. The core cost data set.',
  },
  compute: {
    label: 'Compute',
    help: 'clusters + warehouses + jobs + workspaces. Resource registry + cost-attribution lookups.',
  },
  query_history: {
    label: 'Query History',
    help: 'system.query.history. Statement-level audit trail; large — only refresh when needed.',
  },
  meta: {
    label: 'Unity Catalog Meta',
    help: 'INFORMATION_SCHEMA crawl across all accessible catalogs. Powers Meta Explorer.',
  },
  lineage: {
    label: 'Lineage',
    help: 'system.access.table_lineage + column_lineage. Powers the Meta Explorer > Lineage page. Requires Unity Catalog and the account-level system schema; tolerated to fail if missing.',
  },
  audit: {
    label: 'Audit',
    help: 'system.access.audit + system.access.assistant_events. Powers the Meta Explorer > Audit page. Lookback is shared with lineage and defaults to 30 days.',
  },
  node_pool: {
    label: 'Node Pool',
    help: 'system.compute.node_timeline + warehouse_events + node_types + node_events (instance_events) + instance_pools. Per-minute instance utilization plus warehouse/instance lifecycle. node_timeline is the highest-cardinality table; the lookback below defaults to 3 days.',
  },
};

const numberFmt = new Intl.NumberFormat('en-US');

export default function DataManagement() {
  const queryClient = useQueryClient();
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10));
  const [replaceData, setReplaceData] = useState(false);
  // Lineage and node_pool are unchecked by default — they're the most
  // expensive groups to pull (lineage = many-million row tables; node_pool's
  // node_timeline is per-minute-per-instance) and are only needed for the
  // dedicated Meta Explorer pages. Everything else is on by default for
  // parity with the previous behavior.
  const [extractGroups, setExtractGroups] = useState<Set<ExtractGroup>>(
    () => new Set<ExtractGroup>(ALL_EXTRACT_GROUPS.filter((g) => g !== 'lineage' && g !== 'node_pool')),
  );
  // Lineage tables can have tens of millions of rows on a busy account, so
  // each gets its own (shorter) window. column_lineage is typically 3-5x the
  // volume of table_lineage, hence the tighter default.
  const [tableLineageDaysBack, setTableLineageDaysBack]   = useState<number>(14);
  const [columnLineageDaysBack, setColumnLineageDaysBack] = useState<number>(7);
  // Per-table lookbacks. audit_events and node_timeline are the
  // high-cardinality ones (3d default); assistant_events / warehouse_events
  // / instance_events are event logs with lighter volume so they can
  // afford a wider window. node_types and instance_pools are reference
  // tables (no date bound) and don't take a knob.
  const [auditEventsDaysBack,      setAuditEventsDaysBack]      = useState<number>(3);
  const [assistantEventsDaysBack,  setAssistantEventsDaysBack]  = useState<number>(30);
  const [nodeTimelineDaysBack,     setNodeTimelineDaysBack]     = useState<number>(3);
  const [warehouseEventsDaysBack,  setWarehouseEventsDaysBack]  = useState<number>(30);
  const [instanceEventsDaysBack,   setInstanceEventsDaysBack]   = useState<number>(14);
  const toggleExtractGroup = (g: ExtractGroup) => {
    setExtractGroups((prev) => {
      const next = new Set(prev);
      if (next.has(g)) next.delete(g);
      else next.add(g);
      return next;
    });
  };
  const selectedGroups: ExtractGroup[] = ALL_EXTRACT_GROUPS.filter((g) => extractGroups.has(g));
  const [result, setResult] = useState<ExtractionResult | IngestResult | null>(null);
  const [qiResult, setQiResult] = useState<QueryIntelResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const statusQuery = useQuery({
    queryKey: ['admin-status'],
    queryFn: fetchDataSourceStatus,
  });

  const countsQuery = useQuery({
    queryKey: ['admin-table-counts'],
    queryFn: fetchTableCounts,
    refetchInterval: 10000,
  });

  // After any data-mutating action: invalidate all cached queries AND
  // proactively refetch the workspace-name lookup so chart labels pick up
  // newly-discovered workspace_name values even when the consuming page
  // (e.g. SKU & Billing Origin) isn't currently mounted. invalidateQueries
  // alone refetches only ACTIVE queries by default, which means an inactive
  // ws-meta would stay stale-but-cached until the next mount.
  const refreshAfterDataChange = async () => {
    await queryClient.invalidateQueries();
    await queryClient.refetchQueries({ queryKey: ['ws-meta'] });
  };

  const extractFullMutation = useMutation({
    mutationFn: () => triggerExtract(
      startDate, endDate, true, 'full', selectedGroups,
      tableLineageDaysBack, columnLineageDaysBack,
      auditEventsDaysBack, assistantEventsDaysBack,
      nodeTimelineDaysBack, warehouseEventsDaysBack, instanceEventsDaysBack,
    ),
    onSuccess: async (data) => { setResult(data); setError(null); await refreshAfterDataChange(); },
    onError: (err: Error) => { setError(err.message); setResult(null); },
  });
  const extractIncrementalMutation = useMutation({
    mutationFn: () => triggerExtract(
      startDate, endDate, false, 'incremental', selectedGroups,
      tableLineageDaysBack, columnLineageDaysBack,
      auditEventsDaysBack, assistantEventsDaysBack,
      nodeTimelineDaysBack, warehouseEventsDaysBack, instanceEventsDaysBack,
    ),
    onSuccess: async (data) => { setResult(data); setError(null); await refreshAfterDataChange(); },
    onError: (err: Error) => { setError(err.message); setResult(null); },
  });
  // Kept for back-compat; not used after the full/incremental split.
  const extractMutation = useMutation({
    mutationFn: () => triggerExtract(startDate, endDate, replaceData),
    onSuccess: async (data) => {
      setResult(data);
      setError(null);
      await refreshAfterDataChange();
    },
    onError: (err: Error) => {
      setError(err.message);
      setResult(null);
    },
  });

  const ingestMutation = useMutation({
    mutationFn: () => triggerIngestParquet(replaceData),
    onSuccess: async (data) => {
      setResult(data);
      setError(null);
      await refreshAfterDataChange();
    },
    onError: (err: Error) => {
      setError(err.message);
      setResult(null);
    },
  });

  const seedMutation = useMutation({
    mutationFn: () => triggerSeedDemo(true),
    onSuccess: async (data) => {
      setResult(data);
      setError(null);
      await refreshAfterDataChange();
    },
    onError: (err: Error) => {
      setError(err.message);
      setResult(null);
    },
  });

  const engineQuery = useQuery({
    queryKey: ['admin-engine'],
    queryFn: fetchEngine,
  });

  const engineMutation = useMutation({
    mutationFn: (args: { engine: 'duckdb' | 'spark'; spark_mode?: SparkMode }) =>
      setEngine(args.engine, args.spark_mode),
    onSuccess: (data) => {
      queryClient.setQueryData(['admin-engine'], data);
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  // One-shot materialization: copies Postgres base tables into spark-warehouse
  // as managed Delta tables. Long-running for table_lineage / column_lineage;
  // the backend publishes per-table progress to /api/data-ops/progress.
  const [materializeResult, setMaterializeResult] = useState<MaterializeResult | null>(null);
  const materializeMutation = useMutation({
    mutationFn: triggerMaterializePostgresToSpark,
    onSuccess: async (data) => {
      setMaterializeResult(data);
      setError(null);
      // Refresh engine state so the active spark_mode flips to 'materialized'.
      await queryClient.invalidateQueries({ queryKey: ['admin-engine'] });
      await queryClient.invalidateQueries({ queryKey: ['spark-tables'] });
    },
    onError: (err: Error) => { setError(err.message); setMaterializeResult(null); },
  });

  const queryIntelDemoMutation = useMutation({
    mutationFn: () => triggerExtractQueryIntel(true),
    onSuccess: async (data) => {
      setQiResult(data);
      setError(null);
      await refreshAfterDataChange();
    },
    onError: (err: Error) => {
      setError(err.message);
      setQiResult(null);
    },
  });

  // Data isolation operations — all kick off background jobs.
  const opMutation = useMutation({
    mutationFn: async (fn: () => Promise<{ job_id: number }>) => fn(),
    onSuccess: async () => {
      setError(null);
      // Bring the notifications bell up to date immediately.
      await queryClient.invalidateQueries({ queryKey: ['data-ops-jobs'] });
      await queryClient.invalidateQueries({ queryKey: ['admin-table-counts'] });
    },
    onError: (err: Error) => setError(err.message),
  });

  const confirmAndRun = (label: string, fn: () => Promise<{ job_id: number }>) => {
    if (window.confirm(`${label}\n\nThis runs as a background job. Watch progress in the bell icon at the top right.`)) {
      opMutation.mutate(fn);
    }
  };

  const queryIntelRealMutation = useMutation({
    mutationFn: () => triggerExtractQueryIntel(false),
    onSuccess: async (data) => {
      setQiResult(data);
      setError(null);
      await refreshAfterDataChange();
    },
    onError: (err: Error) => {
      setError(err.message);
      setQiResult(null);
    },
  });

  // Lineage rollups — independent of QI ETL, writes the `lineage_rollups`
  // cache table used by the Lineage dashboards' KPI tiles.
  const [lineageResult, setLineageResult] = useState<LineageRollupResult | null>(null);
  const lineageDemoMutation = useMutation({
    mutationFn: () => triggerTransformLineage(true),
    onSuccess: async (data) => { setLineageResult(data); setError(null); await refreshAfterDataChange(); },
    onError: (err: Error) => { setError(err.message); setLineageResult(null); },
  });
  const lineageRealMutation = useMutation({
    mutationFn: () => triggerTransformLineage(false),
    onSuccess: async (data) => { setLineageResult(data); setError(null); await refreshAfterDataChange(); },
    onError: (err: Error) => { setError(err.message); setLineageResult(null); },
  });

  const isLoading = extractMutation.isPending || extractFullMutation.isPending || extractIncrementalMutation.isPending || ingestMutation.isPending || seedMutation.isPending || queryIntelDemoMutation.isPending || queryIntelRealMutation.isPending || lineageDemoMutation.isPending || lineageRealMutation.isPending;
  const status = statusQuery.data;
  const counts = countsQuery.data;

  // Live progress map — poll fast while any of the above is in-flight,
  // slow when idle so the tail-end "success"/"failed" state still updates.
  const progress = useProgress(isLoading);
  // Convenience filters by operation "kind", so each section only renders
  // the progress card it triggered.
  const progressFor = (kinds: string[]): ProgressEntry[] =>
    kinds.map((k) => progress.byKind[k]).filter(Boolean);

  return (
    <div className="space-y-6 max-w-[1000px]">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Data Management</h1>
        <p className="text-sm text-[var(--color-text-muted)] mt-1">
          Extract billing data from Databricks or manage local data sources
        </p>
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-2xl px-4 py-3">
        <Info size={18} className="text-[var(--color-primary)] mt-0.5 shrink-0" />
        <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
          This page lets you manage how billing data gets into the app.
          <strong> Extract from Databricks</strong> connects live, JOINs usage with list_prices in Spark SQL, and pre-calculates
          <code className="bg-gray-100 px-1 rounded">usage_usd</code> using Databricks' own formula.
          <strong> Load Real Data</strong> ingests pre-extracted parquet files (which include usage_usd).
          <strong> Load Demo Data</strong> loads <code className="bg-gray-100 px-1 rounded">demo_*.parquet</code> files (Acme Corp fakes that mirror real shape/distribution; generate with <code className="bg-gray-100 px-1 rounded">scripts/simulate_demo_data.py</code>).
          Cost = <code className="bg-gray-100 px-1 rounded">COALESCE(usage_quantity * pricing.effective_list.default, 0)</code>.
        </p>
      </div>

      {/* Connection Status */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-[var(--color-text-primary)] mb-4 flex items-center gap-2">
          <Database size={16} />
          Connection Status
          <InfoTooltip text="Shows whether a Databricks connection is configured via DATABRICKS_HOST and DATABRICKS_TOKEN environment variables." />
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="flex items-center gap-3">
            {status?.databricks_connected ? (
              <CheckCircle2 size={20} className="text-green-500" />
            ) : (
              <XCircle size={20} className="text-gray-400" />
            )}
            <div>
              <p className="text-sm font-medium text-[var(--color-text-primary)]">
                Databricks {status?.databricks_connected ? 'Connected' : 'Not Configured'}
              </p>
              <p className="text-xs text-[var(--color-text-muted)]">
                {status?.databricks_host || 'Set DATABRICKS_HOST env var'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Database size={20} className="text-[var(--color-primary)]" />
            <div>
              <p className="text-sm font-medium text-[var(--color-text-primary)]">
                Data Source: {status?.source || '--'}
              </p>
              <p className="text-xs text-[var(--color-text-muted)]">
                Current ingestion mode
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Table Counts */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-[var(--color-text-primary)] mb-4 flex items-center gap-2">
          <Database size={16} />
          Current Data
          <InfoTooltip text="Row counts for each table in the Postgres database. These update automatically." />
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {counts && Object.entries(counts).map(([table, count]) => (
            <div key={table} className="bg-[var(--color-bg-secondary)] rounded-xl p-3 text-center">
              <p className="text-lg font-bold text-[var(--color-text-primary)]">
                {numberFmt.format(count)}
              </p>
              <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
                {table.replace('_', ' ')}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Extract from Databricks */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-[var(--color-text-primary)] mb-4 flex items-center gap-2">
          <Download size={16} />
          Extract from Databricks
          <InfoTooltip text="Connects to your Databricks workspace, runs a Spark SQL query that JOINs system.billing.usage with list_prices to pre-calculate usage_usd (matching Databricks' own billing dashboard formula: COALESCE(usage_quantity * pricing.effective_list.default, 0)). Also extracts compute tables. Requires DATABRICKS_HOST and DATABRICKS_TOKEN." />
        </h2>

        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <label className="block text-xs text-[var(--color-text-muted)] mb-1">Start Date</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="bg-white border border-[var(--color-border)] rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
              />
            </div>
            <div>
              <label className="block text-xs text-[var(--color-text-muted)] mb-1">End Date</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="bg-white border border-[var(--color-border)] rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]"
              />
            </div>
            <label className="flex items-center gap-2 mt-4">
              <input
                type="checkbox"
                checked={replaceData}
                onChange={(e) => setReplaceData(e.target.checked)}
                className="rounded"
              />
              <span className="text-sm text-[var(--color-text-secondary)]">Replace existing data</span>
              <InfoTooltip text="If checked, existing data will be deleted before inserting. If unchecked, new records are appended (duplicates are skipped by record_id)." />
            </label>
          </div>

          {/* Per-group checkboxes — pick which slices of Databricks to refresh. */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium text-[var(--color-text-secondary)]">Refresh which groups</span>
              <InfoTooltip text="Each group writes its own *_<date>.parquet snapshot. Downstream reads pick the newest file per table, so leaving a group unchecked just keeps the previous snapshot in place — handy when one slice (e.g. query_history) is much bigger than the others." />
              <button
                type="button"
                onClick={() => setExtractGroups(new Set(ALL_EXTRACT_GROUPS))}
                className="ml-auto text-[11px] text-[var(--color-primary)] hover:underline"
              >
                Select all
              </button>
              <button
                type="button"
                onClick={() => setExtractGroups(new Set())}
                className="text-[11px] text-[var(--color-text-muted)] hover:underline"
              >
                Clear
              </button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
              {ALL_EXTRACT_GROUPS.map((g) => {
                const checked = extractGroups.has(g);
                const meta = EXTRACT_GROUP_LABELS[g];
                return (
                  <label
                    key={g}
                    className={`flex items-start gap-2 border rounded-lg px-3 py-2 cursor-pointer transition-colors ${
                      checked
                        ? 'border-[var(--color-primary)] bg-[var(--color-primary)]/5'
                        : 'border-[var(--color-border)] bg-white hover:bg-[var(--color-bg-soft)]'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleExtractGroup(g)}
                      className="mt-0.5 rounded"
                    />
                    <span className="flex-1 min-w-0">
                      <span className="block text-sm font-medium text-[var(--color-text-primary)]">{meta.label}</span>
                      <span className="block text-[11px] text-[var(--color-text-muted)] mt-0.5 leading-snug">{meta.help}</span>
                    </span>
                  </label>
                );
              })}
            </div>

            {/* Lineage-specific lookbacks — only relevant when the Lineage
                group is checked. system.access.*_lineage can run to tens of
                millions of rows over a 2-year window, so each table gets its
                own (much shorter) slice. column_lineage is typically 3-5x the
                volume of table_lineage, hence the tighter default. */}
            {extractGroups.has('lineage') && (
              <div className="mt-3 flex items-start gap-3 border border-amber-200 bg-amber-50/60 rounded-lg px-3 py-2">
                <AlertTriangle size={14} className="text-amber-600 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0 space-y-1.5">
                  <p className="text-xs text-amber-900 leading-snug">
                    <strong>Lineage lookback</strong> — each lineage system table is
                    sliced on its own window (independent of the main date range above).
                    A wide lineage scan can be tens of millions of rows and OOM the extractor.
                  </p>
                  <div className="flex flex-wrap items-center gap-3 text-xs text-amber-900">
                    <label className="inline-flex items-center gap-1">
                      <span><code>table_lineage</code>:</span>
                      <input
                        type="number"
                        min={1} max={365}
                        value={tableLineageDaysBack}
                        onChange={(e) => setTableLineageDaysBack(Math.max(1, Math.min(365, Number(e.target.value) || 14)))}
                        className="w-16 px-1.5 py-0.5 bg-white border border-amber-300 rounded"
                      />
                      <span>days</span>
                    </label>
                    <label className="inline-flex items-center gap-1">
                      <span><code>column_lineage</code>:</span>
                      <input
                        type="number"
                        min={1} max={365}
                        value={columnLineageDaysBack}
                        onChange={(e) => setColumnLineageDaysBack(Math.max(1, Math.min(365, Number(e.target.value) || 7)))}
                        className="w-16 px-1.5 py-0.5 bg-white border border-amber-300 rounded"
                      />
                      <span>days</span>
                    </label>
                    <span className="text-amber-700/80">
                      defaults: 14 / 7
                    </span>
                  </div>
                </div>
              </div>
            )}

            {extractGroups.has('audit') && (
              <div className="mt-3 flex items-start gap-3 border border-amber-200 bg-amber-50/60 rounded-lg px-3 py-2">
                <AlertTriangle size={14} className="text-amber-600 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0 space-y-1.5">
                  <p className="text-xs text-amber-900 leading-snug">
                    <strong>Audit lookback</strong> — per-table windows, independent
                    of the main date range. <code>audit_events</code> can be very
                    high-volume on busy accounts; <code>assistant_events</code> is
                    low-volume so it can afford a wider window.
                  </p>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-amber-900">
                    <label className="inline-flex items-center gap-1">
                      <span><code>audit_events</code>:</span>
                      <input
                        type="number"
                        min={1} max={365}
                        value={auditEventsDaysBack}
                        onChange={(e) => setAuditEventsDaysBack(Math.max(1, Math.min(365, Number(e.target.value) || 3)))}
                        className="w-16 px-1.5 py-0.5 bg-white border border-amber-300 rounded"
                      />
                      <span>days <span className="text-amber-700/80">(default 3)</span></span>
                    </label>
                    <label className="inline-flex items-center gap-1">
                      <span><code>assistant_events</code>:</span>
                      <input
                        type="number"
                        min={1} max={365}
                        value={assistantEventsDaysBack}
                        onChange={(e) => setAssistantEventsDaysBack(Math.max(1, Math.min(365, Number(e.target.value) || 30)))}
                        className="w-16 px-1.5 py-0.5 bg-white border border-amber-300 rounded"
                      />
                      <span>days <span className="text-amber-700/80">(default 30)</span></span>
                    </label>
                  </div>
                </div>
              </div>
            )}

            {extractGroups.has('node_pool') && (
              <div className="mt-3 flex items-start gap-3 border border-amber-200 bg-amber-50/60 rounded-lg px-3 py-2">
                <AlertTriangle size={14} className="text-amber-600 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0 space-y-1.5">
                  <p className="text-xs text-amber-900 leading-snug">
                    <strong>Node Pool lookback</strong> — per-table windows.
                    <code> node_types</code> and <code>instance_pools</code> are
                    reference tables (no date bound) and don't take a knob.
                    <code> node_timeline</code> is per-minute-per-instance — wide
                    windows will OOM the Spark Connect driver.
                  </p>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-amber-900">
                    <label className="inline-flex items-center gap-1">
                      <span><code>node_timeline</code>:</span>
                      <input
                        type="number"
                        min={1} max={365}
                        value={nodeTimelineDaysBack}
                        onChange={(e) => setNodeTimelineDaysBack(Math.max(1, Math.min(365, Number(e.target.value) || 3)))}
                        className="w-16 px-1.5 py-0.5 bg-white border border-amber-300 rounded"
                      />
                      <span>days <span className="text-amber-700/80">(default 3)</span></span>
                    </label>
                    <label className="inline-flex items-center gap-1">
                      <span><code>warehouse_events</code>:</span>
                      <input
                        type="number"
                        min={1} max={365}
                        value={warehouseEventsDaysBack}
                        onChange={(e) => setWarehouseEventsDaysBack(Math.max(1, Math.min(365, Number(e.target.value) || 30)))}
                        className="w-16 px-1.5 py-0.5 bg-white border border-amber-300 rounded"
                      />
                      <span>days <span className="text-amber-700/80">(default 30)</span></span>
                    </label>
                    <label className="inline-flex items-center gap-1">
                      <span><code>instance_events</code>:</span>
                      <input
                        type="number"
                        min={1} max={365}
                        value={instanceEventsDaysBack}
                        onChange={(e) => setInstanceEventsDaysBack(Math.max(1, Math.min(365, Number(e.target.value) || 14)))}
                        className="w-16 px-1.5 py-0.5 bg-white border border-amber-300 rounded"
                      />
                      <span>days <span className="text-amber-700/80">(default 14)</span></span>
                    </label>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              onClick={() => extractFullMutation.mutate()}
              disabled={isLoading || !status?.databricks_connected || selectedGroups.length === 0}
              className="flex items-center gap-2 px-5 py-2.5 rounded-full bg-[var(--color-primary)] text-white font-medium text-sm
                hover:bg-[var(--color-primary-dark)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
            >
              {extractFullMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
              {extractFullMutation.isPending ? 'Extracting…' : 'Full Extract'}
            </button>
            <button
              onClick={() => extractIncrementalMutation.mutate()}
              disabled={isLoading || !status?.databricks_connected || selectedGroups.length === 0}
              className="flex items-center gap-2 px-5 py-2.5 rounded-full bg-emerald-600 text-white font-medium text-sm
                hover:bg-emerald-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
            >
              {extractIncrementalMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <PlusCircle size={16} />}
              {extractIncrementalMutation.isPending ? 'Extracting…' : 'Incremental Extract'}
            </button>
          </div>
          <p className="text-[11px] text-[var(--color-text-muted)] mt-2">
            Pulls the selected groups ({selectedGroups.length > 0 ? selectedGroups.join(', ') : 'none'}). <strong>Full</strong> overwrites the real-data partition for those tables; <strong>Incremental</strong> appends new rows since the last cursor (meta is always full-snapshot replaced — it's small). Each group writes its own dated parquet so downstream reads always pick the newest snapshot per table.
          </p>
          {selectedGroups.length === 0 && (
            <p className="text-xs text-[var(--color-warning)] flex items-center gap-1">
              <AlertTriangle size={12} />
              Pick at least one group to extract.
            </p>
          )}

          {!status?.databricks_connected && (
            <p className="text-xs text-[var(--color-warning)] flex items-center gap-1">
              <AlertTriangle size={12} />
              Databricks credentials not configured. Set DATABRICKS_HOST and DATABRICKS_TOKEN in docker-compose.yml.
            </p>
          )}

          {/* Live progress for the Extract pipeline. */}
          {progressFor(['extract']).map((p) => (
            <div key={p.kind} className="mt-3"><ProgressCard entry={p} /></div>
          ))}
        </div>
      </div>

      {/* LOAD — combined section. Two sub-sections inside:
            * Full load (replaces the partition wholesale)
            * Incremental load (appends new rows via the update_time cursor)
          Clear All Data is intentionally absent — the "Erase Data" section
          near the bottom is the canonical place for deletes. */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-[var(--color-text-primary)] mb-2 flex items-center gap-2">
          LOAD
          <InfoTooltip text="Toggle between demo data (from demo_*.parquet files — Acme Corp fakes mirroring real shape) and real Databricks data (parquet snapshot or live extraction). Full load replaces the partition; incremental load appends new rows by update_time cursor." />
        </h2>
        <p className="text-xs text-[var(--color-text-muted)] mb-4">
          Pick the partition (<code className="bg-gray-100 px-1 rounded">demo</code> or
          <code className="bg-gray-100 px-1 rounded">real</code>) and decide whether to
          rebuild it (<strong>full</strong>) or just append new rows
          (<strong>incremental</strong>).
        </p>

        {/* Full load */}
        <div className="mb-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 flex items-center gap-2">
            <RefreshCw size={12} /> Full load
            <InfoTooltip text="Replaces the partition wholesale. Use this on first run, after a schema change, or whenever you want a clean rebuild." />
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {/* Load Demo Data (full) */}
            <button
              onClick={() => seedMutation.mutate()}
              disabled={isLoading}
              className="flex flex-col items-center gap-2 p-4 rounded-xl border-2 border-[var(--color-border)]
                hover:border-[var(--color-primary)] hover:bg-blue-50 transition-all disabled:opacity-50"
            >
              {seedMutation.isPending ? (
                <Loader2 size={24} className="animate-spin text-[var(--color-primary)]" />
              ) : (
                <Sparkles size={24} className="text-purple-500" />
              )}
              <span className="text-sm font-medium text-[var(--color-text-primary)]">
                {seedMutation.isPending ? 'Loading...' : 'Load Demo Data (full)'}
              </span>
              <span className="text-xs text-[var(--color-text-muted)] text-center">
                ~30K sample records, 12 months
              </span>
            </button>

            {/* Load Real Data (Parquet) (full) */}
            <button
              onClick={() => ingestMutation.mutate()}
              disabled={isLoading}
              className="flex flex-col items-center gap-2 p-4 rounded-xl border-2 border-[var(--color-border)]
                hover:border-[var(--color-primary)] hover:bg-blue-50 transition-all disabled:opacity-50"
            >
              {ingestMutation.isPending ? (
                <Loader2 size={24} className="animate-spin text-[var(--color-primary)]" />
              ) : (
                <FileDown size={24} className="text-green-600" />
              )}
              <span className="text-sm font-medium text-[var(--color-text-primary)]">
                {ingestMutation.isPending ? 'Loading...' : 'Load Real Data (Parquet) (full)'}
              </span>
              <span className="text-xs text-[var(--color-text-muted)] text-center">
                From pre-extracted parquet files
              </span>
            </button>
          </div>
        </div>

        {/* Incremental load — same per-partition split, append-only via cursor. */}
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 flex items-center gap-2">
            <PlusCircle size={12} className="text-emerald-500" /> Incremental load
            <InfoTooltip text="Reads only rows newer than the per-table high-watermark cursor (update_time). Appends to the chosen partition; cursor advances on success. Skip the 50-min full reload when only new rows arrived. Runs as a background job." />
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <EraseButton label="Incremental demo" desc="Append new rows to data_origin='demo'" icon={<PlusCircle size={18} className="text-purple-500" />}
              onClick={() => opMutation.mutate(() => dataOps.incrementalLoad('demo'))}
              disabled={isLoading || opMutation.isPending} />
            <EraseButton label="Incremental real" desc="Append new rows to data_origin='real'" icon={<PlusCircle size={18} className="text-emerald-600" />}
              onClick={() => opMutation.mutate(() => dataOps.incrementalLoad('real'))}
              disabled={isLoading || opMutation.isPending} />
          </div>
        </div>

        {/* Live progress for the synchronous LOAD endpoints (seed-demo /
            ingest-parquet). Incremental load runs as a background job and
            shows up in the notifications bell instead. */}
        {progressFor(['seed-demo', 'ingest-parquet']).length > 0 && (
          <div className="mt-4 space-y-2">
            {progressFor(['seed-demo', 'ingest-parquet']).map((p) => (
              <ProgressCard key={p.kind} entry={p} />
            ))}
          </div>
        )}
      </div>

      {/* Transform — sits right under LOAD because the Run button operates on
          whatever LOAD just put on disk. Designed to grow as more transform
          stages land. */}
      <TransformSection
        queryIntelDemoMutation={queryIntelDemoMutation}
        queryIntelRealMutation={queryIntelRealMutation}
        lineageDemoMutation={lineageDemoMutation}
        lineageRealMutation={lineageRealMutation}
        progressEntries={progressFor([
          'query-intel-demo', 'query-intel-real',
          'transform-lineage-demo', 'transform-lineage-real',
        ])}
        qiResult={qiResult}
        lineageResult={lineageResult}
        disabled={isLoading}
      />

      {/* Query Engine — used to be 'Query Profiler Engine'. Same picker, broader
          framing now that Transform covers more than Query Profiler. */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-[var(--color-text-primary)] mb-2 flex items-center gap-2">
          <Cpu size={16} className="text-indigo-500" />
          Query Engine
          <InfoTooltip text="Selects where qi_* tables are stored and queried from. DuckDB writes to Postgres; Spark writes Delta tables to spark-warehouse via Spark Connect. Only one engine is active at a time. Takes effect on the next Transform > Run click and on subsequent Query Profiler / Chatbot reads." />
        </h2>
        <p className="text-xs text-[var(--color-text-muted)] mb-4">
          Pick the engine that backs Query Profiler and any downstream analytics.
          The change is persisted and visible to all Query Profiler pages and the Chatbot.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <button
            onClick={() => engineMutation.mutate({ engine: 'duckdb' })}
            disabled={engineMutation.isPending || engineQuery.isLoading}
            className={`flex flex-col items-start gap-1 p-4 rounded-xl border-2 transition-all
              ${engineQuery.data?.engine === 'duckdb'
                ? 'border-indigo-500 bg-indigo-50 ring-2 ring-indigo-200'
                : 'border-[var(--color-border)] hover:border-indigo-400'}`}
          >
            <div className="flex items-center gap-2">
              <Database size={18} className="text-indigo-500" />
              <span className="text-sm font-semibold text-[var(--color-text-primary)]">DuckDB</span>
              {engineQuery.data?.engine === 'duckdb' && (
                <span className="text-[10px] uppercase tracking-wide bg-indigo-600 text-white px-1.5 py-0.5 rounded">Active</span>
              )}
            </div>
            <p className="text-xs text-[var(--color-text-muted)] text-left">
              qi_* tables live in Postgres. Chatbot uses DuckDB with the Postgres extension ATTACH.
              Lightweight; recommended for &lt; 1 M statements.
            </p>
          </button>

          <button
            onClick={() => engineMutation.mutate({ engine: 'spark' })}
            disabled={engineMutation.isPending || engineQuery.isLoading}
            className={`flex flex-col items-start gap-1 p-4 rounded-xl border-2 transition-all
              ${engineQuery.data?.engine === 'spark'
                ? 'border-orange-500 bg-orange-50 ring-2 ring-orange-200'
                : 'border-[var(--color-border)] hover:border-orange-400'}`}
          >
            <div className="flex items-center gap-2">
              <Flame size={18} className="text-orange-500" />
              <span className="text-sm font-semibold text-[var(--color-text-primary)]">Spark</span>
              {engineQuery.data?.engine === 'spark' && (
                <span className="text-[10px] uppercase tracking-wide bg-orange-600 text-white px-1.5 py-0.5 rounded">Active</span>
              )}
            </div>
            <p className="text-xs text-[var(--color-text-muted)] text-left">
              qi_* tables are Delta tables under <code className="bg-gray-100 px-1 rounded">data/spark-warehouse</code>.
              Reads via Spark Connect (sc://spark-connect:15002). Use for larger volumes.
            </p>
          </button>
        </div>

        {/* Spark sub-mode — only shown when Spark is the active engine. The
            choice flips how every downstream surface (Spark SQL Editor + the
            Chatbot in Spark mode) references base tables. */}
        {engineQuery.data?.engine === 'spark' && (
          <div className="mt-4 border-t border-[var(--color-border)] pt-4 space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                Spark sub-mode
              </span>
              <InfoTooltip text="When Spark is active, choose how the Postgres-resident base tables (billing_usage, query_history, table_lineage, etc.) are exposed to Spark queries. Spark over Postgres uses JDBC temp views (light, references unqualified). Materialize copies the data into spark-warehouse as managed Delta tables (faster reads, references with the 3-part name)." />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button
                onClick={() => engineMutation.mutate({ engine: 'spark', spark_mode: 'jdbc_views' })}
                disabled={engineMutation.isPending}
                className={`flex flex-col items-start gap-1 p-4 rounded-xl border-2 transition-all
                  ${engineQuery.data?.spark_mode === 'jdbc_views'
                    ? 'border-sky-500 bg-sky-50 ring-2 ring-sky-200'
                    : 'border-[var(--color-border)] hover:border-sky-400'}`}
              >
                <div className="flex items-center gap-2">
                  <Database size={16} className="text-sky-500" />
                  <span className="text-sm font-semibold text-[var(--color-text-primary)]">Spark over Postgres</span>
                  {engineQuery.data?.spark_mode === 'jdbc_views' && (
                    <span className="text-[10px] uppercase tracking-wide bg-sky-600 text-white px-1.5 py-0.5 rounded">Active</span>
                  )}
                </div>
                <p className="text-xs text-[var(--color-text-muted)] text-left">
                  Base tables exposed as JDBC temp views — referenced unqualified
                  (e.g. <code className="bg-gray-100 px-1 rounded">SELECT * FROM table_lineage</code>).
                  Zero copy; every query round-trips to Postgres with predicate
                  / LIMIT pushdown enabled.
                </p>
              </button>

              <button
                onClick={() => {
                  if (engineQuery.data?.spark_mode !== 'materialized') {
                    if (!confirm(
                      'Materialize all Postgres base tables into spark-warehouse?\n\n' +
                      'This makes a one-time copy of billing_usage, query_history, table_lineage, etc., ' +
                      'as managed Delta tables in spark_catalog.default. Can take several minutes for ' +
                      'large lineage partitions. Existing Delta tables are overwritten.'
                    )) return;
                    materializeMutation.mutate();
                  } else {
                    // Already materialized — clicking does nothing; flipping back to
                    // jdbc_views happens via the other card.
                  }
                }}
                disabled={engineMutation.isPending || materializeMutation.isPending}
                className={`flex flex-col items-start gap-1 p-4 rounded-xl border-2 transition-all
                  ${engineQuery.data?.spark_mode === 'materialized'
                    ? 'border-emerald-500 bg-emerald-50 ring-2 ring-emerald-200'
                    : 'border-[var(--color-border)] hover:border-emerald-400'}`}
              >
                <div className="flex items-center gap-2">
                  <Flame size={16} className="text-emerald-500" />
                  <span className="text-sm font-semibold text-[var(--color-text-primary)]">Materialize Postgres data</span>
                  {engineQuery.data?.spark_mode === 'materialized' && (
                    <span className="text-[10px] uppercase tracking-wide bg-emerald-600 text-white px-1.5 py-0.5 rounded">Active</span>
                  )}
                  {materializeMutation.isPending && (
                    <Loader2 size={12} className="animate-spin text-emerald-600" />
                  )}
                </div>
                <p className="text-xs text-[var(--color-text-muted)] text-left">
                  Copy base tables into <code className="bg-gray-100 px-1 rounded">spark_catalog.default</code> as managed
                  Delta tables. References use the 3-part name. Trades disk +
                  copy time for zero-Postgres-round-trip reads.
                </p>
              </button>
            </div>

            {/* Live progress + post-run summary for materialize */}
            {progressFor(['materialize-postgres']).map((p) => (
              <div key={p.kind}><ProgressCard entry={p} /></div>
            ))}
            {materializeResult && (
              <div className="bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-3 text-xs text-emerald-900 space-y-1">
                <p className="font-medium">
                  Materialized {Object.keys(materializeResult.counts).length} table(s)
                  in {materializeResult.duration_seconds}s
                </p>
                <p className="font-mono">
                  {Object.entries(materializeResult.counts)
                    .map(([t, n]) => `${t}: ${n >= 0 ? n.toLocaleString() : 'FAILED'}`)
                    .join(' · ')}
                </p>
              </div>
            )}
          </div>
        )}

        {engineMutation.isPending && (
          <p className="text-xs text-[var(--color-text-muted)] mt-3">Switching engine…</p>
        )}
        {engineQuery.data && (
          <p className="text-xs text-[var(--color-text-muted)] mt-3">
            ⚠️ Switching engines does not move existing qi_* data. Open the <strong>Transform</strong>
            section and click <strong>Run</strong> after switching to populate the new engine's storage.
          </p>
        )}
      </div>

      {/* Erase data — soft / hard delete per origin */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-[var(--color-text-primary)] mb-2 flex items-center gap-2">
          <Trash2 size={16} className="text-red-500" />
          Erase Data
          <InfoTooltip text="Soft delete sets deleted_at on every row in the chosen partition; rows stop appearing in dashboards but stay on disk. Hard delete removes them physically. Demo and real partitions are independent." />
        </h2>
        <p className="text-xs text-[var(--color-text-muted)] mb-4">
          Per-origin delete. Demo never touches real and vice versa. All four buttons run as background jobs visible in the notifications bell.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <EraseButton label="Soft delete demo" desc="Mark demo rows as deleted_at = NOW" icon={<Trash2 size={18} className="text-yellow-500" />}
            onClick={() => confirmAndRun('Soft delete ALL demo rows?', () => dataOps.softDelete('demo'))}
            disabled={isLoading || opMutation.isPending} />
          <EraseButton label="Hard delete demo" desc="DELETE FROM ... WHERE data_origin='demo'" icon={<Trash2 size={18} className="text-red-500" />}
            onClick={() => confirmAndRun('Hard delete ALL demo rows? This cannot be undone.', () => dataOps.hardDelete('demo'))}
            disabled={isLoading || opMutation.isPending} />
          <EraseButton label="Soft delete real" desc="Mark real rows as deleted_at = NOW" icon={<Trash2 size={18} className="text-yellow-600" />}
            onClick={() => confirmAndRun('Soft delete ALL real rows? Dashboards will go blank until you Restore.', () => dataOps.softDelete('real'))}
            disabled={isLoading || opMutation.isPending} />
          <EraseButton label="Hard delete real" desc="DELETE FROM ... WHERE data_origin='real'" icon={<Trash2 size={18} className="text-red-700" />}
            onClick={() => confirmAndRun('Hard delete ALL real rows? This cannot be undone.', () => dataOps.hardDelete('real'))}
            disabled={isLoading || opMutation.isPending} />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
          <EraseButton label="Restore demo" desc="Clear deleted_at on demo rows" icon={<RotateCcw size={18} className="text-emerald-500" />}
            onClick={() => confirmAndRun('Restore all soft-deleted demo rows?', () => dataOps.restore('demo'))}
            disabled={isLoading || opMutation.isPending} />
          <EraseButton label="Restore real" desc="Clear deleted_at on real rows" icon={<RotateCcw size={18} className="text-emerald-600" />}
            onClick={() => confirmAndRun('Restore all soft-deleted real rows?', () => dataOps.restore('real'))}
            disabled={isLoading || opMutation.isPending} />
        </div>
      </div>

      {/* Refresh All Data */}
      <div className="flex justify-center">
        <button
          onClick={() => refreshAfterDataChange()}
          className="flex items-center gap-2 px-4 py-2 text-sm text-[var(--color-text-muted)] hover:text-[var(--color-primary)] transition-colors"
        >
          <RefreshCw size={14} />
          Refresh dashboard data
        </button>
      </div>

      {/* Result/Error Display */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-2xl px-4 py-3 flex items-start gap-3">
          <XCircle size={18} className="text-red-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-red-700">Operation Failed</p>
            <p className="text-xs text-red-600 mt-1">{error}</p>
          </div>
        </div>
      )}

      {result && (
        <div className="bg-green-50 border border-green-200 rounded-2xl px-4 py-3 flex items-start gap-3">
          <CheckCircle2 size={18} className="text-green-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-green-700">
              {'tables_extracted' in result ? 'Extraction' : 'Ingestion'} Complete
              <span className="font-normal text-green-600 ml-2">
                ({result.duration_seconds}s)
              </span>
            </p>
            <div className="mt-2 space-y-1">
              {'tables_extracted' in result && (
                <p className="text-xs text-green-600">
                  Extracted: {Object.entries((result as ExtractionResult).tables_extracted)
                    .map(([k, v]) => `${k}: ${numberFmt.format(v)}`)
                    .join(', ')}
                </p>
              )}
              <p className="text-xs text-green-600">
                Ingested: {Object.entries(result.tables_ingested)
                  .map(([k, v]) => `${k}: ${numberFmt.format(v)}`)
                  .join(', ')}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Transform section — a checklist of derived-table refreshes that share one
// trigger. Today only Query Profiler is wired; lineage entries are reserved
// for the upcoming downstream enrichment passes over table_lineage and
// column_lineage.
// ---------------------------------------------------------------------------

type TransformTaskKey =
  | 'query_profiler_real'
  | 'query_profiler_demo'
  | 'lineage_real'
  | 'lineage_demo';

interface TransformTask {
  key: TransformTaskKey;
  label: string;
  description: string;
  // 'wired' tasks can be run from this UI; 'planned' tasks are surfaced as
  // disabled to telegraph the upcoming pipeline shape without lying about it.
  status: 'wired' | 'planned';
}

const TRANSFORM_TASKS: TransformTask[] = [
  {
    key: 'query_profiler_real',
    label: 'Query Profiler (real)',
    description: 'Parse query_history (real) with sqlglot, rebuild qi_* tables.',
    status: 'wired',
  },
  {
    key: 'query_profiler_demo',
    label: 'Query Profiler (demo)',
    description: 'Parse demo_query_history with sqlglot, rebuild qi_* tables.',
    status: 'wired',
  },
  {
    key: 'lineage_real',
    label: 'Lineage rollups (real)',
    description: 'Aggregate table_lineage (real) into lineage_rollups for fast dashboard tiles.',
    status: 'wired',
  },
  {
    key: 'lineage_demo',
    label: 'Lineage rollups (demo)',
    description: 'Aggregate demo_table_lineage into lineage_rollups for fast dashboard tiles.',
    status: 'wired',
  },
];

function TransformSection({
  queryIntelDemoMutation,
  queryIntelRealMutation,
  lineageDemoMutation,
  lineageRealMutation,
  qiResult,
  lineageResult,
  progressEntries,
  disabled,
}: {
  queryIntelDemoMutation: { mutate: () => void; isPending: boolean };
  queryIntelRealMutation: { mutate: () => void; isPending: boolean };
  lineageDemoMutation:   { mutate: () => void; isPending: boolean };
  lineageRealMutation:   { mutate: () => void; isPending: boolean };
  qiResult: QueryIntelResult | null;
  lineageResult: LineageRollupResult | null;
  progressEntries: ProgressEntry[];
  disabled: boolean;
}) {
  // Every task is unchecked by default — Run is a deliberate fan-out, not a
  // one-click "do everything I might want." Users opt in per task.
  const [selected, setSelected] = useState<Set<TransformTaskKey>>(() => new Set());
  const toggle = (k: TransformTaskKey) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(k) ? next.delete(k) : next.add(k);
      return next;
    });
  };

  const wiredSelected = [...selected].filter((k) =>
    TRANSFORM_TASKS.find((t) => t.key === k)?.status === 'wired'
  ) as TransformTaskKey[];
  const plannedSelected = [...selected].filter((k) =>
    TRANSFORM_TASKS.find((t) => t.key === k)?.status === 'planned'
  );

  const anyPending = queryIntelDemoMutation.isPending || queryIntelRealMutation.isPending
    || lineageDemoMutation.isPending || lineageRealMutation.isPending;
  const canRun = wiredSelected.length > 0 && !anyPending && !disabled;

  const runTransform = () => {
    // Fire each selected, wired task. All four endpoints are independent so
    // running in parallel is fine; we don't await them here either, since
    // each mutation owns its own progress display.
    if (selected.has('query_profiler_real')) queryIntelRealMutation.mutate();
    if (selected.has('query_profiler_demo')) queryIntelDemoMutation.mutate();
    if (selected.has('lineage_real')) lineageRealMutation.mutate();
    if (selected.has('lineage_demo')) lineageDemoMutation.mutate();
  };

  return (
    <div className="bg-white border border-[var(--color-border)] rounded-2xl p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-[var(--color-text-primary)] mb-2 flex items-center gap-2">
        <Brain size={16} className="text-purple-500" />
        Transform
        <InfoTooltip text="Derived-table refreshes. Each task transforms raw parquet/Postgres data into analysis-ready tables. Tasks are independent and idempotent — pick what you want and click Run." />
      </h2>
      <p className="text-xs text-[var(--color-text-muted)] mb-4">
        Pick the transforms to (re)run, then click <strong>Run</strong>. All tasks
        are idempotent — safe to re-run any time the underlying source changes.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {TRANSFORM_TASKS.map((t) => {
          const checked = selected.has(t.key);
          const isPlanned = t.status === 'planned';
          return (
            <label
              key={t.key}
              className={`flex items-start gap-2 border rounded-lg px-3 py-2 transition-colors ${
                isPlanned
                  ? 'border-[var(--color-border)] bg-gray-50 cursor-not-allowed opacity-70'
                  : checked
                  ? 'border-purple-500 bg-purple-50 cursor-pointer'
                  : 'border-[var(--color-border)] bg-white hover:bg-purple-50/50 cursor-pointer'
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                disabled={isPlanned}
                onChange={() => toggle(t.key)}
                className="mt-0.5 rounded"
              />
              <span className="flex-1 min-w-0">
                <span className="flex items-center gap-2">
                  <span className="text-sm font-medium text-[var(--color-text-primary)]">{t.label}</span>
                  {isPlanned && (
                    <span className="text-[10px] uppercase tracking-wide bg-gray-200 text-gray-600 px-1.5 py-0.5 rounded">
                      Planned
                    </span>
                  )}
                </span>
                <span className="block text-[11px] text-[var(--color-text-muted)] mt-0.5 leading-snug">
                  {t.description}
                </span>
              </span>
            </label>
          );
        })}
      </div>

      <div className="mt-4 flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={runTransform}
          disabled={!canRun}
          className="flex items-center gap-2 px-5 py-2.5 rounded-full bg-purple-600 text-white font-medium text-sm
            hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
        >
          {anyPending ? <Loader2 size={16} className="animate-spin" /> : <Brain size={16} />}
          {anyPending ? 'Running…' : 'Run'}
        </button>
        <span className="text-xs text-[var(--color-text-muted)]">
          {wiredSelected.length} runnable · {plannedSelected.length} planned · {selected.size} selected
        </span>
      </div>

      {/* Live progress for whichever Transform tasks are running (or recently
          finished). One card per task — they run in parallel. */}
      {progressEntries.length > 0 && (
        <div className="mt-4 space-y-2">
          {progressEntries.map((p) => <ProgressCard key={p.kind} entry={p} />)}
        </div>
      )}

      {qiResult && (
        <div className="mt-4 bg-purple-50 border border-purple-200 rounded-xl px-4 py-3 text-xs text-purple-800 space-y-1">
          <p className="font-medium">
            Extracted from <code>{qiResult.source_file}</code> in {qiResult.duration_seconds}s
          </p>
          <p>
            {numberFmt.format(qiResult.statements_inserted)} statements ·{' '}
            {numberFmt.format(qiResult.tables_extracted)} table refs ·{' '}
            {numberFmt.format(qiResult.columns_extracted)} column refs ·{' '}
            {numberFmt.format(qiResult.errors_extracted)} errors ·{' '}
            {numberFmt.format(qiResult.parse_failures)} parse failures
          </p>
        </div>
      )}

      {lineageResult && (
        <div className="mt-3 bg-fuchsia-50 border border-fuchsia-200 rounded-xl px-4 py-3 text-xs text-fuchsia-900 space-y-1">
          <p className="font-medium">
            Lineage rollups rebuilt for <code>data_origin = {lineageResult.data_origin}</code>{' '}
            in {lineageResult.duration_seconds}s
          </p>
          <p>
            {numberFmt.format(lineageResult.rollup_rows)} rollup rows ·{' '}
            {numberFmt.format(lineageResult.table_edges)} table edges ·{' '}
            {numberFmt.format(lineageResult.column_edges)} column edges ·{' '}
            {numberFmt.format(lineageResult.direct_edges)} direct ·{' '}
            {numberFmt.format(lineageResult.indirect_edges)} indirect ·{' '}
            {numberFmt.format(lineageResult.distinct_entities)} entities
            {lineageResult.last_event && (
              <> · last event {lineageResult.last_event}</>
            )}
          </p>
        </div>
      )}
    </div>
  );
}


function EraseButton({ label, desc, icon, onClick, disabled }: {
  label: string;
  desc: string;
  icon: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex items-start gap-3 p-3 rounded-xl border border-[var(--color-border)] hover:border-[var(--color-primary)] hover:bg-blue-50 transition-all disabled:opacity-50 text-left"
    >
      <span className="mt-0.5">{icon}</span>
      <span className="flex-1">
        <span className="block text-sm font-medium text-[var(--color-text-primary)]">{label}</span>
        <span className="block text-[11px] text-[var(--color-text-muted)] font-mono">{desc}</span>
      </span>
    </button>
  );
}
