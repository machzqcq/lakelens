import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  type AuthMe,
  authLogin,
  authMe,
  getAuthToken,
  setAuthToken,
  setOnUnauthorized,
} from '../api/client';

type AuthState =
  | { status: 'loading' }
  | { status: 'anonymous' }
  | { status: 'authenticated'; user: AuthMe };

interface AuthContextValue {
  state: AuthState;
  user: AuthMe | null;
  isAdmin: boolean;
  login: (email: string, password: string) => Promise<AuthMe>;
  logout: () => void;
  /** Used by the OAuth callback page to drop a token in and refresh the user profile. */
  acceptToken: (token: string) => Promise<AuthMe>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(getAuthToken() ? { status: 'loading' } : { status: 'anonymous' });

  const refresh = useCallback(async () => {
    if (!getAuthToken()) {
      setState({ status: 'anonymous' });
      return;
    }
    try {
      const me = await authMe();
      setState({ status: 'authenticated', user: me });
    } catch {
      setAuthToken(null);
      setState({ status: 'anonymous' });
    }
  }, []);

  // Initial load — if a token is present, fetch /me to validate it
  useEffect(() => {
    refresh();
  }, [refresh]);

  // Wire client.ts -> 401 means we're logged out
  useEffect(() => {
    setOnUnauthorized(() => setState({ status: 'anonymous' }));
    return () => setOnUnauthorized(null);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const resp = await authLogin(email, password);
    setAuthToken(resp.access_token);
    setState({ status: 'authenticated', user: resp.user });
    return resp.user;
  }, []);

  const acceptToken = useCallback(async (token: string) => {
    setAuthToken(token);
    const me = await authMe();
    setState({ status: 'authenticated', user: me });
    return me;
  }, []);

  const logout = useCallback(() => {
    setAuthToken(null);
    setState({ status: 'anonymous' });
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    state,
    user: state.status === 'authenticated' ? state.user : null,
    isAdmin: state.status === 'authenticated' && state.user.is_admin,
    login,
    logout,
    acceptToken,
    refresh,
  }), [state, login, logout, acceptToken, refresh]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
