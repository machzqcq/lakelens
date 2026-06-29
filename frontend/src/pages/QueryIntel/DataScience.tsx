/**
 * Data Science — notebook activity, Genie / AI adoption trend.
 */
import { useQuery } from '@tanstack/react-query';
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts';
import { qi } from '../../api/client';
import { QiShell, QiCard, MiniTable, fmtInt, fmtDuration, fmtPct, LoadingNote } from './shared';

export default function QueryIntelDataScience() {
  const notebooks = useQuery({ queryKey: ['qi-notebooks'], queryFn: () => qi.notebookActivity(20) });
  const genie = useQuery({ queryKey: ['qi-genie'], queryFn: () => qi.genieAdoption() });

  return (
    <QiShell
      title="Data Science"
      intro="How busy each notebook is, and the trend in AI-assisted (Genie) queries — the headline number for any AI-adoption review."
    >
      <QiCard title="Genie / AI Adoption — weekly"
        tooltip="Queries against a Genie space, by week. The success rate line shows whether AI-generated SQL is actually executing.">
        {genie.isLoading ? <LoadingNote /> :
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={(genie.data ?? []).map((r: any) => ({ ...r, success_rate: Number(r.success_rate) * 100 }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="week" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="left" />
              <YAxis yAxisId="right" orientation="right" domain={[0, 100]} tickFormatter={(v) => `${v.toFixed(0)}%`} />
              <Tooltip />
              <Legend />
              <Area yAxisId="left" type="monotone" dataKey="queries" stroke="#ec4899" fill="#ec4899" fillOpacity={0.5} />
              <Line yAxisId="right" type="monotone" dataKey="success_rate" stroke="#10b981" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        }
      </QiCard>

      <QiCard title="Top 20 Notebooks by Query Count"
        tooltip="Most-active notebooks (by query count, distinct users, median latency, and failure count).">
        {notebooks.isLoading ? <LoadingNote /> :
          <MiniTable rows={notebooks.data ?? []} columns={[
            { key: 'notebook_id', label: 'Notebook', render: (v) => <span className="font-mono text-xs">{v}</span> },
            { key: 'queries', label: 'Queries', align: 'right', render: (v) => fmtInt.format(v) },
            { key: 'users', label: 'Users', align: 'right', render: (v) => fmtInt.format(v) },
            { key: 'p50_ms', label: 'p50', align: 'right', render: (v) => fmtDuration(Number(v)) },
            { key: 'failed', label: 'Failed', align: 'right', render: (v) => fmtInt.format(v) },
          ]} />
        }
      </QiCard>
    </QiShell>
  );
}
