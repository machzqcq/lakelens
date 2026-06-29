import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Shield, Trash2, Plus, Save, X, AlertCircle, Loader2, AlertTriangle,
  ChevronDown, ChevronRight, ToggleRight, Layout, Server,
} from 'lucide-react';
import {
  type AdminRole,
  type FilterDimensions,
  type FeatureRegistryEntry,
  adminCreateRole,
  adminDeleteRole,
  adminFeatureRegistry,
  adminFilterDimensions,
  adminListRoles,
  adminPatchRole,
} from '../../api/client';

interface FilterState {
  workspace_ids: string[];
  clouds: string[];
  billing_origins: string[];
  cluster_sources: string[];
  sku_name_pattern: string;
  // Coarse-grained access toggles for the two large/sensitive datasets.
  // Off by default — must be explicitly granted on roles intended for
  // IT-Admin personas, since both span the entire Databricks workspace.
  allow_query_history: boolean;
  allow_databricks_meta: boolean;
}

const EMPTY_FILTERS: FilterState = {
  workspace_ids: [],
  clouds: [],
  billing_origins: [],
  cluster_sources: [],
  sku_name_pattern: '',
  allow_query_history: false,
  allow_databricks_meta: false,
};

function filtersFromRole(role: AdminRole): FilterState {
  const f = (role.filters ?? {}) as Partial<{
    workspace_ids: string[]; clouds: string[]; billing_origins: string[];
    cluster_sources: string[]; sku_name_pattern: string;
    allow_query_history: boolean; allow_databricks_meta: boolean;
  }>;
  return {
    workspace_ids: f.workspace_ids ?? [],
    clouds: f.clouds ?? [],
    billing_origins: f.billing_origins ?? [],
    cluster_sources: f.cluster_sources ?? [],
    sku_name_pattern: f.sku_name_pattern ?? '',
    allow_query_history: !!f.allow_query_history,
    allow_databricks_meta: !!f.allow_databricks_meta,
  };
}

function filtersToPayload(f: FilterState): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (f.workspace_ids.length) out.workspace_ids = f.workspace_ids;
  if (f.clouds.length) out.clouds = f.clouds;
  if (f.billing_origins.length) out.billing_origins = f.billing_origins;
  if (f.cluster_sources.length) out.cluster_sources = f.cluster_sources;
  if (f.sku_name_pattern.trim()) out.sku_name_pattern = f.sku_name_pattern.trim();
  // Only emit positive grants. Absence on the role means "no opinion"; the
  // existing union-of-permissions semantic decides effective access.
  if (f.allow_query_history) out.allow_query_history = true;
  if (f.allow_databricks_meta) out.allow_databricks_meta = true;
  return out;
}

