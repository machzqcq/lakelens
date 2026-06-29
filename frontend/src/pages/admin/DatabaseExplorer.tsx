import { useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  DatabaseZap, Play, Loader2, AlertCircle, Table2, Eye, ChevronRight,
  ChevronDown, ArrowUp, ArrowDown, Search,
} from 'lucide-react';
import {
  type DbObject,
  type DbQueryResult,
  dbListObjects,
  dbRunQuery,
} from '../../api/client';

const DEFAULT_SQL = 'SELECT * FROM billing_usage LIMIT 100';

export default function DatabaseExplorer() {
  const objectsQ = useQuery({ queryKey: ['db-objects'], queryFn: dbListObjects });
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [result, setResult] = useState<DbQueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runMut = useMutation({
    mutationFn: (q: string) => dbRunQuery(q),
    onSuccess: (r) => { setResult(r); setError(null); },
    onError: (e: Error) => { setError(e.message); setResult(null); },
  });

  function run() {
    if (sql.trim()) runMut.mutate(sql);
  }

  function onPickObject(o: DbObject) {
    setSql(`SELECT * FROM ${o.schema_name}.${o.name} LIMIT 100`);
  }

  const objects = objectsQ.data ?? [];
  const bySchema = useMemo(() => {
    const m = new Map<string, DbObject[]>();
    for (const o of objects) {
      if (!m.has(o.schema_name)) m.set(o.schema_name, []);
      m.get(o.schema_name)!.push(o);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [objects]);

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <DatabaseZap size={24} className="text-[var(--color-primary)]" />
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Database Explorer</h1>
        <span className="text-[10px] font-semibold uppercase rounded-full px-2 py-0.5 bg-gray-200 text-gray-700">admin · read-only</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-5">
        {/* Catalog */}
        <div className="bg-white border border-[var(--color-border)] rounded-2xl overflow-hidden h-fit max-h-[80vh] flex flex-col">
          <div className="px-4 py-3 border-b border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
            <p className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              Schema objects {objects.length > 0 && `(${objects.length})`}
            </p>
          </div>
          <div className="overflow-y-auto p-2">
            {objectsQ.isLoading ? (
              <p className="text-xs text-[var(--color-text-muted)] p-2">Loading…</p>
            ) : bySchema.length === 0 ? (
              <p className="text-xs text-[var(--color-text-muted)] p-2">No objects found.</p>
            ) : (
              bySchema.map(([schema, objs]) => (
                <SchemaGroup key={schema} schema={schema} objects={objs} onPick={onPickObject} />
              ))
            )}
          </div>
        </div>

        {/* Editor + results */}
        <div className="space-y-4 min-w-0">
          <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4 space-y-3">
            <textarea
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); } }}
              spellCheck={false}
              rows={5}
              className="w-full bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm font-mono text-[var(--color-text-primary)] resize-y"
              placeholder="SELECT … (read-only; single statement)"
            />
            <div className="flex items-center justify-between gap-3">
              <p className="text-[10px] text-[var(--color-text-muted)]">
                SELECT / WITH only · max 1000 rows · 15s timeout · <kbd className="font-mono">Ctrl/⌘+Enter</kbd> to run
              </p>
              <button onClick={run} disabled={runMut.isPending}
                className="flex items-center gap-2 px-4 py-1.5 rounded-lg bg-[var(--color-primary)] text-white text-sm disabled:opacity-50">
                {runMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                Run
              </button>
            </div>
          </div>

          {error && (
            <div className="flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
              <AlertCircle size={14} className="shrink-0 mt-0.5" /><span className="font-mono">{error}</span>
            </div>
          )}

          {result && <ResultsTable result={result} />}
        </div>
      </div>
    </div>
  );
}

