/**
 * useProgress — polls the live progress map from /api/data-ops/progress.
 *
 * Pass `active` to toggle the polling cadence: while any mutation is pending,
 * the page sets `active=true` and we refetch every ~1.2s; otherwise we slow
 * to ~6s so the tail-end "success" / "failed" states are still picked up.
 *
 * The polling cadence is intentionally a little slower than typical UI feel
 * — it's I/O-bound and we don't want a tight client loop hammering the
 * server during a long extract.
 */
import { useQuery } from '@tanstack/react-query';
import { fetchProgress, type ProgressEntry } from '../api/client';

const ACTIVE_INTERVAL_MS = 1200;
const IDLE_INTERVAL_MS   = 6000;

export interface UseProgressResult {
  byKind: Record<string, ProgressEntry>;
  running: ProgressEntry[];
  isLoading: boolean;
}

export function useProgress(active: boolean = false): UseProgressResult {
  const q = useQuery({
    queryKey: ['progress'],
    queryFn: fetchProgress,
    refetchInterval: active ? ACTIVE_INTERVAL_MS : IDLE_INTERVAL_MS,
    // Don't keep stale entries on mount — we want a fresh read so the UI
    // doesn't show ghost progress from a previous run.
    staleTime: 0,
  });
  const byKind = q.data ?? {};
  const running = Object.values(byKind).filter((e) => e.status === 'running');
  return { byKind, running, isLoading: q.isLoading };
}
