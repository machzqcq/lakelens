/**
 * useFeatures — fetches the global feature-flag state map and exposes a
 * single `isEnabled(key)` predicate. Backs the sidebar visibility logic and
 * any per-page gating that wants to read flags.
 *
 * The endpoint is non-admin (any signed-in user can ask) and the response
 * is cached with React Query's default stale time. Unknown keys default to
 * true so a missing/loading state never accidentally hides core UI.
 */
import { useQuery } from '@tanstack/react-query';
import { fetchFeatureState } from '../api/client';

export interface UseFeaturesResult {
  isEnabled: (key: string) => boolean;
  isLoading: boolean;
  features: Record<string, boolean>;
}

export function useFeatures(): UseFeaturesResult {
  const q = useQuery({
    queryKey: ['feature-state'],
    queryFn: fetchFeatureState,
    staleTime: 60_000,
  });
  const map = q.data?.features ?? {};
  return {
    isEnabled: (key: string) => map[key] !== false,  // unknown → on
    isLoading: q.isLoading,
    features: map,
  };
}
