/**
 * Platform / IT Admin — hot-spots, queueing, error patterns, cache.
 */
import { useQuery } from '@tanstack/react-query';
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend, Cell, PieChart, Pie,
} from 'recharts';
import { qi } from '../../api/client';
import {
  QiShell, QiCard, MiniTable, fmtInt, fmtBytes, fmtDuration, fmtPct,
  CHART_COLORS, LoadingNote, ErrorNote,
} from './shared';

export default function QueryIntelPlatform() {
  const expensive = useQuery({ queryKey: ['qi-expensive'], queryFn: () => qi.expensiveQueries(20) });
  const fullScans = useQuery({ queryKey: ['qi-fullscans'], queryFn: () => qi.fullScans(20) });
  const spill = useQuery({ queryKey: ['qi-spill'], queryFn: () => qi.spillLeaders(10) });
  const errTrends = useQuery({ queryKey: ['qi-errtrends'], queryFn: () => qi.errorTrends() });
  const errCats = useQuery({ queryKey: ['qi-errcats'], queryFn: () => qi.errorCategories() });
  const cap = useQuery({ queryKey: ['qi-capacity'], queryFn: () => qi.capacityQueueing() });
  const cache = useQuery({ queryKey: ['qi-cache'], queryFn: () => qi.cacheEffectiveness() });

  const errTrendByCat = (() => {
    const rows = errTrends.data ?? [];
    const map = new Map<string, any>();
    rows.forEach((r: any) => {
      if (!r.d) return;
      const k = String(r.d);
      if (!map.has(k)) map.set(k, { d: k });
      map.get(k)[r.category ?? 'UNKNOWN'] = r.n;
    });
    return Array.from(map.values()).sort((a, b) => a.d.localeCompare(b.d));
  })();

  const errCategoryRoll = (() => {
    const rows = errCats.data ?? [];
    const m = new Map<string, number>();
    rows.forEach((r: any) => m.set(r.category ?? 'UNKNOWN', (m.get(r.category ?? 'UNKNOWN') ?? 0) + (r.n ?? 0)));
    return Array.from(m.entries()).map(([category, n]) => ({ category, n }));
  })();

  return (
    <QiShell
      title="Platform / IT Admin"
      intro="The on-call view: hot-spots, queueing patterns, error trends, and cache effectiveness."
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <QiCard title="Top 20 Expensive Queries"
          tooltip="Highest total_duration_ms. Click into a row for the statement excerpt.">
          {expensive.isLoading ? <LoadingNote /> :
           expensive.isError ? <ErrorNote error={expensive.error as Error} /> :
            <MiniTable rows={expensive.data ?? []} columns={[
              { key: 'executed_by', label: 'User' },
              { key: 'compute_type', label: 'Compute' },
              { key: 'total_duration_ms', label: 'Duration', align: 'right', render: (v) => fmtDuration(v) },
              { key: 'read_bytes', label: 'Read', align: 'right', render: (v) => fmtBytes(v) },
              { key: 'statement_text_excerpt', label: 'Statement',
                render: (v) => <span className="font-mono text-xs text-[var(--color-text-muted)]" title={v}>{(v || '').slice(0, 60)}…</span> },
            ]} />}
        </QiCard>

        <QiCard title="Full-Scan Suspects"
          tooltip=">100 GB scanned but fewer than 1k rows produced — classic missing WHERE.">
          {fullScans.isLoading ? <LoadingNote /> :
            <MiniTable rows={fullScans.data ?? []} columns={[
              { key: 'executed_by', label: 'User' },
              { key: 'read_bytes', label: 'Scanned', align: 'right', render: (v) => fmtBytes(v) },
              { key: 'produced_rows', label: 'Rows out', align: 'right', render: (v) => fmtInt.format(v ?? 0) },
              { key: 'total_duration_ms', label: 'Duration', align: 'right', render: (v) => fmtDuration(v) },
            ]} emptyMessage="No full-scan suspects in the current window." />}
        </QiCard>

        <QiCard title="Spill Leaders"
          tooltip="Users whose statements spilled the most bytes to local disk. High spill = under-sized warehouse or pathological joins.">
          {spill.isLoading ? <LoadingNote /> :
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={spill.data ?? []} layout="vertical" margin={{ left: 80, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tickFormatter={(v) => fmtBytes(v)} />
                <YAxis type="category" dataKey="user" width={140} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v: any) => fmtBytes(v)} />
                <Bar dataKey="spill_bytes" fill="#ef4444" />
              </BarChart>
            </ResponsiveContainer>
          }
        </QiCard>

        <QiCard title="Error Mix"
          tooltip="Failed statements broken down by error category.">
          {errCats.isLoading ? <LoadingNote /> :
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={errCategoryRoll} dataKey="n" nameKey="category" cx="50%" cy="50%" outerRadius={90} label>
                  {errCategoryRoll.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(v: any) => fmtInt.format(v)} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          }
        </QiCard>
      </div>

      <QiCard title="Daily Error Trend"
        tooltip="Failures per day, stacked by error category. Watch for growing categories week-over-week.">
        {errTrends.isLoading ? <LoadingNote /> :
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={errTrendByCat}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="d" tick={{ fontSize: 10 }} />
              <YAxis />
              <Tooltip />
              <Legend />
              {['PARSE', 'PERMISSION', 'NOT_FOUND', 'OOM', 'TIMEOUT', 'ANALYSIS', 'OTHER'].map((cat, i) => (
                <Area key={cat} type="monotone" dataKey={cat} stackId="1"
                      stroke={CHART_COLORS[i]} fill={CHART_COLORS[i]} fillOpacity={0.6} />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        }
      </QiCard>

      <QiCard title="Queueing by Hour-of-Day"
        tooltip="Average waiting_at_capacity_duration_ms per hour. High bars = peak hours when warehouses are saturated.">
        {cap.isLoading ? <LoadingNote /> :
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={(cap.data ?? []).map((r: any) => ({ hour: r.hour, avg_wait_ms: Number(r.avg_wait_ms) || 0 }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="hour" />
              <YAxis tickFormatter={(v) => fmtDuration(v)} />
              <Tooltip formatter={(v: any) => fmtDuration(Number(v))} />
              <Bar dataKey="avg_wait_ms" fill="#f59e0b" />
            </BarChart>
          </ResponsiveContainer>
        }
      </QiCard>

      <QiCard title="Cache Effectiveness Per Dashboard (Top 50)"
        tooltip="Per dashboard: % of queries served from result cache. Low % = candidate for longer TTL or materialized view.">
        {cache.isLoading ? <LoadingNote /> :
          <MiniTable rows={cache.data ?? []} columns={[
            { key: 'dashboard', label: 'Dashboard ID',
              render: (v) => <span className="font-mono text-xs">{v}</span> },
            { key: 'total', label: 'Queries', align: 'right', render: (v) => fmtInt.format(v) },
            { key: 'cache_hits', label: 'Cache hits', align: 'right', render: (v) => fmtInt.format(v) },
            { key: 'cache_rate', label: 'Hit rate', align: 'right', render: (v) => fmtPct(v) },
          ]} emptyMessage="No dashboards found." />
        }
      </QiCard>
    </QiShell>
  );
}
