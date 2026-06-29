/**
 * Data Engineering — job failure rates, slowest pipelines, compile-heavy.
 */
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { qi } from '../../api/client';
import { QiShell, QiCard, MiniTable, fmtInt, fmtDuration, fmtPct, LoadingNote } from './shared';

export default function QueryIntelDataEng() {
  const jobs = useQuery({ queryKey: ['qi-jobfail'], queryFn: () => qi.jobFailureRates(20) });
  const pipelines = useQuery({ queryKey: ['qi-slowpipes'], queryFn: () => qi.slowestPipelines(20) });
  const compileHeavy = useQuery({ queryKey: ['qi-compile'], queryFn: () => qi.compileHeavy(20) });

  return (
    <QiShell
      title="Data Engineering"
      intro="Job health, pipeline drift, and queries with absurd compile overhead."
    >
      <QiCard title="Jobs by Failure Rate (min 5 runs)"
        tooltip="Highest failure-rate jobs. These are the ones eating on-call time.">
        {jobs.isLoading ? <LoadingNote /> :
          <MiniTable rows={jobs.data ?? []} columns={[
            { key: 'job_id', label: 'Job ID', render: (v) => <span className="font-mono text-xs">{v}</span> },
            { key: 'statements', label: 'Statements', align: 'right', render: (v) => fmtInt.format(v) },
            { key: 'failed', label: 'Failed', align: 'right', render: (v) => fmtInt.format(v) },
            { key: 'failure_rate', label: 'Failure rate', align: 'right', render: (v) => fmtPct(Number(v)) },
            { key: 'avg_duration_ms', label: 'Avg dur', align: 'right', render: (v) => fmtDuration(Number(v)) },
          ]} emptyMessage="No jobs with ≥5 runs in window." />
        }
      </QiCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <QiCard title="Slowest Pipelines"
          tooltip="Pipelines ranked by average run duration. Watch for drift week-over-week.">
          {pipelines.isLoading ? <LoadingNote /> :
            <MiniTable rows={pipelines.data ?? []} columns={[
              { key: 'pipeline_id', label: 'Pipeline ID' },
              { key: 'statements', label: 'Statements', align: 'right', render: (v) => fmtInt.format(v) },
              { key: 'avg_ms', label: 'Avg', align: 'right', render: (v) => fmtDuration(Number(v)) },
              { key: 'max_ms', label: 'Max', align: 'right', render: (v) => fmtDuration(Number(v)) },
              { key: 'failed', label: 'Failed', align: 'right', render: (v) => fmtInt.format(v) },
            ]} emptyMessage="No pipeline statements found." />
          }
        </QiCard>

        <QiCard title="Compile-Heavy Queries (>25% of duration in planning)"
          tooltip="Compile/total > 25%. Usually huge dynamic SQL or pathological optimizer cost. Either trim or pre-compute.">
          {compileHeavy.isLoading ? <LoadingNote /> :
            <MiniTable rows={compileHeavy.data ?? []} columns={[
              { key: 'executed_by', label: 'User' },
              { key: 'total_duration_ms', label: 'Total', align: 'right', render: (v) => fmtDuration(v) },
              { key: 'compilation_duration_ms', label: 'Compile', align: 'right', render: (v) => fmtDuration(v) },
              { key: 'compile_pct', label: '% compile', align: 'right', render: (v) => fmtPct(Number(v)) },
            ]} emptyMessage="No compile-heavy queries flagged." />
          }
        </QiCard>
      </div>
    </QiShell>
  );
}
