/**
 * FinOps — failed-query waste, surface attribution, project-keyword rollup.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  PieChart, Pie, Cell, BarChart, Bar, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { Search } from 'lucide-react';
import { qi } from '../../api/client';
import {
  QiShell, QiCard, MiniTable, fmtInt, fmtBytes, fmtDuration, fmtPct,
  CHART_COLORS, LoadingNote, ErrorNote,
} from './shared';
import KpiCard from '../../components/KpiCard';

export default function QueryIntelFinOps() {
  const failedCost = useQuery({ queryKey: ['qi-failedcost'], queryFn: () => qi.failedCost() });
  const attribution = useQuery({ queryKey: ['qi-attribution'], queryFn: () => qi.sourceAttribution() });
  const tagCov = useQuery({ queryKey: ['qi-tagcov'], queryFn: () => qi.tagCoverage() });
  const [keyword, setKeyword] = useState('');
  const [activeKeyword, setActiveKeyword] = useState('');
  const project = useQuery({
    queryKey: ['qi-project', activeKeyword],
    queryFn: () => qi.projectSearch(activeKeyword),
    enabled: !!activeKeyword,
  });

  return (
    <QiShell
      title="FinOps"
      intro="Where the duration is going, what's getting wasted on failures, and a keyword-driven project rollup for executive reviews."
    >
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <KpiCard title="Wasted Share"
          value={fmtPct(failedCost.data?.wasted_share)}
          subtitle={`Failed: ${fmtDuration(failedCost.data?.failed_ms)} · Canceled: ${fmtDuration(failedCost.data?.canceled_ms)}`}
          icon={<span>💸</span>} tooltip="Duration on FAILED+CANCELED / total duration." accentColor="#ef4444" />
        <KpiCard title="Tag-able Queries"
          value={fmtPct((tagCov.data?.parameterized || 0) / (tagCov.data?.total || 1))}
          subtitle={`${fmtInt.format(tagCov.data?.parameterized ?? 0)} parameterized of ${fmtInt.format(tagCov.data?.total ?? 0)}`}
          icon={<span>🏷️</span>} tooltip="Parameterized statement share — proxy for query maturity." accentColor="#8b5cf6" />
        <KpiCard title="Total Duration"
          value={fmtDuration(failedCost.data?.total_ms)}
          icon={<span>⏱️</span>} tooltip="Sum of total_duration_ms — the wallet you're spending against." accentColor="#0ea5e9" />
      </div>

      <QiCard title="Where duration goes — by source surface"
        tooltip="Total duration grouped by source_category (JOB vs DASHBOARD vs NOTEBOOK vs AD_HOC). The dollar story usually mirrors this.">
        {attribution.isLoading ? <LoadingNote /> :
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={attribution.data ?? []}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="category" />
              <YAxis tickFormatter={(v) => fmtDuration(v)} />
              <Tooltip formatter={(v: any) => fmtDuration(Number(v))} />
              <Bar dataKey="total_ms" fill="#10b981">
                {(attribution.data ?? []).map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        }
      </QiCard>

      <QiCard title="Project / Keyword Search"
        tooltip="Type a keyword (catalog name, schema name, table prefix). We roll up all statements that touched it: time series, top users, workspace fan-out.">
        <div className="flex gap-2 mb-4">
          <input type="text" value={keyword} onChange={(e) => setKeyword(e.target.value)}
            placeholder="e.g. 'sales', 'careset', 'finance'"
            className="flex-1 bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm" />
          <button onClick={() => setActiveKeyword(keyword.trim())}
            disabled={!keyword.trim()}
            className="flex items-center gap-2 px-4 py-2 rounded-full bg-[var(--color-primary)] text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
            <Search size={14} /> Search
          </button>
        </div>
        {activeKeyword && project.isLoading && <LoadingNote />}
        {activeKeyword && project.data && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <Tile label="Statements" value={fmtInt.format(project.data.summary.statements)} />
              <Tile label="Users" value={fmtInt.format(project.data.summary.users)} />
              <Tile label="Workspaces" value={fmtInt.format(project.data.summary.workspaces)} />
              <Tile label="Total duration" value={fmtDuration(project.data.summary.total_ms)} />
              <Tile label="Read bytes" value={fmtBytes(project.data.summary.read_bytes)} />
              <Tile label="Failed" value={fmtInt.format(project.data.summary.failed)} />
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={project.data.daily ?? []}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="d" tick={{ fontSize: 10 }} />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="statements" stroke="#3b82f6" />
              </LineChart>
            </ResponsiveContainer>
            <MiniTable rows={project.data.top_users ?? []} columns={[
              { key: 'user', label: 'Top users' },
              { key: 'statements', label: 'Statements', align: 'right', render: (v) => fmtInt.format(v) },
            ]} />
          </div>
        )}
      </QiCard>
    </QiShell>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-[var(--color-bg-secondary)] rounded-xl px-3 py-2">
      <p className="text-xs text-[var(--color-text-muted)]">{label}</p>
      <p className="text-base font-semibold text-[var(--color-text-primary)]">{value}</p>
    </div>
  );
}
