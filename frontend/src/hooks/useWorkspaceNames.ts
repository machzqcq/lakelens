import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchWorkspaceMeta, type WorkspaceMeta } from '../api/client';

export interface WorkspaceNameResolver {
  /** Returns the workspace name if known, otherwise the workspace id unchanged. */
  (workspaceId: string | null | undefined): string;
}

export interface WorkspaceNamesHook {
  resolver: WorkspaceNameResolver;
  /** Build a label like "name (id)" when name is known, else just the id. */
  label: (workspaceId: string | null | undefined) => string;
  /** Raw map workspace_id → workspace_name (name may be null). */
  byId: Map<string, WorkspaceMeta>;
  isLoading: boolean;
}

/**
 * Resolves workspace_id → workspace_name for chart labels, tooltips, drill-downs.
 * Data is cached for 10 min — workspace metadata changes rarely.
 *
 * Pattern:
 *   const { resolver: wsName, label: wsLabel } = useWorkspaceNames();
 *   <span title={id}>{wsName(id)}</span>
 *   <td>{wsLabel(id)}</td>   // "Eng (1234567890)"
 */
export function useWorkspaceNames(): WorkspaceNamesHook {
  const q = useQuery({
    queryKey: ['ws-meta'],
    queryFn: fetchWorkspaceMeta,
    staleTime: 1000 * 60 * 10,
  });

  const byId = useMemo(() => {
    const m = new Map<string, WorkspaceMeta>();
    for (const w of q.data ?? []) m.set(w.workspace_id, w);
    return m;
  }, [q.data]);

  return useMemo<WorkspaceNamesHook>(() => {
    const resolver: WorkspaceNameResolver = (id) => {
      if (id == null) return '';
      const w = byId.get(String(id));
      return w?.workspace_name || String(id);
    };
    const label = (id: string | null | undefined): string => {
      if (id == null) return '';
      const w = byId.get(String(id));
      return w?.workspace_name ? `${w.workspace_name} (${id})` : String(id);
    };
    return { resolver, label, byId, isLoading: q.isLoading };
  }, [byId, q.isLoading]);
}
