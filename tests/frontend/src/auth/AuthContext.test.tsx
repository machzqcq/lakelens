import { describe, expect, test, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AuthProvider, useAuth } from '@app/auth/AuthContext';
import { setAuthToken } from '@app/api/client';

function Probe() {
  const { state, user, isAdmin, login, logout } = useAuth();
  return (
    <div>
      <div data-testid="status">{state.status}</div>
      <div data-testid="email">{user?.email ?? '—'}</div>
      <div data-testid="admin">{String(isAdmin)}</div>
      <button onClick={() => login('a@b', 'pw').catch(() => {})}>login</button>
      <button onClick={logout}>logout</button>
    </div>
  );
}

const fakeMe = {
  id: 1, email: 'a@b', full_name: null,
  is_active: true, is_email_verified: true,
  roles: ['admin'], is_admin: true,
};

describe('<AuthProvider>', () => {
  beforeEach(() => {
    setAuthToken(null);
    vi.restoreAllMocks();
  });

  test('starts anonymous when no token in storage', async () => {
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'));
    expect(screen.getByTestId('email')).toHaveTextContent('—');
  });

  test('hydrates from a stored token by calling /me', async () => {
    setAuthToken('preexisting');
    vi.spyOn(global, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify(fakeMe), { status: 200, headers: { 'content-type': 'application/json' } })
    );
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(screen.getByTestId('email')).toHaveTextContent('a@b');
    expect(screen.getByTestId('admin')).toHaveTextContent('true');
  });

  test('drops to anonymous if /me returns 401', async () => {
    setAuthToken('bad-token');
    vi.spyOn(global, 'fetch').mockResolvedValueOnce(
      new Response('nope', { status: 401 })
    );
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'));
  });

  test('login updates state and persists token', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({ access_token: 'new-jwt', token_type: 'Bearer', user: fakeMe }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      )
    );
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'));

    await act(async () => {
      await userEvent.click(screen.getByText('login'));
    });
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(localStorage.getItem('auth.access_token')).toBe('new-jwt');
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  test('logout clears token + state', async () => {
    setAuthToken('existing');
    vi.spyOn(global, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify(fakeMe), { status: 200, headers: { 'content-type': 'application/json' } })
    );
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));

    await act(async () => {
      await userEvent.click(screen.getByText('logout'));
    });
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'));
    expect(localStorage.getItem('auth.access_token')).toBeNull();
  });
});