export default function AdminRoles() {
  const qc = useQueryClient();
  const rolesQ = useQuery({ queryKey: ['admin-roles'], queryFn: adminListRoles });
  const dimsQ = useQuery({ queryKey: ['admin-filter-dimensions'], queryFn: adminFilterDimensions });
  const featuresQ = useQuery({
    queryKey: ['admin-feature-registry'],
    queryFn: adminFeatureRegistry,
    staleTime: 5 * 60_000,
  });
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Refresh per-user feature state any time a role mutation may have shifted
  // it (the calling user's own role list could include the edited role).
  const onMutationSuccess = () => {
    qc.invalidateQueries({ queryKey: ['admin-roles'] });
    qc.invalidateQueries({ queryKey: ['feature-state'] });
  };

  const createMut = useMutation({
    mutationFn: (req: Parameters<typeof adminCreateRole>[0]) => adminCreateRole(req),
    onSuccess: () => { onMutationSuccess(); setCreating(false); },
    onError: (e: Error) => setError(e.message),
  });
  const patchMut = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Parameters<typeof adminPatchRole>[1] }) => adminPatchRole(id, patch),
    onSuccess: () => { onMutationSuccess(); setEditingId(null); },
    onError: (e: Error) => setError(e.message),
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => adminDeleteRole(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-roles'] }),
    onError: (e: Error) => setError(e.message),
  });

  const roles = rolesQ.data ?? [];

  return (
    <div className="space-y-5 max-w-[1200px]">
      <div className="flex items-center justify-between gap-3 pr-14">
        <div className="flex items-center gap-3">
          <Shield size={24} className="text-[var(--color-primary)]" />
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Roles</h1>
        </div>
        {!creating && (
          <button onClick={() => { setEditingId(null); setCreating(true); setError(null); }}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--color-primary)] text-white text-sm">
            <Plus size={14} /> New role
          </button>
        )}
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-2xl px-4 py-3 text-xs text-[var(--color-text-secondary)]">
        Custom roles attach a <strong>data-scope filter</strong>. Users with the role only see data
        matching the filter across the entire app. <code>admin</code> bypasses all filters; <code>user</code>
        is unrestricted by default. Multi-role users see the union of allowed values per dimension.
      </div>

      {error && (
        <div className="flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
          <AlertCircle size={14} className="shrink-0 mt-0.5" /><span>{error}</span>
        </div>
      )}

      {creating && (
        <RoleEditor
          mode="create"
          initial={null}
          dims={dimsQ.data}
          featureRegistry={featuresQ.data?.features ?? []}
          submitting={createMut.isPending}
          onCancel={() => setCreating(false)}
          onSubmit={(payload) => createMut.mutate(payload)}
        />
      )}

      {rolesQ.isLoading ? (
        <p className="text-sm text-[var(--color-text-muted)]">Loading roles...</p>
      ) : (
        <div className="space-y-3">
          {roles.map((r: AdminRole) =>
            editingId === r.id ? (
              <RoleEditor
                key={r.id}
                mode="edit"
                initial={r}
                dims={dimsQ.data}
                featureRegistry={featuresQ.data?.features ?? []}
                submitting={patchMut.isPending}
                onCancel={() => setEditingId(null)}
                onSubmit={(payload) => patchMut.mutate({
                  id: r.id,
                  patch: {
                    description: payload.description,
                    filters: payload.filters,
                    features: payload.features,
                  },
                })}
              />
            ) : (
              <RoleCard
                key={r.id}
                role={r}
                onEdit={() => { setCreating(false); setEditingId(r.id); setError(null); }}
                onDelete={() => {
                  if (confirm(`Delete role "${r.name}"? Users will keep their other roles.`)) {
                    deleteMut.mutate(r.id);
                  }
                }}
              />
            )
          )}
        </div>
      )}
    </div>
  );
}

