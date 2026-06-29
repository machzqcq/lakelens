import { useState } from 'react';
import { Link } from 'react-router-dom';
import { UserPlus, Loader2, AlertCircle, Check } from 'lucide-react';
import { authRegister } from '../api/client';
import ThemeSwitcher from '../theme/ThemeSwitcher';

export default function Register() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    setSubmitting(true);
    try {
      const result = await authRegister(email, password, name || undefined);
      setSuccess(result.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg-secondary)] px-4 relative">
      <div className="absolute top-4 right-4 z-20"><ThemeSwitcher /></div>
        <div className="w-full max-w-md bg-white border border-[var(--color-border)] rounded-2xl shadow-sm p-8 text-center">
          <div className="mx-auto w-12 h-12 rounded-full bg-green-100 flex items-center justify-center mb-3">
            <Check size={24} className="text-green-700" />
          </div>
          <h1 className="text-xl font-bold text-[var(--color-text-primary)] mb-2">Check your email</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">{success}</p>
          <Link to="/login" className="inline-block mt-5 text-sm text-[var(--color-primary)] hover:underline">
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg-secondary)] px-4 relative">
      <div className="absolute top-4 right-4 z-20"><ThemeSwitcher /></div>
      <div className="w-full max-w-md bg-white border border-[var(--color-border)] rounded-2xl shadow-sm p-8">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Create account</h1>
          <p className="text-sm text-[var(--color-text-muted)] mt-1">Databricks Billing Dashboard</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <label className="block text-sm">
            <span className="text-xs text-[var(--color-text-muted)]">Full name (optional)</span>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]" />
          </label>
          <label className="block text-sm">
            <span className="text-xs text-[var(--color-text-muted)]">Email</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus
              className="mt-1 w-full bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]" />
          </label>
          <label className="block text-sm">
            <span className="text-xs text-[var(--color-text-muted)]">Password (min 8 chars)</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8}
              className="mt-1 w-full bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]" />
          </label>
          <label className="block text-sm">
            <span className="text-xs text-[var(--color-text-muted)]">Confirm password</span>
            <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required minLength={8}
              className="mt-1 w-full bg-white border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]" />
          </label>

          {error && (
            <div className="flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg p-2">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <button type="submit" disabled={submitting}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-[var(--color-primary)] text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[var(--color-primary)]/90 transition-colors">
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <UserPlus size={14} />}
            Create account
          </button>
        </form>

        <p className="text-center text-xs text-[var(--color-text-muted)] mt-6">
          Already have an account? <Link to="/login" className="text-[var(--color-primary)] hover:underline">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
