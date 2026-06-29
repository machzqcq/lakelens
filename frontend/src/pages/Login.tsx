import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  LogIn, Loader2, AlertCircle, Zap, CheckCircle2,
  BookOpen, GitBranch, Gauge, Layers, ShieldCheck,
} from 'lucide-react';
import { authDevCredentials, authOauthAuthorize, authOauthProviders } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { GoogleIcon, MicrosoftIcon, GitHubIcon } from '../components/BrandIcons';
import ThemeSwitcher from '../theme/ThemeSwitcher';

// The four pillars from README.md — keep titles and order in sync.
const FEATURES: { icon: typeof BookOpen; title: string; body: string }[] = [
  { icon: BookOpen,  title: 'Data Governance',             body: 'Catalog → schema → table → column browser with owners, comments, type heatmaps. Per-role data-scope filters and per-role feature matrix.' },
  { icon: GitBranch, title: 'Column-Level Lineage',        body: 'Direct + transitive upstream / downstream graphs for every table and column. Impact analysis, blast radius, read / write classification.' },
  { icon: Gauge,     title: 'Data Quality & Observability', body: 'Statement-level signals from query history — failure rates, full scans, partition pruning, off-hours PII reads, duplicate clustering.' },
  { icon: Layers,    title: 'Master Data via Lineage',     body: 'Canonical-key surface across query history — which tables share the same logical entity, where it gets copied, who owns the candidate golden copy.' },
];

interface OAuthButtonSpec {
  name: 'google' | 'microsoft' | 'github';
  label: string;
  Icon: React.ComponentType<{ size?: number; className?: string }>;
  bg: string;
  text: string;
  hover: string;
  border: string;
}

