/**
 * Top-right notifications bell. Polls /api/data-ops/jobs for the current
 * user's recent background jobs (extracts, loads, deletes, query-intel ETL).
 *
 * Behavior:
 *   - Badge: count of jobs with status 'queued' or 'running'.
 *   - Dropdown lists most-recent first with: kind, status pill, progress
 *     bar, message, started_at, [Cancel] button when in-flight.
 *   - Poll cadence: 3s when dropdown open, 15s when closed. Pauses when
 *     the tab is hidden (document.hidden) and resumes on focus.
 *   - Survives navigation + reload because state is in Postgres, not in
 *     React state.
 */
import { useEffect, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Bell, Check, X, Loader2, AlertCircle, CircleSlash, ChevronDown } from 'lucide-react';
import { listJobs, cancelJob, type BackgroundJob } from '../api/client';

const POLL_OPEN_MS = 3000;
const POLL_CLOSED_MS = 15000;

function fmtAgo(iso: string): string {
  const dt = new Date(iso).getTime();
  const ago = Math.max(0, (Date.now() - dt) / 1000);
  if (ago < 60) return `${Math.round(ago)}s ago`;
  if (ago < 3600) return `${Math.round(ago / 60)}m ago`;
  if (ago < 86400) return `${Math.round(ago / 3600)}h ago`;
  return `${Math.round(ago / 86400)}d ago`;
}

function statusPill(status: BackgroundJob['status']) {
  const map: Record<BackgroundJob['status'], { color: string; bg: string; icon: any; label: string }> = {
    queued:   { color: 'text-yellow-700', bg: 'bg-yellow-100', icon: Loader2, label: 'Queued' },
    running:  { color: 'text-blue-700',   bg: 'bg-blue-100',   icon: Loader2, label: 'Running' },
    success:  { color: 'text-green-700',  bg: 'bg-green-100',  icon: Check,   label: 'Done' },
    failed:   { color: 'text-red-700',    bg: 'bg-red-100',    icon: AlertCircle, label: 'Failed' },
    canceled: { color: 'text-gray-700',   bg: 'bg-gray-100',   icon: CircleSlash, label: 'Canceled' },
    lost:     { color: 'text-orange-700', bg: 'bg-orange-100', icon: AlertCircle, label: 'Lost' },
  };
  const s = map[status];
  const Icon = s.icon;
  const animate = status === 'running' || status === 'queued';
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${s.color} ${s.bg}`}>
      <Icon size={10} className={animate ? 'animate-spin' : ''} />
      {s.label}
    </span>
  );
}

export default function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const ref = useRef<HTMLDivElement>(null);

  const jobsQ = useQuery({
    queryKey: ['data-ops-jobs'],
    queryFn: () => listJobs(24, 50),
    refetchInterval: () => (document.hidden ? false : (open ? POLL_OPEN_MS : POLL_CLOSED_MS)),
    refetchOnWindowFocus: true,
  });

  const cancelM = useMutation({
    mutationFn: (id: number) => cancelJob(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['data-ops-jobs'] }),
  });

  // Close when clicking outside
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const jobs = jobsQ.data ?? [];
  const inflight = jobs.filter((j) => j.status === 'queued' || j.status === 'running').length;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative w-9 h-9 rounded-full flex items-center justify-center hover:bg-[var(--color-bg-secondary)] transition-colors"
        title="Background jobs"
      >
        <Bell size={18} className="text-[var(--color-text-secondary)]" />
        {inflight > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-[var(--color-primary)] text-white text-[10px] font-semibold flex items-center justify-center">
            {inflight}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-[400px] max-h-[520px] bg-white rounded-2xl border border-[var(--color-border)] shadow-xl z-50 overflow-hidden flex flex-col">
          <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Background Jobs</h3>
              <p className="text-[11px] text-[var(--color-text-muted)]">
                {inflight > 0 ? `${inflight} in progress` : 'No active jobs'} · last 24h
              </p>
            </div>
            <button onClick={() => setOpen(false)} className="p-1 rounded hover:bg-[var(--color-bg-secondary)]">
              <ChevronDown size={14} className="text-[var(--color-text-muted)]" />
            </button>
          </div>

          <div className="overflow-y-auto flex-1 divide-y divide-[var(--color-border)]">
            {jobsQ.isLoading ? (
              <p className="p-4 text-xs text-[var(--color-text-muted)]">Loading…</p>
            ) : jobs.length === 0 ? (
              <p className="p-6 text-center text-xs text-[var(--color-text-muted)]">No background jobs in the last 24 hours.</p>
            ) : (
              jobs.map((j) => <JobRow key={j.id} job={j} onCancel={() => cancelM.mutate(j.id)} />)
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function JobRow({ job, onCancel }: { job: BackgroundJob; onCancel: () => void }) {
  const inflight = job.status === 'queued' || job.status === 'running';
  const pct = Math.max(0, Math.min(100, Number(job.progress_pct) || 0));
  return (
    <div className="px-4 py-3 hover:bg-[var(--color-bg-secondary)]">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-xs font-medium text-[var(--color-text-primary)] truncate" title={job.kind}>{job.kind}</span>
        <div className="flex items-center gap-2 shrink-0">
          {statusPill(job.status)}
          {inflight && !job.cancel_requested && (
            <button onClick={onCancel} className="p-1 rounded hover:bg-red-50 text-red-500" title="Request cancel">
              <X size={12} />
            </button>
          )}
        </div>
      </div>
      {inflight && (
        <div className="w-full h-1.5 rounded-full bg-[var(--color-bg-secondary)] overflow-hidden">
          <div
            className="h-full bg-[var(--color-primary)] transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
      <div className="flex items-center justify-between mt-1">
        <span className="text-[10px] text-[var(--color-text-muted)] truncate flex-1" title={job.message ?? ''}>
          {job.message ?? (job.status === 'success' ? 'Completed' : job.error_message ?? '')}
        </span>
        <span className="text-[10px] text-[var(--color-text-muted)] ml-2">{fmtAgo(job.started_at)}</span>
      </div>
      {inflight && (job.current_step != null || job.total_steps != null) && (
        <p className="text-[10px] text-[var(--color-text-muted)] mt-0.5">
          step {job.current_step ?? '?'} / {job.total_steps ?? '?'} · {pct.toFixed(0)}%
        </p>
      )}
    </div>
  );
}
