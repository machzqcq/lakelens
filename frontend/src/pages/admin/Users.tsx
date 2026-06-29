import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { UserCog, Trash2, Power, Loader2, AlertCircle, Plus, X, Save } from 'lucide-react';
import {
  type AdminUser,
  type AdminRole,
  adminAssignRole,
  adminCreateUser,
  adminDeleteUser,
  adminListRoles,
  adminListUsers,
  adminPatchUser,
  adminUnassignRole,
} from '../../api/client';

export default function AdminUsers() {
  const qc = useQueryClient();
  const usersQ = useQuery({ queryKey: ['admin-users'], queryFn: adminListUsers });
  const rolesQ = useQuery({ queryKey: ['admin-roles'], queryFn: adminListRoles });
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const createMut = useMutation({
    mutationFn: adminCreateUser,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-users'] }); setCreating(false); setError(null); },
    onError: (e: Error) => setError(e.message),
  });

  const patchMut = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: { is_active?: boolean } }) => adminPatchUser(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
    onError: (e: Error) => setError(e.message),
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => adminDeleteUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
    onError: (e: Error) => setError(e.message),
  });
  const assignMut = useMutation({
    mutationFn: ({ uid, rid }: { uid: number; rid: number }) => adminAssignRole(uid, rid),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
    onError: (e: Error) => setError(e.message),
  });
  const unassignMut = useMutation({
    mutationFn: ({ uid, rid }: { uid: number; rid: number }) => adminUnassignRole(uid, rid),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
    onError: (e: Error) => setError(e.message),
  });

  const users = usersQ.data ?? [];
  const roles = rolesQ.data ?? [];

  return (
    <div className="space-y-5 max-w-[1400px]">
      <div className="flex items-center justify-between gap-3 pr-14">
        <div className="flex items-center gap-3">
          <UserCog size={24} className="text-[var(--color-primary)]" />
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Users</h1>
        </div>
        {!creating && (
          <button onClick={() => { setCreating(true); setError(null); }}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--color-primary)] text-white text-sm">
            <Plus size={14} /> New user
          </button>
        )}
      </div>

      {error && (
        <div className="flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
          <AlertCircle size={14} className="shrink-0 mt-0.5" /><span>{error}</span>
        </div>
      )}

      {creating && (
        <CreateUserForm
          roles={roles}
          submitting={createMut.isPending}
          onCancel={() => { setCreating(false); setError(null); }}
          onSubmit={(payload) => createMut.mutate(payload)}
        />
      )}

      {usersQ.isLoading ? (
        <p className="text-sm text-[var(--color-text-muted)]">Loading users...</p>
      ) : (
        <div className="bg-white border border-[var(--color-border)] rounded-2xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[var(--color-bg-secondary)]">
              <tr>
                <th className="px-4 py-2.5 text-left font-semibold text-[var(--color-text-muted)]">User</th>
                <th className="px-4 py-2.5 text-left font-semibold text-[var(--color-text-muted)]">Status</th>
                <th className="px-4 py-2.5 text-left font-semibold text-[var(--color-text-muted)]">Roles</th>
                <th className="px-4 py-2.5 text-left font-semibold text-[var(--color-text-muted)]">SSO</th>
                <th className="px-4 py-2.5 text-right font-semibold text-[var(--color-text-muted)]">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u: AdminUser) => (
                <UserRow
                  key={u.id} user={u} roles={roles}
                  onToggleActive={() => patchMut.mutate({ id: u.id, patch: { is_active: !u.is_active } })}
                  onDelete={() => {
                    if (confirm(`Delete user ${u.email}? This cannot be undone.`)) deleteMut.mutate(u.id);
                  }}
                  onAssign={(rid) => assignMut.mutate({ uid: u.id, rid })}
                  onUnassign={(rid) => unassignMut.mutate({ uid: u.id, rid })}
                />
              ))}
              {users.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-xs text-[var(--color-text-muted)]">No users.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CreateUserForm({
  roles, submitting, onCancel, onSubmit,
}: {
  roles: AdminRole[];
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (p: { email: string; password: string; full_name?: string; role_ids: number[]; is_email_verified: boolean }) => void;
}) {
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [verified, setVerified] = useState(true);
  const [roleIds, setRoleIds] = useState<Set<number>>(new Set());

  // 'user' is always granted server-side; only offer extra/custom roles here.
  const selectableRoles = roles.filter((r) => r.name !== 'user');

  function toggleRole(id: number) {
    setRoleIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    onSubmit({
      email: email.trim().toLowerCase(),
      password,
      full_name: fullName.trim() || undefined,
      role_ids: [...roleIds],
      is_email_verified: verified,
    });
  }

  return (
    <form onSubmit={submit} className="bg-white border-2 border-[var(--color-primary)]/40 rounded-2xl p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">New user</h3>
        <button type="button" onClick={onCancel}
          className="p-1 rounded text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)]">
          <X size={16} />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="block text-sm">
          <span className="text-xs text-[var(--color-text-muted)]">Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
            placeholder="user@company.com"
            className="mt-1 w-full bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm" />
        </label>
        <label className="block text-sm">
          <span className="text-xs text-[var(--color-text-muted)]">Full name (optional)</span>
          <input type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={255}
            className="mt-1 w-full bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm" />
        </label>
        <label className="block text-sm md:col-span-2">
          <span className="text-xs text-[var(--color-text-muted)]">Temporary password (min 8 chars)</span>
          <input type="text" value={password} onChange={(e) => setPassword(e.target.value)} required
            minLength={8} maxLength={128} placeholder="Share this with the user securely"
            className="mt-1 w-full bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm font-mono" />
        </label>
      </div>

      <label className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
        <input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)}
          className="accent-[var(--color-primary)]" />
        Mark email as verified (user can sign in immediately)
      </label>

      <div className="border-t border-[var(--color-border)] pt-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2">
          Additional roles <span className="font-normal normal-case lowercase tracking-normal text-[10px]">(the base <code>user</code> role is always granted)</span>
        </p>
        {selectableRoles.length === 0 ? (
          <p className="text-[10px] text-[var(--color-text-muted)] italic">No custom roles defined yet.</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {selectableRoles.map((r) => (
              <label key={r.id} className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
                <input type="checkbox" checked={roleIds.has(r.id)} onChange={() => toggleRole(r.id)}
                  className="accent-[var(--color-primary)]" />
                <span className="font-mono">{r.name}</span>
                {r.is_system && (
                  <span className="text-[10px] font-semibold uppercase rounded-full px-1.5 py-0.5 bg-gray-200 text-gray-700">system</span>
                )}
                {r.description && <span className="text-[10px] text-[var(--color-text-muted)]">— {r.description}</span>}
              </label>
            ))}
          </div>
        )}
      </div>

      <div className="flex justify-end gap-2 border-t border-[var(--color-border)] pt-3">
        <button type="button" onClick={onCancel}
          className="px-3 py-1.5 rounded-lg text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]">
          Cancel
        </button>
        <button type="submit" disabled={submitting}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--color-primary)] text-white text-sm disabled:opacity-50">
          {submitting ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          Create user
        </button>
      </div>
    </form>
  );
}

