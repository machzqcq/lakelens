/**
 * Top-bar segment toggle for the active view mode (Real vs Demo).
 * Sticky per-user setting; persisted to Postgres on PATCH. Switching
 * invalidates every cached query so charts redraw with the new mode.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Database, Sparkles } from 'lucide-react';
import { getViewMode, setViewMode, type DataOrigin } from '../api/client';

export default function ViewModeToggle() {
  const queryClient = useQueryClient();
  const vm = useQuery({ queryKey: ['view-mode'], queryFn: getViewMode });

  const set = useMutation({
    mutationFn: (mode: DataOrigin) => setViewMode(mode),
    onSuccess: async (data) => {
      queryClient.setQueryData(['view-mode'], data);
      await queryClient.invalidateQueries();
    },
  });

  const current = vm.data?.mode ?? 'real';

  return (
    <div className="inline-flex items-center bg-[var(--color-bg-secondary)] rounded-full border border-[var(--color-border)] p-0.5">
      <button
        onClick={() => current !== 'real' && set.mutate('real')}
        disabled={set.isPending}
        className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-colors ${
          current === 'real'
            ? 'bg-white text-[var(--color-text-primary)] shadow-sm'
            : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]'
        }`}
        title="Show real Databricks data"
      >
        <Database size={12} /> Real
      </button>
      <button
        onClick={() => current !== 'demo' && set.mutate('demo')}
        disabled={set.isPending}
        className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-colors ${
          current === 'demo'
            ? 'bg-yellow-300 text-yellow-900 shadow-sm'
            : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]'
        }`}
        title="Show Acme Corp demo data"
      >
        <Sparkles size={12} /> Demo
      </button>
    </div>
  );
}
