/**
 * BI / Analytics — slowest dashboards, vendor footprint, SELECT * backlog.
 */
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';
import { qi } from '../../api/client';
import { QiShell, QiCard, MiniTable, fmtInt, fmtDuration, fmtPct, CHART_COLORS, LoadingNote } from './shared';

export default function QueryIntelBI() {
  const dashboards = useQuery({ queryKey: ['qi-slowdash'], queryFn: () => qi.slowestDashboards(20) });
  const vendors = useQuery({ queryKey: ['qi-vendors'], queryFn: () => qi.vendorFootprint() });
  const star = useQuery({ queryKey: ['qi-star'], queryFn: () => qi.selectStarDashboards(20) });

  return (
    <QiShell
      title="BI / Analytics"
      intro="The dashboards executives stare at, the BI tools your org actually uses, and the SELECT * code-review backlog."
    >
      <QiCard title="Slowest Dashboards (p95 latency)"
        tooltip="Dashboards where p95 query latency is slowest. Cache and pre-aggregation usually pay off first here.">
        {dashboards.isLoading ? <LoadingNote /> :
          <MiniTable rows={dashboards.data ?? []} columns={[
            { key: 'dashboard_id', label: 'Dashboard', render: (v) => <span className="font-mono text-xs">{v}</span> },
            { key: 'query_count', label: 'Queries', align: 'right', render: (v) => fmtInt.format(v) },
            { key: 'p50_ms', label: 'p50', align: 'right', render: (v) => fmtDuration(Number(v)) },
            { key: 'p95_ms', label: 'p95', align: 'right', render: (v) => fmtDuration(Number(v)) },
            { key: 'cache_rate', label: 'Cache rate', align: 'right', render: (v) => fmtPct(Number(v)) },
          ]} />
        }
      </QiCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <QiCard title="BI Vendor / Client Footprint"
          tooltip="Distribution of queries across client_application. Drives Tableau-vs-PowerBI conversations.">
          {vendors.isLoading ? <LoadingNote /> :
            <ResponsiveContainer width="100%" height={320}>
              <PieChart>
                <Pie data={vendors.data ?? []} dataKey="statements" nameKey="application"
                     cx="50%" cy="50%" outerRadius={100} label={(e: any) => e.application}>
                  {(vendors.data ?? []).map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          }
        </QiCard>

        <QiCard title="p95 Latency per Vendor"
          tooltip="Side-by-side: which client_application has the slowest p95? Often points to bad ODBC defaults or unoptimized BI extracts.">
          {vendors.isLoading ? <LoadingNote /> :
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={(vendors.data ?? []).map((v: any) => ({ ...v, p95_ms: Number(v.p95_ms) }))} layout="vertical" margin={{ left: 120 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tickFormatter={(v) => fmtDuration(v)} />
                <YAxis type="category" dataKey="application" width={140} tick={{ fontSize: 10 }} />
                <Tooltip formatter={(v: any) => fmtDuration(Number(v))} />
                <Bar dataKey="p95_ms" fill="#3b82f6" />
              </BarChart>
            </ResponsiveContainer>
          }
        </QiCard>
      </div>

      <QiCard title="Dashboards with SELECT *"
        tooltip="Dashboards whose underlying SQL has SELECT *. Each one is a future column-rename outage waiting to happen.">
        {star.isLoading ? <LoadingNote /> :
          <MiniTable rows={star.data ?? []} columns={[
            { key: 'dashboard_id', label: 'Dashboard', render: (v) => <span className="font-mono text-xs">{v}</span> },
            { key: 'total', label: 'Total queries', align: 'right', render: (v) => fmtInt.format(v) },
            { key: 'star_count', label: 'SELECT * count', align: 'right', render: (v) => fmtInt.format(v) },
          ]} emptyMessage="No SELECT * dashboards — golden." />
        }
      </QiCard>
    </QiShell>
  );
}