function UserRow({
  user, roles, onToggleActive, onDelete, onAssign, onUnassign,
}: {
  user: AdminUser; roles: AdminRole[];
  onToggleActive: () => void; onDelete: () => void;
  onAssign: (rid: number) => void; onUnassign: (rid: number) => void;
}) {
  const userRoleIds = new Set(roles.filter((r) => user.roles.includes(r.name)).map((r) => r.id));
  return (
    <tr className="border-t border-[var(--color-border)]/50">
      <td className="px-4 py-2.5">
        <div className="text-[var(--color-text-primary)] font-medium">{user.email}</div>
        {user.full_name && <div className="text-[10px] text-[var(--color-text-muted)]">{user.full_name}</div>}
      </td>
      <td className="px-4 py-2.5">
        <div className="flex flex-col gap-0.5">
          <span className={`text-[10px] font-semibold uppercase rounded-full px-1.5 py-0.5 inline-block w-fit ${user.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-200 text-gray-700'}`}>
            {user.is_active ? 'active' : 'disabled'}
          </span>
          {!user.is_email_verified && (
            <span className="text-[10px] font-semibold uppercase rounded-full px-1.5 py-0.5 bg-amber-100 text-amber-800 inline-block w-fit">unverified</span>
          )}
        </div>
      </td>
      <td className="px-4 py-2.5">
        <div className="flex flex-wrap gap-1">
          {roles.map((r) => {
            const has = userRoleIds.has(r.id);
            return (
              <button key={r.id} type="button"
                onClick={() => has ? onUnassign(r.id) : onAssign(r.id)}
                title={has ? `Remove ${r.name}` : `Assign ${r.name}`}
                className={`text-[10px] font-semibold uppercase rounded-full px-2 py-0.5 transition-colors ${
                  has ? 'bg-[var(--color-primary)] text-white' : 'bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-card-hover)]'
                }`}>
                {r.name}
              </button>
            );
          })}
        </div>
      </td>
      <td className="px-4 py-2.5">
        <div className="flex gap-1 flex-wrap">
          {user.oauth_providers.map((p) => (
            <span key={p} className="text-[10px] font-semibold uppercase rounded-full px-1.5 py-0.5 bg-blue-100 text-blue-800">
              {p}
            </span>
          ))}
        </div>
      </td>
      <td className="px-4 py-2.5 text-right">
        <div className="flex justify-end gap-1">
          <button onClick={onToggleActive} title={user.is_active ? 'Disable' : 'Enable'}
            className="p-1.5 rounded text-[var(--color-text-muted)] hover:text-[var(--color-primary)] hover:bg-[var(--color-bg-secondary)]">
            <Power size={14} />
          </button>
          <button onClick={onDelete} title="Delete"
            className="p-1.5 rounded text-[var(--color-text-muted)] hover:text-red-600 hover:bg-red-50">
            <Trash2 size={14} />
          </button>
        </div>
      </td>
    </tr>
  );
}
