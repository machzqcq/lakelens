/**
 * ProgressCard — renders a single live operation from /api/data-ops/progress.
 *
 * Designed to sit alongside the action buttons that triggered the run so the
 * user immediately sees "where are we" instead of just a spinner. Auto-hides
 * a few seconds after the run reaches a terminal state (handled by the
 * server-side TTL).
 *
 * Cancel button: when `status === 'running'`, an X-button sits to the right
 * of the elapsed-time chip. Clicking it POSTs to /data-ops/progress/{kind}/cancel
 * — the server flips the cancel flag, a watcher coroutine cancels the in-flight
 * work task, and the entry transitions to the 'cancelled' terminal state. Between
 * the click and that transition we show "Cancelling…" + a disabled button so
 * the user knows the request was received.
 */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, Loader2, X, XCircle, Ban } from 'lucide-react';
import { cancelProgress, type ProgressEntry } from '../api/client';

const numberFmt = new Intl.NumberFormat('en-US');

export function ProgressCard({ entry }: { entry: ProgressEntry }) {
  const queryClient = useQueryClient();
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelInFlight, setCancelInFlight] = useState(false);

  const pct = entry.total_steps > 0
    ? Math.min(100, Math.round((entry.current_step / entry.total_steps) * 100))
    : (entry.status === 'success' ? 100 : 0);
  const palette = entry.status === 'failed'
    ? { bar: 'bg-red-500',     text: 'text-red-800',     bg: 'bg-red-50',     border: 'border-red-200',     Icon: XCircle }
    : entry.status === 'success'
    ? { bar: 'bg-emerald-500', text: 'text-emerald-900', bg: 'bg-emerald-50', border: 'border-emerald-200', Icon: CheckCircle2 }
    : entry.status === 'cancelled'
    ? { bar: 'bg-slate-400',   text: 'text-slate-700',   bg: 'bg-slate-50',   border: 'border-slate-200',   Icon: Ban }
    : { bar: 'bg-fuchsia-500', text: 'text-fuchsia-900', bg: 'bg-fuchsia-50', border: 'border-fuchsia-200', Icon: Loader2 };
  const Icon = palette.Icon;

  const isRunning = entry.status === 'running';
  // The server may already have flipped cancel_requested before our click
  // — fold both signals into one local "we're cancelling" state.
  const cancelling = isRunning && (entry.cancel_requested || cancelInFlight);

  const handleCancel = async () => {
    setCancelError(null);
    setCancelInFlight(true);
    try {
      await cancelProgress(entry.kind);
      // Force a fresh poll so the UI flips to 'Cancelling…' immediately.
      await queryClient.invalidateQueries({ queryKey: ['progress'] });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setCancelError(msg);
    } finally {
      setCancelInFlight(false);
    }
  };

  return (
    <div className={`${palette.bg} ${palette.border} border rounded-2xl px-4 py-3 shadow-sm`}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <Icon
            size={14}
            className={`shrink-0 ${palette.text} ${entry.status === 'running' ? 'animate-spin' : ''}`}
          />
          <span className={`text-sm font-semibold ${palette.text} truncate`} title={entry.label}>
            {entry.label}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className={`text-[10px] uppercase tracking-wide ${palette.text}/80`}>
            {cancelling ? 'cancelling' : entry.status} · {entry.elapsed_seconds.toFixed(1)}s
          </div>
          {isRunning && (
            <button
              type="button"
              onClick={handleCancel}
              disabled={cancelling}
              title={cancelling ? 'Cancellation in progress…' : 'Cancel this operation'}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border transition-colors ${
                cancelling
                  ? 'bg-white/70 text-slate-500 border-slate-200 cursor-wait'
                  : 'bg-white text-red-700 border-red-200 hover:bg-red-50 hover:border-red-300'
              }`}
            >
              <X size={11} />
              {cancelling ? 'Cancelling…' : 'Cancel'}
            </button>
          )}
        </div>
      </div>

      <div className="mt-2 h-2 bg-white rounded">
        <div
          className={`${palette.bar} h-full rounded transition-all`}
          style={{ width: `${Math.max(2, pct)}%` }}
        />
      </div>
      <div className="mt-1 flex items-center justify-between text-[11px] font-mono">
        <span className={`${palette.text}/90 truncate`} title={entry.last_message}>
          {entry.last_message || '…'}
        </span>
        <span className={`${palette.text}/70 shrink-0 ml-2`}>
          {entry.total_steps > 0
            ? `${numberFmt.format(entry.current_step)} / ${numberFmt.format(entry.total_steps)}`
            : `step ${numberFmt.format(entry.current_step)}`}
          {' '}({pct}%)
        </span>
      </div>

      {entry.error && (
        <p className="mt-2 text-[11px] text-red-800 bg-red-100 border border-red-200 rounded px-2 py-1">
          {entry.error}
        </p>
      )}
      {cancelError && (
        <p className="mt-2 text-[11px] text-red-800 bg-red-100 border border-red-200 rounded px-2 py-1">
          Cancel failed: {cancelError}
        </p>
      )}
    </div>
  );
}

export function ProgressList({ entries }: { entries: ProgressEntry[] }) {
  if (entries.length === 0) return null;
  return (
    <div className="space-y-2">
      {entries.map((e) => <ProgressCard key={e.kind} entry={e} />)}
    </div>
  );
}