function RoleCard({ role, onEdit, onDelete }: { role: AdminRole; onEdit: () => void; onDelete: () => void }) {
  const filters = filtersFromRole(role);
  const dimSummary = ((): string => {
    const parts: string[] = [];
    if (filters.workspace_ids.length) parts.push(`${filters.workspace_ids.length} workspace${filters.workspace_ids.length === 1 ? '' : 's'}`);
    if (filters.clouds.length) parts.push(`${filters.clouds.length} cloud${filters.clouds.length === 1 ? '' : 's'}`);
    if (filters.billing_origins.length) parts.push(`${filters.billing_origins.length} origin${filters.billing_origins.length === 1 ? '' : 's'}`);
    if (filters.cluster_sources.length) parts.push(`${filters.cluster_sources.length} source${filters.cluster_sources.length === 1 ? '' : 's'}`);
    if (filters.sku_name_pattern) parts.push('SKU pattern');
    return parts.length ? parts.join(' · ') : (role.is_system ? 'unrestricted' : 'no filter set');
  })();
  const itAdminScopes = [
    filters.allow_query_history && 'query history',
    filters.allow_databricks_meta && 'databricks meta',
  ].filter(Boolean) as string[];

  // features=null means 'grants everything'; an explicit list shows the count.
  const featureSummary = role.features === null
    ? 'all features'
    : `${role.features.length} feature${role.features.length === 1 ? '' : 's'} granted`;

  return (
    <div className="bg-white border border-[var(--color-border)] rounded-2xl p-4">
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-semibold text-[var(--color-text-primary)] font-mono">{role.name}</span>
          {role.is_system && (
            <span className="text-[10px] font-semibold uppercase rounded-full px-1.5 py-0.5 bg-gray-200 text-gray-700">system</span>
          )}
          <span className="text-[10px] text-[var(--color-text-muted)]">· {role.user_count} user{role.user_count === 1 ? '' : 's'}</span>
        </div>
        <div className="flex items-center gap-1">
          {!role.is_system && (
            <>
              <button onClick={onEdit} className="text-xs px-2 py-1 rounded text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]">Edit</button>
              <button onClick={onDelete} className="p-1.5 rounded text-[var(--color-text-muted)] hover:text-red-600 hover:bg-red-50">
                <Trash2 size={14} />
              </button>
            </>
          )}
        </div>
      </div>
      {role.description && <p className="text-xs text-[var(--color-text-secondary)] mb-2">{role.description}</p>}
      <p className="text-[10px] text-[var(--color-text-muted)] uppercase tracking-wider">Scope: {dimSummary}</p>
      <p className="text-[10px] text-[var(--color-text-muted)] uppercase tracking-wider mt-0.5">
        Features: {featureSummary}
      </p>
      {itAdminScopes.length > 0 && (
        <p className="text-[10px] mt-1 text-amber-700 uppercase tracking-wider">
          IT&nbsp;Admin grants: {itAdminScopes.join(' + ')}
        </p>
      )}
    </div>
  );
}

interface EditorPayload {
  name: string;
  description?: string;
  filters: Record<string, unknown>;
  features: string[];
}

