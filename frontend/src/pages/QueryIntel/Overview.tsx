/**
 * Query Profiler landing page — KPI tiles + a tour-style map of what each
 * department's sub-page covers.
 */
import { useQuery } from '@tanstack/react-query';
import {
  Activity, Users, Building2, CheckCircle2, Zap,
  CloudCog, Sparkles, LayoutDashboard, Briefcase, BookOpen,
  ShieldCheck, Code2, BarChart3, BrainCircuit, Server,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { qi } from '../../api/client';
import KpiCard from '../../components/KpiCard';
import { QiShell, QiCard, fmtInt, fmtPct, fmtDuration, NoDataNote, LoadingNote, ErrorNote } from './shared';

const DEPTS = [
  { path: '/query-intel/platform',    label: 'Platform / IT Admin',  desc: 'Hot-spots, queueing, error trends, cache effectiveness.', icon: Server,         color: 'text-blue-500' },
  { path: '/query-intel/catalog',     label: 'Catalog Usage',        desc: 'Top tables, columns, partitioning candidates, zombie tables.', icon: BookOpen,        color: 'text-indigo-500' },
  { path: '/query-intel/finops',      label: 'FinOps',               desc: 'Failed-query waste, surface attribution, project keyword search.', icon: Briefcase,      color: 'text-emerald-500' },
  { path: '/query-intel/executive',   label: 'Executive',            desc: 'Adoption KPIs, reliability, serverless share, Genie growth.', icon: BarChart3,        color: 'text-orange-500' },
  { path: '/query-intel/data-eng',    label: 'Data Engineering',     desc: 'Job failure rates, slowest pipelines, compile-heavy queries.', icon: CloudCog,        color: 'text-cyan-500' },
  { path: '/query-intel/bi',          label: 'BI / Analytics',       desc: 'Slowest dashboards, vendor footprint, SELECT * backlog.', icon: LayoutDashboard,  color: 'text-violet-500' },
  { path: '/query-intel/data-science',label: 'Data Science',         desc: 'Notebook activity, Genie adoption trend.',                icon: BrainCircuit,    color: 'text-purple-500' },
  { path: '/query-intel/security',    label: 'Security & Governance',desc: 'Permission denials, off-hours, bulk export, grants/revokes.', icon: ShieldCheck,    color: 'text-red-500' },
  { path: '/query-intel/devex',       label: 'Developer Experience', desc: 'Per-user footprint, tool mix, syntax-error pain.',         icon: Code2,            color: 'text-pink-500' },
  { path: '/query-intel/cross-cutting',label: 'Cross-cutting',        desc: 'SQL feature mix, duplicate queries, hour-of-day load.',    icon: Activity,         color: 'text-slate-500' },
];

export default function QueryIntelOverview() {
  const ov = useQuery({ queryKey: ['qi-overview'], queryFn: () => qi.overview() });

  if (ov.isLoading) return <QiShell title="Query Profiler"><LoadingNote /></QiShell>;
  if (ov.isError) return <QiShell title="Query Profiler"><ErrorNote error={ov.error as Error} /></QiShell>;
  if (!ov.data?.has_data) return <QiShell title="Query Profiler"><NoDataNote /></QiShell>;

  const d = ov.data;
  return (
    <QiShell
      title="Query Profiler"
      intro="Derived analytics over query_history — every department's pulse on how the lakehouse is actually used."
    >
      {/* Top KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard title="Total Statements" value={fmtInt.format(d.total_statements)}
          subtitle={`${d.date_min} → ${d.date_max}`}
          icon={<Activity size={18} />} tooltip="All rows in qi_statements." />
        <KpiCard title="Distinct Users" value={fmtInt.format(d.distinct_users)}
          subtitle={`${d.distinct_workspaces} workspaces`}
          icon={<Users size={18} />} tooltip="Unique executed_by values." accentColor="#10b981" />
        <KpiCard title="Success Rate" value={fmtPct(d.success_rate)}
          subtitle={`${fmtInt.format(d.failed_count)} failed · ${fmtInt.format(d.canceled_count)} canceled`}
          icon={<CheckCircle2 size={18} />} tooltip="FINISHED / total." accentColor={d.success_rate >= 0.9 ? '#10b981' : '#f59e0b'} />
        <KpiCard title="Latency p50/p95" value={`${fmtDuration(d.median_duration_ms)} / ${fmtDuration(d.p95_duration_ms)}`}
          icon={<Zap size={18} />} tooltip="Median and 95th-percentile total_duration_ms." accentColor="#3b82f6" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard title="Cache Hit Rate" value={fmtPct(d.cache_hit_rate)}
          icon={<Sparkles size={18} />} tooltip="from_result_cache=true / total" accentColor="#8b5cf6" />
        <KpiCard title="Serverless Share" value={fmtPct(d.serverless_share)}
          icon={<CloudCog size={18} />} tooltip="compute.type=SERVERLESS_COMPUTE / total" accentColor="#06b6d4" />
        <KpiCard title="Dashboard Queries" value={fmtInt.format(d.dashboard_query_count)}
          subtitle={`${fmtInt.format(d.job_query_count)} job · ${fmtInt.format(d.notebook_query_count)} notebook`}
          icon={<LayoutDashboard size={18} />} tooltip="Surface attribution from query_source." accentColor="#f59e0b" />
        <KpiCard title="Genie / AI Queries" value={fmtInt.format(d.genie_query_count)}
          icon={<BrainCircuit size={18} />} tooltip="Statements with genie_space_id set." accentColor="#ec4899" />
      </div>

      {d.last_extract_at && (
        <p className="text-xs text-[var(--color-text-muted)]">
          Last extracted from <code>{d.last_extract_source}</code> at {new Date(d.last_extract_at).toLocaleString()}
        </p>
      )}

      {/* Tour cards */}
      <QiCard title="Open a department view" tooltip="Each card opens a sub-page with the scenarios specific to that role.">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {DEPTS.map((dept) => {
            const Icon = dept.icon;
            return (
              <Link key={dept.path} to={dept.path}
                className="flex items-start gap-3 p-4 rounded-xl border border-[var(--color-border)] hover:border-[var(--color-primary)] hover:bg-blue-50 transition-all">
                <Icon size={20} className={dept.color} />
                <div>
                  <p className="text-sm font-medium text-[var(--color-text-primary)]">{dept.label}</p>
                  <p className="text-xs text-[var(--color-text-muted)] mt-0.5">{dept.desc}</p>
                </div>
              </Link>
            );
          })}
        </div>
      </QiCard>
    </QiShell>
  );
}
