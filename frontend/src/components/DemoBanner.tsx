/**
 * Sticky yellow banner shown at the top of every protected page when the
 * current user's `viewing_data_mode === 'demo'`. The toggle next to it
 * flips back to real with a single click. Backend filters reads on the
 * server side based on the same setting.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, RefreshCcw } from 'lucide-react';
import { getViewMode, setViewMode } from '../api/client';

export default function DemoBanner() {
  const queryClient = useQueryClient();
  const vm = useQuery({ queryKey: ['view-mode'], queryFn: getViewMode });

  const flip = useMutation({
    mutationFn: () => setViewMode('real'),
    onSuccess: async () => {
      // Refresh every query so charts reflect real data immediately.
      await queryClient.invalidateQueries();
    },
  });

  if (!vm.data || vm.data.mode !== 'demo') return null;

  return (
    <div className="bg-yellow-100 border-b border-yellow-300 px-6 py-2 flex items-center justify-center gap-3 text-yellow-900">
      <AlertTriangle size={16} />
      <span className="text-sm font-medium">
        You are viewing <strong>DEMO</strong> data. Real Databricks data is hidden.
      </span>
      <button
        onClick={() => flip.mutate()}
        disabled={flip.isPending}
        className="ml-3 flex items-center gap-1 px-3 py-1 rounded-full bg-yellow-300 hover:bg-yellow-400 text-yellow-900 text-xs font-semibold transition-colors disabled:opacity-50"
      >
        <RefreshCcw size={12} />
        {flip.isPending ? 'Switching…' : 'Switch to Real Data'}
      </button>
    </div>
  );
}