function RoleEditor({
  mode, initial, dims, featureRegistry, submitting, onCancel, onSubmit,
}: {
  mode: 'create' | 'edit';
  initial: AdminRole | null;
  dims: FilterDimensions | undefined;
  featureRegistry: FeatureRegistryEntry[];
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (p: EditorPayload) => void;
}) {
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [filters, setFilters] = useState<FilterState>(initial ? filtersFromRole(initial) : EMPTY_FILTERS);

  // Feature keys this role grants. A new role starts with every registered
  // key enabled (the user can uncheck to restrict). Editing an existing role
  // pre-fills from the stored list; `features === null` (legacy roles) also
  // counts as "everything enabled".
  const initialFeatureSet = (): Set<string> => {
    const all = new Set(featureRegistry.map((f) => f.key));
    if (initial == null) return all;
    if (initial.features == null) return all;
    return new Set(initial.features);
  };
  const [enabledFeatures, setEnabledFeatures] = useState<Set<string>>(initialFeatureSet);

  // Reset state when switching between create/edit OR when the registry
  // finishes loading (so the "all checked by default" applies after the
  // network round-trip, not just to the empty initial render).
  useEffect(() => {
    setName(initial?.name ?? '');
    setDescription(initial?.description ?? '');
    setFilters(initial ? filtersFromRole(initial) : EMPTY_FILTERS);
    setEnabledFeatures(initialFeatureSet());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial, featureRegistry.length]);

  function toggle(dim: keyof Omit<FilterState, 'sku_name_pattern' | 'allow_query_history' | 'allow_databricks_meta'>, value: string) {
    setFilters((f) => {
      const set = new Set(f[dim] as string[]);
      if (set.has(value)) set.delete(value);
      else set.add(value);
      return { ...f, [dim]: [...set].sort() };
    });
  }

  function toggleFeature(key: string) {
    setEnabledFeatures((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    onSubmit({
      name: name.trim().toLowerCase(),
      description: description.trim() || undefined,
      filters: filtersToPayload(filters),
      features: [...enabledFeatures].sort(),
    });
  }

  return (
    <form onSubmit={submit} className="bg-white border-2 border-[var(--color-primary)]/40 rounded-2xl p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
          {mode === 'create' ? 'New role' : `Edit "${initial?.name}"`}
        </h3>
        <button type="button" onClick={onCancel}
          className="p-1 rounded text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)]">
          <X size={16} />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="block text-sm">
          <span className="text-xs text-[var(--color-text-muted)]">Name</span>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} required
            disabled={mode === 'edit'} pattern="[a-z0-9_-]+" minLength={2} maxLength={64}
            placeholder="e.g. finance-readonly"
            className="mt-1 w-full bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm font-mono disabled:bg-gray-50" />
        </label>
        <label className="block text-sm">
          <span className="text-xs text-[var(--color-text-muted)]">Description</span>
          <input type="text" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500}
            className="mt-1 w-full bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm" />
        </label>
      </div>

      <div className="border-t border-[var(--color-border)] pt-3 space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Data-scope filters <span className="font-normal normal-case lowercase tracking-normal text-[10px]">(empty = unrestricted)</span>
        </p>

        <FilterGroup label="Workspaces" values={dims?.workspace_ids ?? []} selected={filters.workspace_ids} onToggle={(v) => toggle('workspace_ids', v)} />
        <FilterGroup label="Clouds" values={dims?.clouds ?? []} selected={filters.clouds} onToggle={(v) => toggle('clouds', v)} />
        <FilterGroup label="Billing origins" values={dims?.billing_origins ?? []} selected={filters.billing_origins} onToggle={(v) => toggle('billing_origins', v)} />
        <FilterGroup label="Cluster sources" values={dims?.cluster_sources ?? []} selected={filters.cluster_sources} onToggle={(v) => toggle('cluster_sources', v)} />

        <label className="block text-sm">
          <span className="text-xs text-[var(--color-text-muted)]">SKU name pattern (SQL LIKE, e.g. "PREMIUM%")</span>
          <input type="text" value={filters.sku_name_pattern}
            onChange={(e) => setFilters((f) => ({ ...f, sku_name_pattern: e.target.value }))}
            placeholder="leave empty for no SKU restriction"
            className="mt-1 w-full bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm font-mono" />
        </label>
      </div>

      <ItAdminScopeSection
        allowQueryHistory={filters.allow_query_history}
        allowDatabricksMeta={filters.allow_databricks_meta}
        onToggleQueryHistory={() =>
          setFilters((f) => ({ ...f, allow_query_history: !f.allow_query_history }))
        }
        onToggleDatabricksMeta={() =>
          setFilters((f) => ({ ...f, allow_databricks_meta: !f.allow_databricks_meta }))
        }
      />

      <FeatureToggleSection
        registry={featureRegistry}
        enabled={enabledFeatures}
        onToggle={toggleFeature}
        onSetAll={(on) =>
          setEnabledFeatures(new Set(on ? featureRegistry.map((f) => f.key) : []))
        }
      />

      <div className="flex justify-end gap-2 border-t border-[var(--color-border)] pt-3">
        <button type="button" onClick={onCancel}
          className="px-3 py-1.5 rounded-lg text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]">
          Cancel
        </button>
        <button type="submit" disabled={submitting}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--color-primary)] text-white text-sm disabled:opacity-50">
          {submitting ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          {mode === 'create' ? 'Save role' : 'Save changes'}
        </button>
      </div>
    </form>
  );
}

