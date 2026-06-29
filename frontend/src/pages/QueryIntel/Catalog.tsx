/**
 * Catalog Usage — what tables, columns, and patterns are dominating the lakehouse.
 */
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { qi } from '../../api/client';
import { QiShell, QiCard, MiniTable, fmtInt, fmtBytes, fmtPct, LoadingNote, ErrorNote } from './shared';

const ROLE_OPTIONS = ['', 'read', 'write', 'cte', 'reference'] as const;
const COLUMN_ROLE_OPTIONS = ['', 'select', 'where', 'groupby', 'orderby', 'join', 'having', 'aggregate'] as const;

export default function QueryIntelCatalog() {
  const [tableRole, setTableRole] = useState<string>('');
  const [colRole, setColRole] = useState<string>('where');

  const topTables = useQuery({
    queryKey: ['qi-toptables', tableRole],
    queryFn: () => qi.topTables(20, tableRole || undefined),
  });
  const topCols = useQuery({
    queryKey: ['qi-topcols', colRole],
    queryFn: () => qi.topColumns(20, colRole || undefined),
  });
  const partitioning = useQuery({ queryKey: ['qi-partitioning'], queryFn: () => qi.partitioningCandidates(20) });
  const zombies = useQuery({ queryKey: ['qi-zombies'], queryFn: () => qi.zombieTables(20) });

  return (
    <QiShell
      title="Catalog Usage"
      intro="Where the SQL is actually pointing. Drives partitioning decisions, materialized-view candidates, and zombie-table retirement."
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <QiCard title="Top Referenced Tables"
          tooltip="Tables ranked by distinct statement count. Heavy hitters drive most cost.">
          <div className="mb-3 flex items-center gap-2">
            <span className="text-xs text-[var(--color-text-muted)]">Role:</span>
            <select value={tableRole} onChange={(e) => setTableRole(e.target.value)}
                    className="text-xs border border-[var(--color-border)] rounded px-2 py-1">
              {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r || 'any'}</option>)}
            </select>
          </div>
          {topTables.isLoading ? <LoadingNote /> : topTables.isError ?
            <ErrorNote error={topTables.error as Error} /> :
            <MiniTable rows={topTables.data ?? []} columns={[
              { key: 'table', label: 'Table' },
              { key: 'statements', label: 'Statements', align: 'right', render: (v) => fmtInt.format(v) },
              { key: 'users', label: 'Users', align: 'right', render: (v) => fmtInt.format(v) },
            ]} />}
        </QiCard>

        <QiCard title="Top Referenced Columns"
          tooltip="Most-used columns by role. Drives partitioning / Z-ORDER decisions.">
          <div className="mb-3 flex items-center gap-2">
            <span className="text-xs text-[var(--color-text-muted)]">Role:</span>
            <select value={colRole} onChange={(e) => setColRole(e.target.value)}
                    className="text-xs border border-[var(--color-border)] rounded px-2 py-1">
              {COLUMN_ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r || 'any'}</option>)}
            </select>
          </div>
          {topCols.isLoading ? <LoadingNote /> :
            <ResponsiveContainer width="100%" height={400}>
              <BarChart data={topCols.data ?? []} layout="vertical" margin={{ left: 120 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis type="category" dataKey="column_name" width={140} tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="statements" fill="#6366f1" />
              </BarChart>
            </ResponsiveContainer>
          }
        </QiCard>

        <QiCard title="Partitioning Candidates"
          tooltip="Tables with low pruning_ratio (lots of files scanned vs files pruned). Adding a partition key or Liquid Clustering could cut scans drastically.">
          {partitioning.isLoading ? <LoadingNote /> :
            <MiniTable rows={partitioning.data ?? []} columns={[
              { key: 'table', label: 'Table' },
              { key: 'avg_pruning', label: 'Avg pruning', align: 'right', render: (v) => fmtPct(Number(v)) },
              { key: 'read_bytes', label: 'Read', align: 'right', render: (v) => fmtBytes(v) },
              { key: 'statements', label: 'Queries', align: 'right', render: (v) => fmtInt.format(v) },
            ]} emptyMessage="No partitioning candidates flagged." />
          }
        </QiCard>

        <QiCard title="Zombie Tables"
          tooltip="Tables WRITTEN to but never READ. Candidates for retirement — they're consuming storage with no consumer value.">
          {zombies.isLoading ? <LoadingNote /> :
            <MiniTable rows={zombies.data ?? []} columns={[
              { key: 'table', label: 'Table' },
              { key: 'write_count', label: 'Write events', align: 'right', render: (v) => fmtInt.format(v) },
            ]} emptyMessage="No zombie tables — every table written has a reader." />
          }
        </QiCard>
      </div>
    </QiShell>
  );
}
