/**
 * Admin-only Spark SQL editor. Two-pane layout:
 *   Left  — table catalog (spark_catalog.default), click to drop a SELECT *
 *           into the editor; hover for the column schema.
 *   Right — SQL textarea + Run + Result grid.
 *
 * Routed at /spark-sql. Talks to /api/spark-sql/{session,tables,query}.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Database, Play, Flame, RefreshCw, AlertCircle, Loader2, CheckCircle2, ChevronRight, ChevronDown } from 'lucide-react';
import { sparkSql, type SparkTable, type SparkQueryResponse } from '../../api/client';
import InfoTooltip from '../../components/InfoTooltip';

const DEFAULT_SQL = `-- Spark SQL editor — runs against spark_catalog.default via Spark Connect.
-- Pick a table from the left to drop a starter query.
-- Note: tables tagged [temp] are JDBC-backed temp views (billing_usage,
-- query_history, table_lineage, ...). They are session-scoped and must be
-- referenced UNQUALIFIED — \`SELECT * FROM table_lineage\`, NOT
-- \`spark_catalog.default.table_lineage\`.
SHOW TABLES IN spark_catalog.default;
-- SHOW VIEWS;  -- uncomment to see temp views too`;

export default function SparkSqlEditor() {
  const [sql, setSql] = useState<string>(DEFAULT_SQL);
  const [result, setResult] = useState<SparkQueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  const sessionQ = useQuery({ queryKey: ['spark-session'], queryFn: sparkSql.session });
  const tablesQ  = useQuery({
    queryKey: ['spark-tables'],
    queryFn:  sparkSql.tables,
    enabled:  !!sessionQ.data?.reachable,
  });

  const runMutation = useMutation({
    mutationFn: (q: string) => sparkSql.query(q, 1000),
    onSuccess: (data) => { setResult(data); setError(null); },
    onError: (e: Error) => { setResult(null); setError(e.message); },
  });

  const onRun = () => {
    const q = sql.trim();
    if (!q) return;
    runMutation.mutate(q);
  };

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); onRun(); }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [sql]);

  const onPickTable = (t: SparkTable) => {
    // Temp views (JDBC-backed billing/query_history/lineage/etc. registered
    // by backend/spark_session.py:_register_base_jdbc_views) are session-
    // scoped — they're NOT in spark_catalog.default, so a fully-qualified
    // SELECT would fail with TABLE_OR_VIEW_NOT_FOUND. Use the unqualified
    // name for temp views; only real managed/external/view objects in
    // spark_catalog.default get the three-part name.
    const isTemp = (t.kind || '').toUpperCase() === 'TEMPORARY';
    const ref = isTemp ? t.name : `${t.catalog}.${t.database}.${t.name}`;
    setSql(`SELECT * FROM ${ref} LIMIT 100;`);
    taRef.current?.focus();
  };

  return (
    <div className="space-y-4 max-w-[1400px]">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
            <Flame size={22} className="text-orange-500" />
            Spark SQL Editor
            <InfoTooltip text="Ad-hoc SQL against the spark-warehouse via Spark Connect (sc://spark-connect:15002). Read-only: SELECT / WITH / SHOW / DESCRIBE only. Capped at 1,000 rows." />
          </h1>
          <p className="text-xs text-[var(--color-text-muted)] mt-1">
            Read-only ad-hoc queries against <code className="bg-gray-100 px-1 rounded">spark_catalog.default</code> (Delta tables in <code className="bg-gray-100 px-1 rounded">data/spark-warehouse</code>).
          </p>
        </div>
        <SessionBadge sessionQ={sessionQ} />
      </div>

      <div className="grid grid-cols-12 gap-4">
        {/* Table catalog */}
        <div className="col-span-12 lg:col-span-3 bg-white border border-[var(--color-border)] rounded-2xl p-3 shadow-sm h-[600px] overflow-auto">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-semibold text-[var(--color-text-secondary)] flex items-center gap-1">
              <Database size={14} /> Tables
            </h2>
            <button
              onClick={() => tablesQ.refetch()}
              className="p-1 rounded hover:bg-[var(--color-bg-secondary)]"
              title="Refresh"
            >
              <RefreshCw size={12} className={tablesQ.isFetching ? 'animate-spin' : ''} />
            </button>
          </div>
          {!sessionQ.data?.reachable ? (
            <p className="text-xs text-[var(--color-text-muted)]">
              Spark Connect is unreachable — table list unavailable.
            </p>
          ) : tablesQ.isLoading ? (
            <p className="text-xs text-[var(--color-text-muted)]">Loading…</p>
          ) : (tablesQ.data ?? []).length === 0 ? (
            <p className="text-xs text-[var(--color-text-muted)]">
              No tables yet in <code>spark_catalog.default</code>. Click <strong>Extract query profiler</strong> with engine=spark to populate it.
            </p>
          ) : (
            <ul className="space-y-0.5">
              {(tablesQ.data ?? []).map((t) => (
                <TableRow key={t.name} table={t} onPick={() => onPickTable(t)} />
              ))}
            </ul>
          )}
        </div>

        {/* Editor + results */}
        <div className="col-span-12 lg:col-span-9 space-y-3">
          <div className="bg-white border border-[var(--color-border)] rounded-2xl p-3 shadow-sm">
            <textarea
              ref={taRef}
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              className="w-full h-44 p-3 font-mono text-xs bg-[#0d1117] text-[#c9d1d9] rounded-lg outline-none focus:ring-2 focus:ring-orange-300 leading-relaxed"
              placeholder="-- write Spark SQL here"
              spellCheck={false}
            />
            <div className="flex items-center justify-between mt-3">
              <p className="text-[10px] text-[var(--color-text-muted)]">
                ⌘/Ctrl + Enter to run. Capped at 1,000 rows. Spark engine reachable: <strong>{sessionQ.data?.reachable ? 'yes' : 'no'}</strong>.
              </p>
              <button
                onClick={onRun}
                disabled={runMutation.isPending || !sessionQ.data?.reachable}
                className="flex items-center gap-2 px-4 py-1.5 rounded-full bg-orange-500 text-white text-sm font-medium hover:bg-orange-600 transition-colors disabled:opacity-50"
              >
                {runMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                {runMutation.isPending ? 'Running…' : 'Run'}
              </button>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-xl px-3 py-2 flex items-start gap-2">
              <AlertCircle size={14} className="text-red-600 mt-0.5 shrink-0" />
              <div>
                <p className="text-xs font-semibold text-red-700">Query failed</p>
                <p className="text-xs text-red-700 whitespace-pre-wrap leading-relaxed mt-0.5">{error}</p>
              </div>
            </div>
          )}

          {/* Result table */}
          {result && (
            <div className="bg-white border border-[var(--color-border)] rounded-2xl p-3 shadow-sm">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-[var(--color-text-muted)]">
                  {result.row_count} row{result.row_count !== 1 ? 's' : ''}
                  {result.truncated ? ' (truncated — showing first 1,000)' : ''} ·{' '}
                  {result.elapsed_ms} ms
                </span>
              </div>
              <ResultGrid columns={result.columns} rows={result.rows} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


function SessionBadge({ sessionQ }: { sessionQ: ReturnType<typeof useQuery<typeof sparkSql.session extends () => Promise<infer T> ? T : never, Error>> }) {
  const s = sessionQ.data;
  if (sessionQ.isLoading) return <span className="text-xs text-[var(--color-text-muted)]">Probing Spark Connect…</span>;
  if (!s?.reachable) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-red-50 border border-red-200 text-xs text-red-700">
        <AlertCircle size={12} /> Spark Connect unreachable
        <span className="font-mono text-[10px]">{s?.remote}</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 border border-emerald-200 text-xs text-emerald-700">
      <CheckCircle2 size={12} /> Spark {s.spark_version ?? '?'}
      <span className="text-emerald-600 font-mono text-[10px]">{s.remote}</span>
    </div>
  );
}


function TableRow({ table, onPick }: { table: SparkTable; onPick: () => void }) {
  const [open, setOpen] = useState(false);
  const isTemp = (table.kind || '').toUpperCase() === 'TEMPORARY';
  // Tooltip shows the fully-qualified path for real catalog tables but the
  // unqualified name for temp views, matching what onPickTable drops.
  const fqTitle = isTemp
    ? `${table.name}  (JDBC temp view — reference unqualified)`
    : `${table.catalog}.${table.database}.${table.name}`;
  return (
    <li>
      <div className="flex items-center gap-1 group">
        <button
          onClick={() => setOpen((o) => !o)}
          className="p-0.5 rounded hover:bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)]"
          title="Expand columns"
        >
          {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        </button>
        <button
          onClick={onPick}
          className="flex-1 text-left px-1.5 py-1 text-xs rounded hover:bg-orange-50 text-[var(--color-text-primary)] truncate flex items-center gap-1"
          title={fqTitle}
        >
          <span className="truncate">{table.name}</span>
          {isTemp && (
            <span
              className="shrink-0 text-[9px] uppercase tracking-wide bg-sky-100 text-sky-700 px-1 py-px rounded"
              title="JDBC-backed temp view — reference unqualified."
            >
              temp
            </span>
          )}
        </button>
      </div>
      {open && (
        <ul className="ml-5 mt-0.5 mb-1 space-y-0.5">
          {table.columns.map((c) => (
            <li key={c.name} className="text-[10px] text-[var(--color-text-muted)] font-mono leading-snug">
              <span className="text-[var(--color-text-secondary)]">{c.name}</span>{' '}
              <span className="text-[var(--color-text-muted)]">: {c.type}</span>
              {!c.nullable && <span className="text-amber-600 ml-1">NN</span>}
            </li>
          ))}
          {table.columns.length === 0 && (
            <li className="text-[10px] text-[var(--color-text-muted)] italic">no schema</li>
          )}
        </ul>
      )}
    </li>
  );
}


function ResultGrid({ columns, rows }: { columns: string[]; rows: Record<string, any>[] }) {
  if (rows.length === 0) {
    return <p className="text-xs text-[var(--color-text-muted)] py-6 text-center">No rows.</p>;
  }
  const cells = useMemo(() => rows.slice(0, 200), [rows]);
  return (
    <div className="overflow-auto max-h-[440px]">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-[var(--color-bg-secondary)]">
          <tr>
            {columns.map((c) => (
              <th key={c} className="text-left px-2 py-1.5 font-semibold text-[var(--color-text-secondary)] border-b border-[var(--color-border)] whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cells.map((r, i) => (
            <tr key={i} className="hover:bg-[var(--color-bg-secondary)]">
              {columns.map((c) => (
                <td key={c} className="px-2 py-1 border-b border-[var(--color-border)]/30 font-mono text-[11px] truncate max-w-[280px]" title={String(r[c] ?? '')}>
                  {r[c] === null || r[c] === undefined
                    ? <span className="text-[var(--color-text-muted)] italic">null</span>
                    : typeof r[c] === 'object'
                      ? JSON.stringify(r[c])
                      : String(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