function ItAdminScopeSection({
  allowQueryHistory,
  allowDatabricksMeta,
  onToggleQueryHistory,
  onToggleDatabricksMeta,
}: {
  allowQueryHistory: boolean;
  allowDatabricksMeta: boolean;
  onToggleQueryHistory: () => void;
  onToggleDatabricksMeta: () => void;
}) {
  return (
    <div className="border-t border-[var(--color-border)] pt-3 space-y-3">
      <div className="flex items-start gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          IT&nbsp;Admin scopes
          <span className="font-normal normal-case lowercase tracking-normal text-[10px]">
            {' '}(grant cautiously)
          </span>
        </p>
      </div>

      <div className="flex items-start gap-2 text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-2.5">
        <AlertTriangle size={14} className="shrink-0 mt-0.5 text-amber-600" />
        <span>
          These two datasets span the <strong>entire Databricks workspace</strong> rather than
          billing-scoped slices — query history can include customer SQL, and meta enumerates every
          catalog/schema/table/column. Intended for IT&nbsp;Admin-style roles only. Leave both
          unchecked for finance / analytics / read-only roles.
        </span>
      </div>

      <ScopeToggle
        checked={allowQueryHistory}
        onChange={onToggleQueryHistory}
        title="Query History (qh / qi_*)"
        description="Access to query_history and the derived qi_* analytics tables (Query Profiler, statement search, error breakdowns)."
      />
      <ScopeToggle
        checked={allowDatabricksMeta}
        onChange={onToggleDatabricksMeta}
        title="Databricks Meta (Unity Catalog snapshot)"
        description="Access to databricks_meta — every catalog / database / table / column the extractor saw. Powers the Meta Explorer page and chatbot table suggestions."
      />
    </div>
  );
}

function ScopeToggle({
  checked, onChange, title, description,
}: {
  checked: boolean;
  onChange: () => void;
  title: string;
  description: string;
}) {
  return (
    <label className="flex items-start gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/40 p-3 cursor-pointer hover:border-[var(--color-primary)]/40">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="mt-0.5 accent-[var(--color-primary)] shrink-0"
      />
      <span className="min-w-0">
        <span className="block text-sm font-medium text-[var(--color-text-primary)]">{title}</span>
        <span className="block text-[11px] text-[var(--color-text-secondary)] mt-0.5">
          {description}
        </span>
      </span>
    </label>
  );
}

function FeatureToggleSection({
  registry, enabled, onToggle, onSetAll,
}: {
  registry: FeatureRegistryEntry[];
  enabled: Set<string>;
  onToggle: (key: string) => void;
  onSetAll: (on: boolean) => void;
}) {
  // Collapsed by default per spec — the matrix is long, and the typical
  // role doesn't need to narrow features. Expand to customize.
  const [open, setOpen] = useState(false);

  const frontend = registry.filter((f) => f.category === 'frontend');
  const backend = registry.filter((f) => f.category === 'backend');
  const onCount = registry.filter((f) => enabled.has(f.key)).length;

  return (
    <div className="border-t border-[var(--color-border)] pt-3 space-y-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-3 text-left rounded-lg p-2 -mx-2 hover:bg-[var(--color-bg-secondary)]/40"
      >
        <span className="flex items-center gap-2">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <ToggleRight size={16} className="text-teal-500" />
          <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            Toggle Features
          </span>
          <span className="text-[10px] font-normal normal-case lowercase tracking-normal text-[var(--color-text-muted)]">
            {onCount} of {registry.length} enabled
          </span>
        </span>
      </button>

      {open && (
        <div className="space-y-3">
          <div className="flex items-start gap-2 text-[11px] text-teal-900 bg-teal-50 border border-teal-200 rounded-lg p-2.5">
            <ToggleRight size={14} className="shrink-0 mt-0.5 text-teal-600" />
            <span>
              The role grants access only to the checked features below. A user
              with this role <strong>cannot reach</strong> a feature's URL when
              it is off here — the sidebar entry is hidden and the page redirects
              to <code>/</code>. New roles start with all features enabled;
              uncheck any you want to restrict for this tier. Admins and the
              built-in <code>user</code> role always get every feature.
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onSetAll(true)}
              className="text-[11px] px-2 py-1 rounded-md border border-[var(--color-border)] hover:bg-[var(--color-bg-secondary)]"
            >
              Enable all
            </button>
            <button
              type="button"
              onClick={() => onSetAll(false)}
              className="text-[11px] px-2 py-1 rounded-md border border-[var(--color-border)] hover:bg-[var(--color-bg-secondary)]"
            >
              Disable all
            </button>
          </div>

          <FeatureSubsection
            title="Frontend"
            icon={<Layout size={14} className="text-blue-500" />}
            description="UI surfaces and visible widgets — turning one off hides the nav entry and blocks the URL."
            features={frontend}
            enabled={enabled}
            onToggle={onToggle}
          />
          <FeatureSubsection
            title="Backend"
            icon={<Server size={14} className="text-amber-600" />}
            description="Server-side capabilities (extractors, LLM, OAuth, jobs). Disabled features still appear in the UI today; backend enforcement plumbing is incremental."
            features={backend}
            enabled={enabled}
            onToggle={onToggle}
          />
        </div>
      )}
    </div>
  );
}