const OAUTH_BUTTONS: OAuthButtonSpec[] = [
  { name: 'google',    label: 'Continue with Google',    Icon: GoogleIcon,    bg: '#ffffff', text: '#1f1f1f', hover: '#f5f5f5', border: '#dadce0' },
  { name: 'microsoft', label: 'Continue with Microsoft', Icon: MicrosoftIcon, bg: '#ffffff', text: '#1f1f1f', hover: '#f5f5f5', border: '#dadce0' },
  { name: 'github',    label: 'Continue with GitHub',    Icon: GitHubIcon,    bg: '#24292f', text: '#ffffff', hover: '#1c2128', border: '#24292f' },
];

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, state } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [providers, setProviders] = useState<Record<string, boolean>>({});
  const [devPrefilled, setDevPrefilled] = useState(false);

  useEffect(() => {
    authOauthProviders().then(setProviders).catch(() => setProviders({}));
  }, []);

  // Local-dev convenience: pre-fill the form with the bootstrap admin
  // credentials when the backend has EXPOSE_DEV_CREDENTIALS=true. Returns
  // null in any other environment, so this is a no-op in prod.
  useEffect(() => {
    authDevCredentials().then((creds) => {
      if (creds && creds.email) {
        setEmail((cur) => cur || creds.email);
        setPassword((cur) => cur || creds.password);
        setDevPrefilled(true);
      }
    });
  }, []);

  useEffect(() => {
    if (state.status === 'authenticated') {
      const from = (location.state as { from?: string } | null)?.from ?? '/';
      navigate(from, { replace: true });
    }
  }, [state, location.state, navigate]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function startOAuth(provider: string) {
    try {
      const { url } = await authOauthAuthorize(provider);
      window.location.href = url;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="min-h-screen flex flex-col lg:flex-row bg-[var(--color-bg-secondary)] relative">
      {/* Theme switcher floats top-right on the page */}
      <div className="absolute top-4 right-4 z-20">
        <ThemeSwitcher />
      </div>

      {/* ---------- Hero panel (left on desktop) ---------- */}
      <section
        className="relative lg:flex-1 flex flex-col justify-between p-8 lg:p-12 text-white overflow-hidden"
        style={{ background: 'var(--hero-gradient)' }}
      >
        {/* Decorative orbs */}
        <div aria-hidden className="absolute -top-24 -left-24 w-96 h-96 rounded-full opacity-30 blur-3xl"
          style={{ background: 'radial-gradient(circle, rgba(255,255,255,0.4), transparent 70%)' }} />
        <div aria-hidden className="absolute -bottom-32 -right-16 w-96 h-96 rounded-full opacity-20 blur-3xl"
          style={{ background: 'radial-gradient(circle, rgba(0,0,0,0.5), transparent 70%)' }} />

        <div className="relative">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-xl bg-white/15 backdrop-blur flex items-center justify-center ring-1 ring-white/30">
              <BookOpen size={22} />
            </div>
            <div>
              <h1 className="text-lg font-semibold leading-tight">Governance Workbench</h1>
              <p className="text-xs text-white/70 leading-tight">Governance · Lineage · Data Quality · MDM</p>
            </div>
          </div>

          <h2 className="text-3xl lg:text-4xl font-bold leading-tight max-w-md mb-4">
            Govern the lakehouse you've already built.
          </h2>
          <p className="text-white/85 text-sm max-w-md mb-10 leading-relaxed">
            A self-hosted control plane over Databricks <code className="bg-white/10 rounded px-1">system.*</code> and
            Unity Catalog <code className="bg-white/10 rounded px-1">INFORMATION_SCHEMA</code> — column-level lineage,
            audit forensics, data-quality observability, and master-data tracking,
            all running outside the workspace it observes.
          </p>

          <ul className="space-y-4 max-w-md">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <li key={title} className="flex gap-3">
                <div className="shrink-0 w-9 h-9 rounded-lg bg-white/15 backdrop-blur flex items-center justify-center ring-1 ring-white/20">
                  <Icon size={16} />
                </div>
                <div>
                  <p className="text-sm font-semibold">{title}</p>
                  <p className="text-xs text-white/75 leading-relaxed">{body}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="relative mt-10 flex flex-wrap gap-x-6 gap-y-2 text-[11px] text-white/70">
          <span className="flex items-center gap-1.5"><ShieldCheck size={12} /> Self-hosted — your data stays in your VPC</span>
          <span className="flex items-center gap-1.5"><CheckCircle2 size={12} /> SSO via Google / MS / GitHub</span>
          <span className="flex items-center gap-1.5"><CheckCircle2 size={12} /> RBAC with per-role data scopes</span>
          <span className="flex items-center gap-1.5"><CheckCircle2 size={12} /> No read-runtime dependency on the workspace</span>
        </div>
      </section>

      {/* ---------- Form panel (right on desktop) ---------- */}
      <section className="lg:w-[460px] flex items-center justify-center p-6 lg:p-10">
        <div className="w-full max-w-sm">
          <div className="text-center mb-6">
            <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Sign in</h1>
            <p className="text-sm text-[var(--color-text-muted)] mt-1">Welcome back. Pick your method.</p>
          </div>

          {/* OAuth buttons up top — typical SSO-first flow */}
          <div className="space-y-2 mb-5">
            {OAUTH_BUTTONS.map(({ name, label, Icon, bg, text, hover, border }) => {
              const enabled = providers[name];
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => startOAuth(name)}
                  disabled={!enabled}
                  title={enabled ? label : `${name} OAuth not configured (admin: set ${name.toUpperCase()}_OAUTH_CLIENT_ID/SECRET)`}
                  className="group relative w-full flex items-center justify-center gap-3 px-4 py-2.5 rounded-lg border text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{
                    backgroundColor: bg,
                    color: text,
                    borderColor: border,
                  }}
                  onMouseOver={(e) => { if (!e.currentTarget.disabled) e.currentTarget.style.backgroundColor = hover; }}
                  onMouseOut={(e) => { e.currentTarget.style.backgroundColor = bg; }}
                >
                  <Icon size={18} />
                  <span>{label}</span>
                </button>
              );
            })}
          </div>

          <div className="my-5 flex items-center gap-2 text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">
            <div className="flex-1 h-px bg-[var(--color-border)]" />
            or use email
            <div className="flex-1 h-px bg-[var(--color-border)]" />
          </div>

          {devPrefilled && (
            <div className="mb-3 flex items-start gap-2 text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5 leading-snug">
              <span className="font-semibold uppercase tracking-wider text-[9px] mt-[1px]">Dev</span>
              <span>Pre-filled from <code className="font-mono">.env</code> (DEFAULT_ADMIN_*). Disable by setting <code className="font-mono">EXPOSE_DEV_CREDENTIALS=false</code>.</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-3">
            <label className="block text-sm">
              <span className="text-xs text-[var(--color-text-muted)]">Email</span>
              <input
                type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus
                placeholder="you@company.com"
                className="mt-1 w-full bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/30 focus:border-[var(--color-primary)] transition-colors"
              />
            </label>
            <label className="block text-sm">
              <span className="text-xs text-[var(--color-text-muted)]">Password</span>
              <input
                type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
                placeholder="••••••••"
                className="mt-1 w-full bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/30 focus:border-[var(--color-primary)] transition-colors"
              />
            </label>

            {error && (
              <div className="flex items-start gap-2 text-xs text-[var(--color-danger)] bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 rounded-lg p-2">
                <AlertCircle size={14} className="shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <button type="submit" disabled={submitting}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-[var(--color-primary)] text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 active:scale-[0.99] transition-all shadow-sm">
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <LogIn size={14} />}
              Sign in
            </button>
          </form>

          <p className="text-center text-xs text-[var(--color-text-muted)] mt-6">
            New here? <Link to="/register" className="text-[var(--color-primary)] hover:underline font-medium">Create an account</Link>
          </p>

          <div className="mt-5 flex items-center justify-center gap-1.5 text-[10px] text-[var(--color-text-muted)]">
            <Zap size={10} /> FastAPI · Postgres · Spark Connect · DuckDB · React
          </div>
        </div>
      </section>
    </div>
  );
}
