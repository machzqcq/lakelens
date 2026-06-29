/**
 * Meta Explorer — three-pane Unity Catalog browser over the `databricks_meta`
 * Postgres table. Left = catalog/database tree, middle = table list for the
 * selected database, right = column schema for the selected table. Search
 * bar at the top searches across table names, column names, and comments.
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BookOpen, Database, Search, ChevronRight, ChevronDown, Table2, User, FileText,
  Loader2, Calendar, Layers, Download,
} from 'lucide-react';
import { metaExplorer, type TableRow as MetaTableRow, type SearchHit } from '../api/client';
import InfoTooltip from '../components/InfoTooltip';
import KpiCard from '../components/KpiCard';
import { exportToCsv, exportToXlsx, type ExportRow } from '../utils/export';

const numberFmt = new Intl.NumberFormat('en-US');

export default function MetaExplorer() {
  const [selectedCatalog, setSelectedCatalog] = useState<string | null>(null);
  const [selectedDatabase, setSelectedDatabase] = useState<string | null>(null);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [activeSearch, setActiveSearch] = useState('');

  const statsQ = useQuery({ queryKey: ['meta-stats'], queryFn: metaExplorer.stats });
  const catalogsQ = useQuery({ queryKey: ['meta-catalogs'], queryFn: metaExplorer.catalogs });
  const databasesQ = useQuery({
    queryKey: ['meta-databases', selectedCatalog],
    queryFn: () => metaExplorer.databases(selectedCatalog!),
    enabled: !!selectedCatalog,
  });
  const tablesQ = useQuery({
    queryKey: ['meta-tables', selectedCatalog, selectedDatabase],
    queryFn: () => metaExplorer.tables(selectedCatalog!, selectedDatabase!),
    enabled: !!selectedCatalog && !!selectedDatabase,
  });
  const tableDetailQ = useQuery({
    queryKey: ['meta-table-detail', selectedCatalog, selectedDatabase, selectedTable],
    queryFn: () => metaExplorer.tableDetail(selectedCatalog!, selectedDatabase!, selectedTable!),
    enabled: !!selectedCatalog && !!selectedDatabase && !!selectedTable,
  });
  const searchQ = useQuery({
    queryKey: ['meta-search', activeSearch],
    queryFn: () => metaExplorer.search(activeSearch),
    enabled: activeSearch.length >= 2,
  });

  const stats = statsQ.data;
  const hasData = (stats?.tables ?? 0) > 0;

  return (
    <div className="space-y-6 max-w-[1500px]">
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
          <BookOpen size={22} className="text-cyan-600" />
          Meta Explorer
          <InfoTooltip text="Browse the Unity Catalog metadata snapshot extracted from Databricks INFORMATION_SCHEMA. One row per (catalog, database, table, column) with type, comment, owner. Refresh via Data Management → Extract from Databricks." />
        </h1>
        <p className="text-sm text-[var(--color-text-muted)] mt-1">
          Every accessible catalog, database, table, and column at a point in time.
          {stats?.last_extract && (
            <span className="ml-2">Last extracted: <strong>{stats.last_extract}</strong></span>
          )}
        </p>
      </div>

      {/* Bulk export — Catalogs / Tables / Columns. Tables carry catalog+database;
          Columns carry catalog+database+table+col so each export stands alone. */}
      <ExportToolbar disabled={!hasData} />

      {/* KPI tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard title="Catalogs" value={numberFmt.format(stats?.catalogs ?? 0)}
          icon={<Layers size={18} />} tooltip="Distinct catalogs in spark_catalog (SHOW CATALOGS)." accentColor="#06b6d4" />
        <KpiCard title="Databases" value={numberFmt.format(stats?.databases ?? 0)}
          icon={<Database size={18} />} tooltip="Schemas across all catalogs." accentColor="#3b82f6" />
        <KpiCard title="Tables" value={numberFmt.format(stats?.tables ?? 0)}
          icon={<Table2 size={18} />} tooltip="Unique table_type rows (MANAGED + EXTERNAL + VIEW)." accentColor="#8b5cf6" />
        <KpiCard title="Columns" value={numberFmt.format(stats?.columns ?? 0)}
          icon={<FileText size={18} />} tooltip="Total column-level rows in databricks_meta." accentColor="#10b981" />
      </div>

      {!hasData && !statsQ.isLoading && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3">
          <p className="text-sm font-medium text-yellow-800">No metadata snapshot yet.</p>
          <p className="text-xs text-yellow-700 mt-1">
            Go to <strong>Data Management → Extract from Databricks</strong> (full or incremental) to populate <code>databricks_meta</code>.
          </p>
        </div>
      )}

      {/* Search */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4 shadow-sm">
        <div className="flex gap-2">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') setActiveSearch(search.trim()); }}
            placeholder="Search table names, column names, or comments…"
            className="flex-1 bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm"
          />
          <button
            onClick={() => setActiveSearch(search.trim())}
            disabled={search.trim().length < 2}
            className="flex items-center gap-1 px-3 py-2 rounded-full bg-cyan-600 text-white text-sm font-medium hover:bg-cyan-700 disabled:opacity-50"
          >
            <Search size={14} /> Search
          </button>
          {activeSearch && (
            <button
              onClick={() => { setSearch(''); setActiveSearch(''); }}
              className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
            >
              Clear
            </button>
          )}
        </div>
        {activeSearch && (
          <SearchResults
            hits={searchQ.data ?? []}
            loading={searchQ.isLoading}
            onPick={(hit) => {
              setSelectedCatalog(hit.catalog);
              setSelectedDatabase(hit.database);
              setSelectedTable(hit.table_name);
              setActiveSearch('');
              setSearch('');
            }}
          />
        )}
      </div>

      {/* Three-pane browser */}
      <div className="grid grid-cols-12 gap-3 min-h-[520px]">
        {/* Catalog/Database tree */}
        <div className="col-span-12 lg:col-span-3 bg-white border border-[var(--color-border)] rounded-2xl p-3 shadow-sm overflow-auto max-h-[640px]">
          <h2 className="text-xs font-semibold text-[var(--color-text-secondary)] mb-2 flex items-center gap-1">
            <Layers size={12} /> Catalogs
          </h2>
          {catalogsQ.isLoading ? (
            <p className="text-xs text-[var(--color-text-muted)]">Loading…</p>
          ) : (catalogsQ.data ?? []).length === 0 ? (
            <p className="text-xs text-[var(--color-text-muted)]">No catalogs.</p>
          ) : (
            <ul className="space-y-0.5">
              {(catalogsQ.data ?? []).map((c) => (
                <CatalogNode
                  key={c.catalog}
                  catalog={c.catalog}
                  tableCount={c.table_count}
                  databaseCount={c.database_count}
                  isOpen={selectedCatalog === c.catalog}
                  selectedDatabase={selectedCatalog === c.catalog ? selectedDatabase : null}
                  onToggle={() => setSelectedCatalog(selectedCatalog === c.catalog ? null : c.catalog)}
                  databases={selectedCatalog === c.catalog ? (databasesQ.data ?? []) : []}
                  databasesLoading={databasesQ.isLoading}
                  onPickDatabase={(name) => { setSelectedDatabase(name); setSelectedTable(null); }}
                />
              ))}
            </ul>
          )}
        </div>

        {/* Tables list */}
        <div className="col-span-12 lg:col-span-4 bg-white border border-[var(--color-border)] rounded-2xl p-3 shadow-sm overflow-auto max-h-[640px]">
          <h2 className="text-xs font-semibold text-[var(--color-text-secondary)] mb-2 flex items-center gap-1">
            <Table2 size={12} />
            Tables
            {selectedDatabase && (
              <span className="text-[10px] text-[var(--color-text-muted)] font-mono ml-1 truncate">
                in {selectedCatalog}.{selectedDatabase}
              </span>
            )}
          </h2>
          {!selectedDatabase ? (
            <p className="text-xs text-[var(--color-text-muted)] py-4 text-center">
              Pick a database from the tree on the left.
            </p>
          ) : tablesQ.isLoading ? (
            <p className="text-xs text-[var(--color-text-muted)]">Loading…</p>
          ) : (
            <TablesList
              tables={tablesQ.data ?? []}
              selected={selectedTable}
              onPick={setSelectedTable}
            />
          )}
        </div>

        {/* Table detail (columns) */}
        <div className="col-span-12 lg:col-span-5 bg-white border border-[var(--color-border)] rounded-2xl p-3 shadow-sm overflow-auto max-h-[640px]">
          {!selectedTable ? (
            <p className="text-xs text-[var(--color-text-muted)] py-4 text-center">
              Pick a table from the middle pane.
            </p>
          ) : tableDetailQ.isLoading ? (
            <p className="text-xs text-[var(--color-text-muted)] py-4 text-center">
              <Loader2 size={14} className="animate-spin inline mr-1" /> Loading columns…
            </p>
          ) : tableDetailQ.data ? (
            <TableDetailPane detail={tableDetailQ.data} />
          ) : null}
        </div>
      </div>
    </div>
  );
}