function FeatureSubsection({
  title, icon, description, features, enabled, onToggle,
}: {
  title: string;
  icon: React.ReactNode;
  description: string;
  features: FeatureRegistryEntry[];
  enabled: Set<string>;
  onToggle: (key: string) => void;
}) {
  if (features.length === 0) return null;
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/40 overflow-hidden">
      <div className="px-3 py-2 border-b border-[var(--color-border)] flex items-center gap-2">
        {icon}
        <span className="text-xs font-semibold text-[var(--color-text-primary)]">{title}</span>
        <span className="text-[10px] text-[var(--color-text-muted)] ml-1">
          ({features.filter((f) => enabled.has(f.key)).length}/{features.length})
        </span>
        <span className="ml-auto text-[10px] text-[var(--color-text-muted)] truncate">{description}</span>
      </div>
      <ul className="divide-y divide-[var(--color-border)]/60">
        {features.map((f) => (
          <li key={f.key}>
            <label className="flex items-start gap-3 p-3 cursor-pointer hover:bg-white/60">
              <input
                type="checkbox"
                checked={enabled.has(f.key)}
                onChange={() => onToggle(f.key)}
                className="mt-0.5 accent-[var(--color-primary)] shrink-0"
              />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-[var(--color-text-primary)]">{f.title}</span>
                  <code className="text-[10px] text-[var(--color-text-muted)] bg-[var(--color-bg-secondary)] px-1.5 py-0.5 rounded">
                    {f.key}
                  </code>
                </span>
                <span className="block text-[11px] text-[var(--color-text-secondary)] mt-1 leading-relaxed">
                  {f.description}
                </span>
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}

function FilterGroup({
  label, values, selected, onToggle,
}: {
  label: string; values: string[]; selected: string[]; onToggle: (v: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const visible = useMemo(() => (showAll ? values : values.slice(0, 30)), [values, showAll]);
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-semibold text-[var(--color-text-secondary)]">
          {label} <span className="text-[10px] font-normal text-[var(--color-text-muted)]">({selected.length}/{values.length})</span>
        </span>
        {values.length > 30 && (
          <button type="button" onClick={() => setShowAll((v) => !v)}
            className="text-[10px] text-[var(--color-primary)] hover:underline">
            {showAll ? 'Show fewer' : `Show all ${values.length}`}
          </button>
        )}
      </div>
      {values.length === 0 ? (
        <p className="text-[10px] text-[var(--color-text-muted)] italic">No values found.</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-4 gap-y-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/40 p-3">
          {visible.map((v) => {
            const has = selected.includes(v);
            return (
              <label key={v} title={v}
                className="flex items-center gap-2 text-[12px] text-[var(--color-text-secondary)] cursor-pointer min-w-0">
                <input type="checkbox" checked={has} onChange={() => onToggle(v)}
                  className="accent-[var(--color-primary)] shrink-0" />
                <span className="font-mono truncate">{v}</span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
