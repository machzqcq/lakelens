import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, AlertCircle } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';

/** Lands here after the backend redirects back with `#access_token=...&provider=...`. */
export default function OAuthCallback() {
  const navigate = useNavigate();
  const { acceptToken } = useAuth();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const hash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : '';
    const params = new URLSearchParams(hash);
    const token = params.get('access_token');
    if (!token) {
      setError('No token in callback URL.');
      return;
    }
    acceptToken(token)
      .then(() => {
        // Wipe the fragment and bounce home
        window.history.replaceState(null, '', '/');
        navigate('/', { replace: true });
      })
      .catch((e: Error) => setError(e.message));
  }, [acceptToken, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg-secondary)] px-4">
      <div className="w-full max-w-md bg-white border border-[var(--color-border)] rounded-2xl shadow-sm p-8 text-center">
        {error ? (
          <>
            <div className="mx-auto w-12 h-12 rounded-full bg-red-100 flex items-center justify-center mb-3">
              <AlertCircle size={24} className="text-red-700" />
            </div>
            <h1 className="text-xl font-bold text-[var(--color-text-primary)] mb-2">Sign-in failed</h1>
            <p className="text-sm text-red-700">{error}</p>
            <button onClick={() => navigate('/login', { replace: true })}
              className="mt-5 text-sm text-[var(--color-primary)] hover:underline">
              Back to sign in
            </button>
          </>
        ) : (
          <>
            <Loader2 size={36} className="animate-spin text-[var(--color-primary)] mx-auto mb-3" />
            <p className="text-sm text-[var(--color-text-secondary)]">Completing sign-in...</p>
          </>
        )}
      </div>
    </div>
  );
}