function SchemaGroup({
  schema, objects, onPick,
}: { schema: string; objects: DbObject[]; onPick: (o: DbObject) => void }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="mb-1">
      <button onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-1.5 px-2 py-1.5 text-xs font-semibold text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] rounded">
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span className="font-mono">{schema}</span>
        <span className="text-[10px] font-normal text-[var(--color-text-muted)]">({objects.length})</span>
      </button>
      {open && (
        <div className="pl-2">
          {objects.map((o) => (
            <button key={`${o.schema_name}.${o.name}`} onClick={() => onPick(o)}
              title={`${o.columns.length} columns · ~${o.approx_rows.toLocaleString()} rows\n${o.columns.map((c) => `${c.name} ${c.type}`).join('\n')}`}
              className="w-full flex items-center gap-2 px-2 py-1 text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] rounded text-left">
              {o.kind === 'view'
                ? <Eye size={12} className="shrink-0 text-[var(--color-text-muted)]" />
                : <Table2 size={12} className="shrink-0 text-[var(--color-text-muted)]" />}
              <span className="font-mono truncate">{o.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

type SortDir = 'asc' | 'desc';

function ResultsTable({ result }: { result: DbQueryResult }) {
  const { columns, rows } = result;
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [filters, setFilters] = useState<Record<string, string>>({});

  function toggleSort(col: string) {
    if (sortCol === col) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortCol(col); setSortDir('asc'); }
  }

  const view = useMemo(() => {
    let r = rows;
    const active = Object.entries(filters).filter(([, v]) => v.trim() !== '');
    if (active.length) {
      r = r.filter((row) =>
        active.every(([col, q]) =>
          String(row[col] ?? '').toLowerCase().includes(q.toLowerCase())
        )
      );
    }
    if (sortCol) {
      r = [...r].sort((a, b) => {
        const av = a[sortCol], bv = b[sortCol];
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        const an = typeof av === 'number' ? av : Number(av);
        const bn = typeof bv === 'number' ? bv : Number(bv);
        let cmp: number;
        if (!Number.isNaN(an) && !Number.isNaN(bn) && av !== '' && bv !== '') {
          cmp = an - bn;
        } else {
          cmp = String(av).localeCompare(String(bv));
        }
        return sortDir === 'asc' ? cmp : -cmp;
      });
    }
    return r;
  }, [rows, filters, sortCol, sortDir]);

  return (
    <div className="bg-white border border-[var(--color-border)] rounded-2xl overflow-hidden">
      <div className="px-4 py-2.5 border-b border-[var(--color-border)] bg-[var(--color-bg-secondary)] flex items-center justify-between gap-3 text-xs text-[var(--color-text-muted)]">
        <span>
          {view.length.toLocaleString()} / {result.row_count.toLocaleString()} row{result.row_count === 1 ? '' : 's'}
          {result.truncated && <span className="text-amber-600"> · truncated to 1000</span>}
        </span>
        <span>{result.elapsed_ms} ms</span>
      </div>
      <div className="overflow-auto max-h-[60vh]">
        <table className="w-full text-xs">
          <thead className="bg-[var(--color-bg-secondary)] sticky top-0 z-10">
            <tr>
              {columns.map((c) => (
                <th key={c} className="px-3 py-2 text-left font-semibold text-[var(--color-text-muted)] whitespace-nowrap border-b border-[var(--color-border)]">
                  <button onClick={() => toggleSort(c)} className="flex items-center gap-1 hover:text-[var(--color-primary)]">
                    {c}
                    {sortCol === c && (sortDir === 'asc' ? <ArrowUp size={11} /> : <ArrowDown size={11} />)}
                  </button>
                </th>
              ))}
            </tr>
            <tr>
              {columns.map((c) => (
                <th key={c} className="px-2 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
                  <div className="flex items-center gap-1 bg-white border border-[var(--color-border)] rounded px-1.5 py-0.5">
                    <Search size={10} className="text-[var(--color-text-muted)] shrink-0" />
                    <input
                      value={filters[c] ?? ''}
                      onChange={(e) => setFilters((f) => ({ ...f, [c]: e.target.value }))}
                      placeholder="filter"
                      className="w-full min-w-[60px] text-[11px] font-normal outline-none bg-transparent text-[var(--color-text-primary)]"
                    />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.map((row, i) => (
              <tr key={i} className="border-t border-[var(--color-border)]/50 hover:bg-[var(--color-bg-secondary)]/50">
                {columns.map((c) => (
                  <td key={c} className="px-3 py-1.5 font-mono text-[var(--color-text-secondary)] whitespace-nowrap max-w-[420px] truncate" title={String(row[c] ?? '')}>
                    {row[c] == null ? <span className="text-[var(--color-text-muted)] italic">null</span> : String(row[c])}
                  </td>
                ))}
              </tr>
            ))}
            {view.length === 0 && (
              <tr><td colSpan={columns.length} className="px-4 py-8 text-center text-xs text-[var(--color-text-muted)]">No rows match the column filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
