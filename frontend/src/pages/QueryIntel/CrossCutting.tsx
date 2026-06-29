/**
 * Cross-cutting — SQL feature mix, duplicate-query roll-up, hour-of-day load.
 */
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from 'recharts';
import { qi } from '../../api/client';
import { QiShell, QiCard, MiniTable, fmtInt, fmtDuration, CHART_COLORS, LoadingNote } from './shared';

export default function QueryIntelCross() {
  const features = useQuery({ queryKey: ['qi-features'], queryFn: () => qi.sqlFeatureMix() });
  const hour = useQuery({ queryKey: ['qi-hour'], queryFn: () => qi.hourOfDay() });
  const dups = useQuery({ queryKey: ['qi-dups'], queryFn: () => qi.duplicateQueries(20) });
  const types = useQuery({ queryKey: ['qi-types'], queryFn: () => qi.statementTypeMix() });

  const featuresArr = features.data ? Object.entries(features.data)
    .filter(([k]) => k !== 'total')
    .map(([k, v]) => ({ feature: k, count: Number(v), pct: features.data.total ? Number(v) / features.data.total : 0 }))
    .sort((a, b) => b.count - a.count) : [];

  return (
    <QiShell
      title="Cross-cutting"
      intro="SQL feature usage across the whole org, hour-of-day load curve, repeated queries that could be cached, and the statement-type histogram."
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <QiCard title="SQL Feature Mix"
          tooltip="Share of SQL statements that use CTE / subquery / window / SELECT * / cross join. A maturity signal.">
          {features.isLoading ? <LoadingNote /> :
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={featuresArr} layout="vertical" margin={{ left: 100 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis type="category" dataKey="feature" width={110} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="count" fill="#6366f1" />
              </BarChart>
            </ResponsiveContainer>
          }
        </QiCard>

        <QiCard title="Statement-Type Mix"
          tooltip="Distribution of statement_type (SELECT, MERGE, INSERT, …).">
          {types.isLoading ? <LoadingNote /> :
            <ResponsiveContainer width="100%" height={320}>
              <PieChart>
                <Pie data={types.data ?? []} dataKey="n" nameKey="statement_type"
                     cx="50%" cy="50%" outerRadius={100} label={(e: any) => e.statement_type}>
                  {(types.data ?? []).map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          }
        </QiCard>
      </div>

      <QiCard title="Hour-of-Day Load"
        tooltip="Total query volume + median latency per hour. Peaks tell you where to add capacity.">
        {hour.isLoading ? <LoadingNote /> :
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={(hour.data ?? []).map((r: any) => ({ ...r, p50_ms: Number(r.p50_ms) }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="hour" />
              <YAxis yAxisId="left" />
              <YAxis yAxisId="right" orientation="right" tickFormatter={(v) => fmtDuration(v)} />
              <Tooltip />
              <Legend />
              <Area yAxisId="left" type="monotone" dataKey="queries" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.4} />
              <Line yAxisId="right" type="monotone" dataKey="p50_ms" stroke="#f59e0b" />
            </AreaChart>
          </ResponsiveContainer>
        }
      </QiCard>

      <QiCard title="Most Duplicate Queries"
        tooltip="Same normalized SQL run 5+ times. Each row is a materialized-view candidate (or a TTL extension).">
        {dups.isLoading ? <LoadingNote /> :
          <MiniTable rows={dups.data ?? []} columns={[
            { key: 'runs', label: 'Runs', align: 'right', render: (v) => fmtInt.format(v) },
            { key: 'users', label: 'Users', align: 'right', render: (v) => fmtInt.format(v) },
            { key: 'avg_ms', label: 'Avg dur', align: 'right', render: (v) => fmtDuration(Number(v)) },
            { key: 'total_ms', label: 'Total dur', align: 'right', render: (v) => fmtDuration(Number(v)) },
            { key: 'sample_excerpt', label: 'SQL',
              render: (v) => <span className="font-mono text-xs">{(v || '').slice(0, 80)}…</span> },
          ]} />
        }
      </QiCard>
    </QiShell>
  );
}