// -----------------------------------------------------------------------------

function CatalogNode({
  catalog, tableCount, databaseCount, isOpen, selectedDatabase, onToggle,
  databases, databasesLoading, onPickDatabase,
}: {
  catalog: string;
  tableCount: number;
  databaseCount: number;
  isOpen: boolean;
  selectedDatabase: string | null;
  onToggle: () => void;
  databases: { catalog: string; database: string; table_count: number; column_count: number }[];
  databasesLoading: boolean;
  onPickDatabase: (name: string) => void;
}) {
  return (
    <li>
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-1 px-1.5 py-1 text-xs rounded hover:bg-cyan-50 text-left"
      >
        {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <Layers size={12} className="text-cyan-600 shrink-0" />
        <span className="flex-1 font-medium truncate" title={catalog}>{catalog}</span>
        <span className="text-[10px] text-[var(--color-text-muted)] shrink-0">
          {numberFmt.format(databaseCount)} db / {numberFmt.format(tableCount)} t
        </span>
      </button>
      {isOpen && (
        <ul className="ml-4 mt-0.5 space-y-0.5">
          {databasesLoading ? (
            <li className="text-[10px] text-[var(--color-text-muted)] italic px-2">Loading…</li>
          ) : databases.length === 0 ? (
            <li className="text-[10px] text-[var(--color-text-muted)] italic px-2">no databases</li>
          ) : (
            databases.map((d) => (
              <li key={d.database}>
                <button
                  onClick={() => onPickDatabase(d.database)}
                  className={`w-full flex items-center gap-1 px-1.5 py-0.5 text-[11px] rounded text-left
                    ${selectedDatabase === d.database
                      ? 'bg-cyan-100 text-cyan-900 font-medium'
                      : 'hover:bg-cyan-50 text-[var(--color-text-secondary)]'}`}
                >
                  <Database size={10} className="shrink-0 text-cyan-500" />
                  <span className="flex-1 truncate" title={d.database}>{d.database}</span>
                  <span className="text-[10px] text-[var(--color-text-muted)] shrink-0">
                    {numberFmt.format(d.table_count)}
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </li>
  );
}


function TablesList({ tables, selected, onPick }: {
  tables: MetaTableRow[]; selected: string | null; onPick: (name: string) => void;
}) {
  if (tables.length === 0) {
    return <p className="text-xs text-[var(--color-text-muted)] py-4 text-center">No tables.</p>;
  }
  return (
    <ul className="space-y-0.5">
      {tables.map((t) => (
        <li key={t.table_name}>
          <button
            onClick={() => onPick(t.table_name)}
            className={`w-full flex items-start gap-2 px-2 py-1.5 text-xs rounded text-left
              ${selected === t.table_name
                ? 'bg-cyan-100 border border-cyan-300'
                : 'hover:bg-cyan-50 border border-transparent'}`}
          >
            <Table2 size={12} className="text-cyan-500 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-medium text-[var(--color-text-primary)] truncate" title={t.table_name}>
                {t.table_name}
              </p>
              <p className="text-[10px] text-[var(--color-text-muted)]">
                {t.table_type ?? 'TABLE'} · {numberFmt.format(t.column_count)} columns
                {t.table_owner && ` · owner ${t.table_owner}`}
              </p>
              {t.table_comment && (
                <p className="text-[10px] text-[var(--color-text-muted)] italic truncate mt-0.5" title={t.table_comment}>
                  {t.table_comment}
                </p>
              )}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}


function TableDetailPane({ detail }: { detail: import('../api/client').TableDetail }) {
  return (
    <div className="space-y-3">
      <div>
        <p className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">
          {detail.catalog} / {detail.database}
        </p>
        <h3 className="text-lg font-bold text-[var(--color-text-primary)] font-mono">{detail.table_name}</h3>
        <p className="text-[11px] text-[var(--color-text-muted)] mt-1 flex items-center gap-3 flex-wrap">
          {detail.table_type && <span className="bg-cyan-100 text-cyan-800 px-1.5 py-0.5 rounded">{detail.table_type}</span>}
          {detail.table_owner && <span className="flex items-center gap-0.5"><User size={10} /> {detail.table_owner}</span>}
          <span>{numberFmt.format(detail.columns.length)} columns</span>
        </p>
        {detail.table_comment && (
          <p className="text-xs text-[var(--color-text-secondary)] mt-2 italic">{detail.table_comment}</p>
        )}
      </div>

      <div className="border-t border-[var(--color-border)] pt-2">
        <h4 className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1">Columns</h4>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] border-b border-[var(--color-border)]">
              <th className="text-left py-1.5">Name</th>
              <th className="text-left py-1.5">Type</th>
              <th className="text-left py-1.5">Comment</th>
            </tr>
          </thead>
          <tbody>
            {detail.columns.map((c) => (
              <tr key={c.col_name} className="border-b border-[var(--color-border)]/40 hover:bg-cyan-50">
                <td className="py-1.5 pr-2 font-mono text-[11px] font-medium">{c.col_name}</td>
                <td className="py-1.5 pr-2 font-mono text-[11px] text-[var(--color-text-muted)]">{c.data_type ?? '—'}</td>
                <td className="py-1.5 text-[var(--color-text-muted)] text-[11px]">{c.comment ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


type ExportKind = 'catalogs' | 'tables' | 'columns';

function ExportToolbar({ disabled }: { disabled: boolean }) {
  const [busy, setBusy] = useState<{ kind: ExportKind; fmt: 'csv' | 'xlsx' } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(kind: ExportKind, fmt: 'csv' | 'xlsx') {
    if (busy || disabled) return;
    setBusy({ kind, fmt });
    setError(null);
    try {
      let rows: ExportRow[];
      let filename: string;
      if (kind === 'catalogs') {
        const data = await metaExplorer.exportCatalogs();
        filename = 'meta-catalogs';
        rows = data.map((r) => ({
          catalog: r.catalog,
          database_count: r.database_count,
          table_count: r.table_count,
          column_count: r.column_count,
        }));
      } else if (kind === 'tables') {
        const data = await metaExplorer.exportTables();
        filename = 'meta-tables';
        rows = data.map((r) => ({
          catalog: r.catalog,
          database: r.database,
          table_name: r.table_name,
          table_type: r.table_type,
          table_owner: r.table_owner,
          table_comment: r.table_comment,
          column_count: r.column_count,
        }));
      } else {
        const data = await metaExplorer.exportColumns();
        filename = 'meta-columns';
        rows = data.map((r) => ({
          catalog: r.catalog,
          database: r.database,
          table_name: r.table_name,
          table_type: r.table_type,
          table_owner: r.table_owner,
          table_comment: r.table_comment,
          col_name: r.col_name,
          data_type: r.data_type,
          comment: r.comment,
        }));
      }
      if (fmt === 'csv') exportToCsv(filename, rows);
      else exportToXlsx(filename, rows, kind);
    } catch (e: any) {
      setError(e?.message || 'Export failed');
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4 shadow-sm">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <Download size={16} className="text-cyan-600" />
          <span className="text-sm font-semibold text-[var(--color-text-primary)]">Export</span>
          <span className="text-xs text-[var(--color-text-muted)]">
            CSV or XLSX of the full Unity Catalog snapshot. Tables carry catalog+database;
            columns carry catalog+database+table.
          </span>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3">
        <ExportRowGroup
          label="Catalogs"
          description="One row per catalog with rollup counts."
          disabled={disabled}
          busyFmt={busy?.kind === 'catalogs' ? busy.fmt : null}
          onClick={(fmt) => run('catalogs', fmt)}
        />
        <ExportRowGroup
          label="Tables"
          description="Every table — includes catalog and database columns."
          disabled={disabled}
          busyFmt={busy?.kind === 'tables' ? busy.fmt : null}
          onClick={(fmt) => run('tables', fmt)}
        />
        <ExportRowGroup
          label="Columns"
          description="Every column — includes catalog, database, and table."
          disabled={disabled}
          busyFmt={busy?.kind === 'columns' ? busy.fmt : null}
          onClick={(fmt) => run('columns', fmt)}
        />
      </div>
      {error && (
        <p className="mt-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">
          {error}
        </p>
      )}
    </div>
  );
}

function ExportRowGroup({
  label, description, disabled, busyFmt, onClick,
}: {
  label: string;
  description: string;
  disabled: boolean;
  busyFmt: 'csv' | 'xlsx' | null;
  onClick: (fmt: 'csv' | 'xlsx') => void;
}) {
  const btn =
    'flex-1 px-3 py-1.5 rounded-md text-xs font-medium border transition-colors ' +
    'disabled:opacity-50 disabled:cursor-not-allowed';
  return (
    <div className="border border-[var(--color-border)] rounded-xl p-3 bg-[var(--color-bg-secondary)]/40">
      <p className="text-xs font-semibold text-[var(--color-text-primary)]">{label}</p>
      <p className="text-[11px] text-[var(--color-text-muted)] mt-0.5 mb-2 leading-snug">{description}</p>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onClick('csv')}
          disabled={disabled || busyFmt !== null}
          className={`${btn} border-cyan-300 text-cyan-700 hover:bg-cyan-50`}
        >
          {busyFmt === 'csv' ? (
            <span className="inline-flex items-center gap-1">
              <Loader2 size={11} className="animate-spin" /> CSV
            </span>
          ) : 'CSV'}
        </button>
        <button
          type="button"
          onClick={() => onClick('xlsx')}
          disabled={disabled || busyFmt !== null}
          className={`${btn} border-emerald-300 text-emerald-700 hover:bg-emerald-50`}
        >
          {busyFmt === 'xlsx' ? (
            <span className="inline-flex items-center gap-1">
              <Loader2 size={11} className="animate-spin" /> XLSX
            </span>
          ) : 'XLSX'}
        </button>
      </div>
    </div>
  );
}


function SearchResults({ hits, loading, onPick }: {
  hits: SearchHit[]; loading: boolean; onPick: (h: SearchHit) => void;
}) {
  if (loading) {
    return <p className="text-xs text-[var(--color-text-muted)] mt-3"><Loader2 size={12} className="animate-spin inline mr-1" /> Searching…</p>;
  }
  if (hits.length === 0) {
    return <p className="text-xs text-[var(--color-text-muted)] mt-3">No matches.</p>;
  }
  return (
    <div className="mt-3 border border-[var(--color-border)] rounded-lg overflow-hidden divide-y divide-[var(--color-border)] max-h-64 overflow-y-auto">
      {hits.map((h, i) => (
        <button
          key={i}
          onClick={() => onPick(h)}
          className="w-full px-3 py-1.5 text-left hover:bg-cyan-50 text-xs"
        >
          <span className="font-mono">{h.catalog}.{h.database}.{h.table_name}</span>
          {h.col_name && h.matched_in === 'column' && <span className="text-cyan-700">.{h.col_name}</span>}
          <span className="text-[10px] text-[var(--color-text-muted)] ml-2">[{h.matched_in}]</span>
        </button>
      ))}
    </div>
  );
}
