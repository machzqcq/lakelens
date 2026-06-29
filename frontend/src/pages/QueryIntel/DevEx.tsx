/**
 * Developer Experience — per-user footprint, tool mix, syntax-error pain.
 */
import { useQuery } from '@tanstack/react-query';
import {
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { qi } from '../../api/client';
import { QiShell, QiCard, MiniTable, fmtInt, fmtBytes, fmtDuration, CHART_COLORS, LoadingNote } from './shared';

export default function QueryIntelDevEx() {
  const users = useQuery({ queryKey: ['qi-userfp'], queryFn: () => qi.userFootprint(30) });
  const tools = useQuery({ queryKey: ['qi-tools'], queryFn: () => qi.toolMix() });
  const syntax = useQuery({ queryKey: ['qi-syntax'], queryFn: () => qi.syntaxErrors(20) });

  return (
    <QiShell
      title="Developer Experience"
      intro="Where developers are productive vs frustrated. Per-user footprint, tool mix, and the pain caused by syntax / unresolved-column errors."
    >
      <QiCard title="Tool Mix Across the Org"
        tooltip="Which client_application is sending the most queries? SQL Editor vs Notebook vs Tableau vs PowerBI.">
        {tools.isLoading ? <LoadingNote /> :
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie data={tools.data ?? []} dataKey="queries" nameKey="application"
                   cx="50%" cy="50%" outerRadius={100} label={(e: any) => e.application}>
                {(tools.data ?? []).map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        }
      </QiCard>

      <QiCard title="Top 30 Users by Query Volume"
        tooltip="Per-user counts, p50 latency, failure count, tools used. The 'who is your power user' table.">
        {users.isLoading ? <LoadingNote /> :
          <MiniTable rows={users.data ?? []} columns={[
            { key: 'user', label: 'User' },
            { key: 'total', label: 'Total', align: 'right', render: (v) => fmtInt.format(v) },
            { key: 'tools', label: 'Tools', align: 'right', render: (v) => fmtInt.format(v) },
            { key: 'p50_ms', label: 'p50', align: 'right', render: (v) => fmtDuration(Number(v)) },
            { key: 'failed', label: 'Failed', align: 'right', render: (v) => fmtInt.format(v) },
            { key: 'read_bytes', label: 'Read', align: 'right', render: (v) => fmtBytes(v) },
          ]} />
        }
      </QiCard>

      <QiCard title="Top Users by Syntax / Unresolved-Column Errors"
        tooltip="Proxy for developer pain. People near the top either need help or are running flaky generators.">
        {syntax.isLoading ? <LoadingNote /> :
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={syntax.data ?? []} layout="vertical" margin={{ left: 120 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis type="category" dataKey="user" width={140} tick={{ fontSize: 10 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="errors" fill="#ec4899" />
            </BarChart>
          </ResponsiveContainer>
        }
      </QiCard>
    </QiShell>
  );
}
