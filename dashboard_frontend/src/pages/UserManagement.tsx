import React, { useState, useEffect, useCallback } from 'react';
import { Navigate } from 'react-router-dom';
import { Users, UserPlus, Trash2, Shield, UserCheck, Eye, X, KeyRound, ToggleLeft, ToggleRight, AlertTriangle } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { useRole } from '../context/RoleContext';
import { cn } from '../lib/utils';

type UserRole = 'admin' | 'developer' | 'viewer';

interface UserRecord {
  id: number;
  email: string;
  display_name: string;
  role: UserRole;
  disabled: boolean;
  created_at: number;
}

const ROLE_META: Record<UserRole, { label: string; icon: React.ReactNode; color: string }> = {
  admin: { label: 'Admin', icon: <Shield className="w-3 h-3" />, color: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400' },
  developer: { label: 'Developer', icon: <UserCheck className="w-3 h-3" />, color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
  viewer: { label: 'Viewer', icon: <Eye className="w-3 h-3" />, color: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-[var(--on-surface-variant)]' },
};

function RoleBadge({ role }: { role: UserRole }) {
  const meta = ROLE_META[role];
  return (
    <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold font-medium', meta.color)}>
      {meta.icon}
      {meta.label}
    </span>
  );
}

function CreateUserModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<UserRole>('viewer');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch('/api/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ name, email, password, role }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) { setError(data.error || 'Failed to create user'); return; }
      onCreated();
      onClose();
    } catch { setError('Network failure'); }
    finally { setSubmitting(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
      <motion.div initial={{ opacity: 0, scale: 0.95, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.95, y: 10 }}
        className="bg-[var(--surface)] rounded-md p-8 w-full max-w-md shadow-2xl border border-[var(--outline)]">
        <div className="flex justify-between items-center mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-md bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-300"><UserPlus className="w-5 h-5" /></div>
            <h2 className="text-xl font-bold text-[var(--on-surface)]">Create Account</h2>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-stone-100 dark:hover:bg-zinc-800 rounded-full transition-colors text-[var(--on-surface-variant)]"><X className="w-5 h-5" /></button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-1.5">
            <label className="text-xs font-bold font-medium text-[var(--on-surface-variant)]">Name</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} required placeholder="e.g. John Doe"
              className="w-full bg-stone-50 dark:bg-zinc-900 border border-[var(--outline)] rounded-xl py-3 px-4 text-sm focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all dark:text-white" />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-bold font-medium text-[var(--on-surface-variant)]">Account</label>
            <input type="text" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="username"
              className="w-full bg-stone-50 dark:bg-zinc-900 border border-[var(--outline)] rounded-xl py-3 px-4 text-sm focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all dark:text-white" />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-bold font-medium text-[var(--on-surface-variant)]">Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required placeholder="••••••••"
              className="w-full bg-stone-50 dark:bg-zinc-900 border border-[var(--outline)] rounded-xl py-3 px-4 text-sm focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all dark:text-white" />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-bold font-medium text-[var(--on-surface-variant)]">Role</label>
            <div className="grid grid-cols-3 gap-2">
              {(['admin', 'developer', 'viewer'] as UserRole[]).map((r) => (
                <button key={r} type="button" onClick={() => setRole(r)}
                  className={cn('flex flex-col items-center gap-1.5 py-3 px-2 rounded-xl border text-xs font-bold transition-all',
                    role === r ? 'border-indigo-600 bg-indigo-50 text-indigo-700 dark:border-indigo-500 dark:bg-indigo-950/30 dark:text-indigo-300 dark:border-primary dark:bg-primary/10'
                      : 'border-[var(--outline)] text-slate-500 hover:border-slate-300 dark:text-[var(--on-surface-variant)] dark:hover:border-slate-700')}>
                  {ROLE_META[r].icon}{ROLE_META[r].label}
                </button>
              ))}
            </div>
          </div>
          {error && (
            <div className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 dark:bg-rose-900/20 dark:border-rose-800 px-4 py-3 text-sm font-medium text-rose-700 dark:text-rose-400">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />{error}
            </div>
          )}
          <button type="submit" disabled={submitting}
            className="w-full py-3.5 bg-primary text-white rounded-xl font-bold shadow-lg shadow-primary/20 hover:scale-[1.02] active:scale-[0.98] transition-all disabled:opacity-60 disabled:cursor-not-allowed">
            {submitting ? 'Creating...' : 'Create Account'}
          </button>
        </form>
      </motion.div>
    </div>
  );
}

function EditUserModal({ user, currentUserEmail, onClose, onUpdated }: { user: UserRecord; currentUserEmail: string | null; onClose: () => void; onUpdated: () => void }) {
  const [displayName, setDisplayName] = useState(user.display_name || '');
  const [role, setRole] = useState<UserRole>(user.role);
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { email: user.email, role, display_name: displayName };
      if (password.trim()) body.password = password.trim();
      const res = await fetch('/api/users/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) { setError(data.error || 'Failed to update user'); return; }
      onUpdated();
      onClose();
    } catch { setError('Network failure'); }
    finally { setSubmitting(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
      <motion.div initial={{ opacity: 0, scale: 0.95, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.95, y: 10 }}
        className="bg-[var(--surface)] rounded-md p-8 w-full max-w-md shadow-2xl border border-[var(--outline)]">
        <div className="flex justify-between items-center mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-md bg-amber-100 dark:bg-amber-900/30 text-amber-600"><KeyRound className="w-5 h-5" /></div>
            <div>
              <h2 className="text-xl font-bold text-[var(--on-surface)]">Edit User</h2>
              <p className="text-xs text-[var(--on-surface-variant)] truncate max-w-[200px]">{user.email}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-stone-100 dark:hover:bg-zinc-800 rounded-full transition-colors text-[var(--on-surface-variant)]"><X className="w-5 h-5" /></button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-1.5">
            <label className="text-xs font-bold font-medium text-[var(--on-surface-variant)]">Name</label>
            <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="Display name"
              className="w-full bg-stone-50 dark:bg-zinc-900 border border-[var(--outline)] rounded-xl py-3 px-4 text-sm focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all dark:text-white" />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-bold font-medium text-[var(--on-surface-variant)]">Role</label>
            <div className="grid grid-cols-3 gap-2">
              {(['admin', 'developer', 'viewer'] as UserRole[]).map((r) => (
                <button key={r} type="button" onClick={() => setRole(r)}
                  disabled={user.email === currentUserEmail && r !== 'admin'}
                  className={cn('flex flex-col items-center gap-1.5 py-3 px-2 rounded-xl border text-xs font-bold transition-all disabled:opacity-40 disabled:cursor-not-allowed',
                    role === r ? 'border-indigo-600 bg-indigo-50 text-indigo-700 dark:border-indigo-500 dark:bg-indigo-950/30 dark:text-indigo-300 dark:border-primary dark:bg-primary/10'
                      : 'border-[var(--outline)] text-slate-500 hover:border-slate-300 dark:text-[var(--on-surface-variant)] dark:hover:border-slate-700')}>
                  {ROLE_META[r].icon}{ROLE_META[r].label}
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-bold font-medium text-[var(--on-surface-variant)]">
              New Password <span className="normal-case font-medium text-[var(--on-surface-variant)]">(leave blank to keep current)</span>
            </label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••"
              className="w-full bg-stone-50 dark:bg-zinc-900 border border-[var(--outline)] rounded-xl py-3 px-4 text-sm focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all dark:text-white" />
          </div>
          {error && (
            <div className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 dark:bg-rose-900/20 dark:border-rose-800 px-4 py-3 text-sm font-medium text-rose-700 dark:text-rose-400">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />{error}
            </div>
          )}
          <button type="submit" disabled={submitting}
            className="w-full py-3.5 bg-primary text-white rounded-xl font-bold shadow-lg shadow-primary/20 hover:scale-[1.02] active:scale-[0.98] transition-all disabled:opacity-60 disabled:cursor-not-allowed">
            {submitting ? 'Saving...' : 'Save Changes'}
          </button>
        </form>
      </motion.div>
    </div>
  );
}

function DeleteConfirmModal({ target, error, deleting, onConfirm, onClose }: {
  target: UserRecord;
  error: string | null;
  deleting: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const [confirmText, setConfirmText] = useState('');
  const confirmed = confirmText === 'delete';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
      <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.95 }}
        className="bg-[var(--surface)] rounded-md p-8 w-full max-w-sm shadow-2xl border border-[var(--outline)]">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2.5 rounded-md bg-rose-100 dark:bg-rose-900/30 text-rose-600"><Trash2 className="w-5 h-5" /></div>
          <h3 className="text-lg font-bold text-[var(--on-surface)]">Delete Account</h3>
        </div>
        <p className="text-sm text-[var(--on-surface-variant)] mb-1">
          Permanently delete <span className="font-semibold text-slate-700 dark:text-slate-200">{target.display_name || target.email}</span>?
        </p>
        <p className="text-xs text-[var(--on-surface-variant)] mb-5">This action cannot be undone. All sessions will be revoked.</p>
        <div className="space-y-1.5 mb-5">
          <label className="text-xs font-bold font-medium text-[var(--on-surface-variant)]">
            Type <span className="font-mono text-rose-500">delete</span> to confirm
          </label>
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="delete"
            autoComplete="off"
            className="w-full bg-stone-50 dark:bg-zinc-900 border border-[var(--outline)] rounded-xl py-3 px-4 text-sm focus:ring-2 focus:ring-rose-500/20 outline-none transition-all dark:text-white font-mono"
          />
        </div>
        {error && (
          <div className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 dark:bg-rose-900/20 dark:border-rose-800 px-4 py-3 text-sm font-medium text-rose-700 dark:text-rose-400 mb-4">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />{error}
          </div>
        )}
        <div className="flex gap-3">
          <button onClick={onClose}
            className="flex-1 py-3 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl font-bold text-sm hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors">
            Cancel
          </button>
          <button onClick={onConfirm} disabled={!confirmed || deleting}
            className="flex-1 py-3 bg-rose-500 text-white rounded-xl font-bold text-sm hover:bg-rose-600 active:scale-[0.98] transition-all shadow-lg shadow-rose-500/20 disabled:opacity-40 disabled:cursor-not-allowed">
            {deleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </motion.div>
    </div>
  );
}

export function UserManagement() {
  const { role, userEmail, loading } = useRole();
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editTarget, setEditTarget] = useState<UserRecord | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<UserRecord | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deletingEmail, setDeletingEmail] = useState<string | null>(null);
  const [togglingEmail, setTogglingEmail] = useState<string | null>(null);

  const fetchUsers = useCallback(async () => {
    setLoadingUsers(true);
    setError(null);
    try {
      const res = await fetch('/api/users', { credentials: 'include' });
      const data = await res.json();
      if (data.ok) setUsers(data.users);
      else setError(data.error || 'Failed to load users');
    } catch { setError('Network failure'); }
    finally { setLoadingUsers(false); }
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const handleDelete = async (user: UserRecord) => {
    setDeletingEmail(user.email);
    setDeleteError(null);
    try {
      const res = await fetch('/api/users/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: user.email }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) { setDeleteError(data.error || 'Failed to delete user'); return; }
      setDeleteTarget(null);
      fetchUsers();
    } catch { setDeleteError('Network failure'); }
    finally { setDeletingEmail(null); }
  };

  const handleToggleDisabled = async (user: UserRecord) => {
    setTogglingEmail(user.email);
    try {
      await fetch('/api/users/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: user.email, disabled: !user.disabled }),
      });
      fetchUsers();
    } finally { setTogglingEmail(null); }
  };

  const formatDate = (epoch: number) =>
    new Date(epoch * 1000).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh] text-sm text-[var(--on-surface-variant)] font-medium">
        Loading session...
      </div>
    );
  }

  if (role !== 'admin') return <Navigate to="/" replace />;

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="mb-8 flex items-center justify-between pb-8 border-b border-[var(--outline)]">
        <div className="flex items-center gap-4">
          <div className="p-3 rounded-md bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-300"><Users className="w-6 h-6" /></div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-[var(--on-surface)]">User Management</h1>
            <p className="text-sm text-[var(--on-surface-variant)] mt-0.5">Admin-only — create and manage user accounts</p>
          </div>
        </div>
        <button onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold text-sm shadow-lg shadow-primary/20 hover:scale-[1.02] active:scale-[0.98] transition-all">
          <UserPlus className="w-4 h-4" />New Account
        </button>
      </div>

      <div className="bg-[var(--surface)] rounded-md border border-[var(--outline)] shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <p className="text-xs font-bold font-medium text-[var(--on-surface-variant)]">
            {users.length} {users.length === 1 ? 'Account' : 'Accounts'}
          </p>
          <p className="text-[10px] text-[var(--on-surface-variant)] font-medium">Users cannot self-register — accounts created by admin only</p>
        </div>

        {loadingUsers ? (
          <div className="flex items-center justify-center py-16 text-[var(--on-surface-variant)] text-sm font-medium">Loading accounts...</div>
        ) : error ? (
          <div className="flex items-center justify-center gap-2 py-16 text-rose-500 text-sm font-medium">
            <AlertTriangle className="w-4 h-4" />{error}
          </div>
        ) : users.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-[var(--on-surface-variant)]">
            <Users className="w-10 h-10 mb-3 opacity-30" />
            <p className="text-sm font-medium">No accounts yet</p>
          </div>
        ) : (
          <div className="divide-y divide-[var(--outline)]">
            {users.map((u) => (
              <motion.div key={u.email} layout
                className={cn('flex items-center gap-4 px-6 py-4 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors', u.disabled && 'opacity-60')}>
                <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center text-primary font-bold text-sm flex-shrink-0">
                  {u.email[0].toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-[var(--on-surface)] truncate">{u.display_name || u.email}</span>
                    {u.email === userEmail && (
                      <span className="text-[9px] font-bold font-medium px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-300">You</span>
                    )}
                    {u.disabled && (
                      <span className="text-[9px] font-bold font-medium px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-700 text-[var(--on-surface-variant)]">Disabled</span>
                    )}
                  </div>
                  <p className="text-xs text-[var(--on-surface-variant)] mt-0.5">{u.display_name ? <span className="font-mono">{u.email}</span> : null} · Created {formatDate(u.created_at)}</p>
                </div>
                <RoleBadge role={u.role} />
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <button onClick={() => setEditTarget(u)} title="Edit role / reset password"
                    className="p-2 rounded-xl text-[var(--on-surface-variant)] hover:text-primary hover:bg-primary/10 transition-colors">
                    <KeyRound className="w-4 h-4" />
                  </button>
                  {u.email !== userEmail && (
                    <button onClick={() => handleToggleDisabled(u)} disabled={togglingEmail === u.email}
                      title={u.disabled ? 'Enable account' : 'Disable account'}
                      className="p-2 rounded-xl text-[var(--on-surface-variant)] hover:text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-900/20 transition-colors disabled:opacity-40">
                      {u.disabled ? <ToggleLeft className="w-4 h-4" /> : <ToggleRight className="w-4 h-4" />}
                    </button>
                  )}
                  {u.email !== userEmail && (
                    <button onClick={() => { setDeleteTarget(u); setDeleteError(null); }} title="Delete account"
                      className="p-2 rounded-xl text-[var(--on-surface-variant)] hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-900/20 transition-colors">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>

      <AnimatePresence>
        {showCreate && <CreateUserModal key="create-user-modal" onClose={() => setShowCreate(false)} onCreated={fetchUsers} />}
        {editTarget && <EditUserModal key="edit-user-modal" user={editTarget} currentUserEmail={userEmail} onClose={() => setEditTarget(null)} onUpdated={fetchUsers} />}
        {deleteTarget && (
          <DeleteConfirmModal
            key="delete-confirm-modal"
            target={deleteTarget}
            error={deleteError}
            deleting={deletingEmail === deleteTarget.email}
            onConfirm={() => handleDelete(deleteTarget)}
            onClose={() => { setDeleteTarget(null); setDeleteError(null); }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
