import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Loader2, AlertCircle, Check } from 'lucide-react';
import { authVerifyEmail } from '../api/client';
import ThemeSwitcher from '../theme/ThemeSwitcher';

export default function VerifyEmail() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [state, setState] = useState<{ status: 'loading' | 'ok' | 'error'; message: string }>({
    status: 'loading',
    message: 'Verifying...',
  });

  useEffect(() => {
    if (!token) {
      setState({ status: 'error', message: 'Missing verification token.' });
      return;
    }
    authVerifyEmail(token)
      .then((r) => setState({ status: r.success ? 'ok' : 'error', message: r.message }))
      .catch((e: Error) => setState({ status: 'error', message: e.message }));
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg-secondary)] px-4 relative">
      <div className="absolute top-4 right-4 z-20"><ThemeSwitcher /></div>
      <div className="w-full max-w-md bg-white border border-[var(--color-border)] rounded-2xl shadow-sm p-8 text-center">
        {state.status === 'loading' && (
          <>
            <Loader2 size={36} className="animate-spin text-[var(--color-primary)] mx-auto mb-3" />
            <p className="text-sm text-[var(--color-text-secondary)]">{state.message}</p>
          </>
        )}
        {state.status === 'ok' && (
          <>
            <div className="mx-auto w-12 h-12 rounded-full bg-green-100 flex items-center justify-center mb-3">
              <Check size={24} className="text-green-700" />
            </div>
            <h1 className="text-xl font-bold text-[var(--color-text-primary)] mb-2">Email verified</h1>
            <p className="text-sm text-[var(--color-text-secondary)]">{state.message}</p>
            <Link to="/login" className="inline-block mt-5 text-sm text-[var(--color-primary)] hover:underline">
              Sign in
            </Link>
          </>
        )}
        {state.status === 'error' && (
          <>
            <div className="mx-auto w-12 h-12 rounded-full bg-red-100 flex items-center justify-center mb-3">
              <AlertCircle size={24} className="text-red-700" />
            </div>
            <h1 className="text-xl font-bold text-[var(--color-text-primary)] mb-2">Verification failed</h1>
            <p className="text-sm text-red-700">{state.message}</p>
            <Link to="/login" className="inline-block mt-5 text-sm text-[var(--color-primary)] hover:underline">
              Back to sign in
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
