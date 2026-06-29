import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import {
  getAuthToken,
  setAuthToken,
  setOnUnauthorized,
  authLogin,
  authMe,
} from '@app/api/client';

describe('auth token storage', () => {
  test('setAuthToken persists to localStorage', () => {
    setAuthToken('my-token');
    expect(getAuthToken()).toBe('my-token');
    expect(localStorage.getItem('auth.access_token')).toBe('my-token');
  });

  test('setAuthToken(null) clears storage', () => {
    setAuthToken('something');
    setAuthToken(null);
    expect(getAuthToken()).toBeNull();
  });
});

describe('request: auth header injection + 401 handling', () => {
  beforeEach(() => {
    setAuthToken(null);
    vi.restoreAllMocks();
  });

  afterEach(() => {
    setAuthToken(null);
    setOnUnauthorized(null);
  });

  test('attaches Authorization header when token is set', async () => {
    setAuthToken('xyz');
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({ id: 1, email: 'a@b', is_admin: true, roles: ['admin'], full_name: null, is_active: true, is_email_verified: true }), {
        status: 200, headers: { 'content-type': 'application/json' },
      })
    );
    await authMe();
    const [, init] = fetchSpy.mock.calls[0];
    const headers = (init?.headers ?? {}) as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer xyz');
  });

  test('does not attach header when no token is set', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({ access_token: 't', token_type: 'Bearer', user: {} }), {
        status: 200, headers: { 'content-type': 'application/json' },
      })
    );
    await authLogin('a@b', 'pw');
    const [, init] = fetchSpy.mock.calls[0];
    const headers = (init?.headers ?? {}) as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  test('401 clears token and fires onUnauthorized', async () => {
    setAuthToken('expired');
    const unauthorizedHandler = vi.fn();
    setOnUnauthorized(unauthorizedHandler);
    vi.spyOn(global, 'fetch').mockResolvedValueOnce(
      new Response('Unauthorized', { status: 401 })
    );
    await expect(authMe()).rejects.toThrow(/Unauthorized/i);
    expect(getAuthToken()).toBeNull();
    expect(unauthorizedHandler).toHaveBeenCalledOnce();
  });

  test('non-2xx surfaces the server detail message', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Email already registered' }), {
        status: 409, headers: { 'content-type': 'application/json' },
      })
    );
    await expect(authLogin('a@b', 'pw')).rejects.toThrow('Email already registered');
  });
});
