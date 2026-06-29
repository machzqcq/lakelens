/**
 * Meta Explorer > Audit — dashboards over `system.access.audit` and
 * `system.access.assistant_events`.
 *
 * Layout:
 *   - KPI tiles (audit events, distinct users, distinct services + actions,
 *     error events, last event timestamp, Assistant prompt count).
 *   - Three breakdown bars: by service_name, by audit_level
 *     (ACCOUNT_LEVEL / WORKSPACE_LEVEL), by HTTP-style status class.
 *   - Top services × actions list + top users.
 *   - Assistant section: top users + KPI cards.
 *   - Search + filterable recent-events table (errors-only toggle, per-service
 *     dropdown, per-user dropdown).
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Shield, AlertTriangle, Clock, Users, Activity, Sparkles, Search, Loader2,
  CheckCircle2, XCircle, Database,
} from 'lucide-react';
import { metaExplorer, type AuditEventOut } from '../api/client';
import KpiCard from '../components/KpiCard';
import InfoTooltip from '../components/InfoTooltip';
import { BreakdownBar, numberFmt } from './lineage/_shared';

export default function MetaAudit() {
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [serviceFilter, setServiceFilter] = useState<string>('');
  const [userFilter, setUserFilter] = useState<string>('');
  const [search, setSearch] = useState('');
  const [activeSearch, setActiveSearch] = useState('');

  const statsQ = useQuery({ queryKey: ['audit-stats'], queryFn: () => metaExplorer.auditStats(15) });
  const recentQ = useQuery({
    queryKey: ['audit-recent', errorsOnly, serviceFilter, userFilter],
    queryFn: () => metaExplorer.auditRecent({
      limit: 50,
      errors_only: errorsOnly,
      service: serviceFilter || undefined,
      user_email: userFilter || undefined,
    }),
  });
  const searchQ = useQuery({
    queryKey: ['audit-search', activeSearch],
    queryFn: () => metaExplorer.auditSearch(activeSearch, 50),
    enabled: activeSearch.length >= 2,
  });

  const stats = statsQ.data;
  const hasData = (stats?.audit_events ?? 0) > 0 || (stats?.assistant_events ?? 0) > 0;

  // Unique service / user dropdown values from the breakdown bars so the
  // filters surface only what's actually present in the current partition.
  const serviceOptions = useMemo(
    () => (stats?.by_service ?? []).map((b) => b.label).filter((s) => s && s !== '(none)'),
    [stats],
  );
  const userOptions = useMemo(
    () => (stats?.top_users ?? []).map((b) => b.label).filter(Boolean),
    [stats],
  );

  return (
    <div className="space-y-6 max-w-[1500px]">
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)] flex items-center gap-2">
          <Shield size={20} className="text-rose-600" />
          Audit
          <InfoTooltip text="Dashboards over system.access.audit (every workspace + account-level action: logins, table grants, notebook exports, SQL warehouse start/stops, Unity Catalog ops) and system.access.assistant_events (Databricks Assistant / Genie user prompts). View-mode scoped." />
        </h1>
        <p className="text-sm text-[var(--color-text-muted)] mt-1">
          Who did what across the workspace + account. Click any breakdown row
          to filter the recent-events table.
          {stats?.last_event && (
            <span className="ml-2 inline-flex items-center gap-1">
              <Clock size={11} /> Last audit event: <strong>{stats.last_event}</strong>
            </span>
          )}
        </p>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
        <KpiCard title="Audit events" value={numberFmt.format(stats?.audit_events ?? 0)}
          icon={<Activity size={18} />} accentColor="#e11d48"
          tooltip="Rows in audit_events within the active view-mode partition." />
        <KpiCard title="Distinct users" value={numberFmt.format(stats?.distinct_users ?? 0)}
          icon={<Users size={18} />} accentColor="#3b82f6"
          tooltip="Distinct user_identity_email values across audit events." />
        <KpiCard title="Distinct services" value={numberFmt.format(stats?.distinct_services ?? 0)}
          icon={<Database size={18} />} accentColor="#0891b2"
          tooltip="Distinct service_name values (unityCatalog, notebook, SQL, …)." />
        <KpiCard title="Distinct actions" value={numberFmt.format(stats?.distinct_actions ?? 0)}
          icon={<Shield size={18} />} accentColor="#a855f7"
          tooltip="Distinct (service_name, action_name) pairs." />
        <KpiCard title="Error events" value={numberFmt.format(stats?.error_events ?? 0)}
          icon={<AlertTriangle size={18} />} accentColor="#f97316"
          tooltip="Audit events with response_status_code >= 400." />
        <KpiCard title="Assistant prompts" value={numberFmt.format(stats?.assistant_events ?? 0)}
          icon={<Sparkles size={18} />} accentColor="#f59e0b"
          tooltip="User-submitted Databricks Assistant / Genie prompts. Excludes autocomplete & safety checks." />
      </div>

      {!hasData && !statsQ.isLoading && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3">
          <p className="text-sm font-medium text-yellow-800">No audit data yet.</p>
          <p className="text-xs text-yellow-700 mt-1">
            Trigger an extract that includes the <code>audit</code> group, or run
            <code> python scripts/simulate_demo_data.py </code> and switch to demo view-mode.
          </p>
        </div>
      )}

      {/* Breakdown bars */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <BreakdownBar
          title="By service_name"
          total={stats?.audit_events ?? 0}
          accent="#e11d48"
          items={(stats?.by_service ?? []).map((b) => ({ label: b.label, count: b.count }))}
        />
        <BreakdownBar
          title="By audit_level"
          total={stats?.audit_events ?? 0}
          accent="#3b82f6"
          items={(stats?.by_audit_level ?? []).map((b) => ({ label: b.label, count: b.count }))}
        />
        <BreakdownBar
          title="By response status class"
          total={stats?.audit_events ?? 0}
          accent="#f59e0b"
          items={(stats?.by_status_class ?? []).map((b) => ({ label: b.label, count: b.count }))}
        />
      </div>

      {/* Top lists */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        <TopList title="Top actions" subtitle="service_name : action_name pairs"
          items={stats?.top_actions ?? []}
          onPick={(label) => {
            const [svc] = label.split(':');
            setServiceFilter(svc); setUserFilter('');
          }}
          accent="#a21caf" />
        <TopList title="Top users (audit)" subtitle="By total audit events"
          items={stats?.top_users ?? []}
          onPick={(label) => { setUserFilter(label); setServiceFilter(''); }}
          accent="#3b82f6" />
        <TopList title="Top users (Assistant)" subtitle="By total Genie / Assistant prompts"
          items={stats?.top_assistant_users ?? []}
          onPick={() => undefined}
          accent="#f59e0b" />
      </div>

      {/* Search */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4 shadow-sm space-y-2">
        <div className="flex gap-2">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') setActiveSearch(search.trim()); }}
            placeholder="Search by user / service / action / IP / error message…"
            className="flex-1 bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm"
          />
          <button
            onClick={() => setActiveSearch(search.trim())}
            disabled={search.trim().length < 2}
            className="flex items-center gap-1 px-3 py-2 rounded-full bg-rose-600 text-white text-sm font-medium hover:bg-rose-700 disabled:opacity-50"
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
            hits={(searchQ.data ?? []) as AuditEventOut[]}
            loading={searchQ.isLoading}
          />
        )}
      </div>

      {/* Recent events table */}
      <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4 shadow-sm">
        <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
          <h3 className="text-sm font-semibold text-[var(--color-text-primary)] flex items-center gap-2">
            <Activity size={14} className="text-rose-600" />
            Recent events
            <InfoTooltip text="Most recent audit_events, newest first. Use the filters to narrow." />
          </h3>
          <div className="flex items-center gap-3 flex-wrap text-xs">
            <label className="inline-flex items-center gap-1 cursor-pointer">
              <input
                type="checkbox"
                checked={errorsOnly}
                onChange={(e) => setErrorsOnly(e.target.checked)}
                className="rounded"
              />
              Errors only
              <InfoTooltip text="response_status_code >= 400" />
            </label>
            <FilterPicker label="service" value={serviceFilter} options={serviceOptions} onChange={setServiceFilter} />
            <FilterPicker label="user" value={userFilter} options={userOptions} onChange={setUserFilter} />
            {(errorsOnly || serviceFilter || userFilter) && (
              <button
                onClick={() => { setErrorsOnly(false); setServiceFilter(''); setUserFilter(''); }}
                className="text-[10px] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] underline"
              >
                Reset filters
              </button>
            )}
          </div>
        </div>
        {recentQ.isLoading ? (
          <p className="text-xs text-[var(--color-text-muted)]"><Loader2 size={12} className="animate-spin inline mr-1" /> Loading…</p>
        ) : (recentQ.data ?? []).length === 0 ? (
          <p className="text-xs text-[var(--color-text-muted)] italic">No events match the current filters.</p>
        ) : (
          <RecentTable rows={recentQ.data ?? []} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

function TopList({
  title, subtitle, items, onPick, accent,
}: {
  title: string;
  subtitle: string;
  items: { label: string; count: number }[];
  onPick: (label: string) => void;
  accent: string;
}) {
  return (
    <div className="bg-white border border-[var(--color-border)] rounded-2xl p-3 shadow-sm">
      <h3 className="text-xs font-semibold text-[var(--color-text-primary)]" style={{ color: accent }}>
        {title}
      </h3>
      <p className="text-[10px] text-[var(--color-text-muted)] mt-0.5 mb-2">{subtitle}</p>
      <ul className="divide-y divide-[var(--color-border)]/60 max-h-72 overflow-auto">
        {items.length === 0 && (
          <li className="text-xs text-[var(--color-text-muted)] italic py-1.5">no rows</li>
        )}
        {items.map((it) => (
          <li key={it.label}>
            <button
              onClick={() => onPick(it.label)}
              className="w-full flex items-center justify-between gap-2 px-1.5 py-1 text-xs hover:bg-rose-50 text-left"
            >
              <span className="font-mono truncate" title={it.label}>{it.label}</span>
              <span className="shrink-0 text-[10px] text-[var(--color-text-muted)]">
                {numberFmt.format(it.count)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function FilterPicker({
  label, value, options, onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="inline-flex items-center gap-1">
      <span className="text-[var(--color-text-muted)]">{label}:</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-white border border-[var(--color-border)] rounded px-1.5 py-0.5 text-[11px] font-mono"
      >
        <option value="">(any)</option>
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </label>
  );
}

function RecentTable({ rows }: { rows: AuditEventOut[] }) {
  return (
    <div className="overflow-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] border-b border-[var(--color-border)]">
            <th className="text-left py-1.5 px-2">Time</th>
            <th className="text-left py-1.5 px-2">User</th>
            <th className="text-left py-1.5 px-2">Service</th>
            <th className="text-left py-1.5 px-2">Action</th>
            <th className="text-left py-1.5 px-2">Status</th>
            <th className="text-left py-1.5 px-2">Level</th>
            <th className="text-left py-1.5 px-2">Workspace</th>
            <th className="text-left py-1.5 px-2">Source IP</th>
            <th className="text-left py-1.5 px-2">Error</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const ok = r.response_status_code !== null && r.response_status_code !== undefined && r.response_status_code < 400;
            return (
              <tr key={r.event_id ?? r.request_id ?? r.event_time}
                className="border-b border-[var(--color-border)]/40 hover:bg-rose-50/40">
                <td className="py-1 px-2 font-mono">{r.event_time?.replace('T', ' ').slice(0, 19) ?? ''}</td>
                <td className="py-1 px-2 font-mono truncate max-w-[180px]" title={r.user_identity_email ?? ''}>
                  {r.user_identity_email ?? ''}
                </td>
                <td className="py-1 px-2">{r.service_name}</td>
                <td className="py-1 px-2 font-mono">{r.action_name}</td>
                <td className="py-1 px-2 font-mono flex items-center gap-1">
                  {ok
                    ? <CheckCircle2 size={10} className="text-emerald-600" />
                    : <XCircle size={10} className="text-red-600" />}
                  {r.response_status_code ?? ''}
                </td>
                <td className="py-1 px-2 text-[10px] uppercase">{r.audit_level}</td>
                <td className="py-1 px-2 font-mono">{r.workspace_id}</td>
                <td className="py-1 px-2 font-mono">{r.source_ip_address}</td>
                <td className="py-1 px-2 truncate max-w-[180px] text-red-700" title={r.response_error_message ?? ''}>
                  {r.response_error_message ?? ''}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SearchResults({ hits, loading }: { hits: AuditEventOut[]; loading: boolean }) {
  if (loading) return <p className="text-xs text-[var(--color-text-muted)]"><Loader2 size={12} className="animate-spin inline mr-1" /> Searching…</p>;
  if (hits.length === 0) return <p className="text-xs text-[var(--color-text-muted)]">No matches.</p>;
  return (
    <div className="border border-[var(--color-border)] rounded-lg max-h-64 overflow-auto">
      <RecentTable rows={hits} />
    </div>
  );
}
