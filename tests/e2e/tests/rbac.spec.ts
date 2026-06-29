/**
 * RBAC visibility: non-admin users must not see admin nav items, and direct
 * URL access to /admin/* must redirect home.
 *
 * We register a fresh user via the API, verify them via DB, then drive the
 * browser as that user.
 */

import { test, expect, type APIRequestContext } from '@playwright/test';

const BACKEND = process.env.E2E_BACKEND_URL || 'http://localhost:58000';
const FRONTEND = process.env.E2E_FRONTEND_URL || 'http://localhost:53000';

async function makeVerifiedUser(api: APIRequestContext): Promise<{ email: string; password: string }> {
  const id = Math.random().toString(36).slice(2, 10);
  const email = `e2e-${id}@test.local`;
  const password = 'E2eTestPw1234!';

  // Register
  let r = await api.post(`${BACKEND}/api/auth/register`, {
    data: { email, password, full_name: 'E2E User' },
  });
  expect(r.status(), `register ${email}`).toBe(201);

  // Fetch the verification token via the dev endpoint... actually that one
  // only returns the bootstrap admin's creds. We instead read the token
  // from the DB by hitting an internal helper. Simpler: log in as admin and
  // query the verification tokens table via raw psql is messy; we just
  // grab the token via the email log (dev mode) -- not available over HTTP.
  //
  // For E2E, the cleanest path is: drive the verify-email URL with the
  // most-recent token we can discover. The verification token isn't exposed
  // via any API, so we use the postgres connection directly:
  const { Client } = require('pg');
  const pg = new Client({
    host: process.env.E2E_DB_HOST || 'localhost',
    port: Number(process.env.E2E_DB_PORT || 55432),
    database: process.env.E2E_DB_NAME || 'dbx_cost_test',
    user: process.env.E2E_DB_USER || 'test_user',
    password: process.env.E2E_DB_PASS || 'test_pass',
  });
  await pg.connect();
  const res = await pg.query(
    `SELECT t.token FROM auth_email_verification_tokens t
       JOIN auth_users u ON u.id = t.user_id
      WHERE u.email = $1 AND t.used_at IS NULL
      ORDER BY t.created_at DESC LIMIT 1`,
    [email],
  );
  await pg.end();

  const token = res.rows[0]?.token;
  expect(token, `verification token for ${email}`).toBeTruthy();

  r = await api.get(`${BACKEND}/api/auth/verify-email?token=${token}`);
  expect(r.status(), 'verify-email').toBe(200);

  return { email, password };
}

test.describe('Non-admin RBAC', () => {
  test.skip(
    !!process.env.SKIP_RBAC_E2E,
    'set SKIP_RBAC_E2E=1 if `pg` npm package is unavailable',
  );

  test('regular user does not see admin nav items', async ({ page, request }) => {
    const creds = await makeVerifiedUser(request);

    await page.goto(`${FRONTEND}/login`);
    await page.locator('input[type="email"]').fill(creds.email);
    await page.locator('input[type="password"]').fill(creds.password);
    await page.getByRole('button', { name: /^sign in$/i }).click();
    await page.waitForURL((u) => !u.pathname.startsWith('/login'));

    // Admin nav items should NOT be visible in the sidebar
    const sidebar = page.locator('aside');
    await expect(sidebar.getByRole('link', { name: /^Users$/i })).toHaveCount(0);
    await expect(sidebar.getByRole('link', { name: /^Roles$/i })).toHaveCount(0);
  });

  test('direct URL to /admin/users redirects home for non-admin', async ({ page, request }) => {
    const creds = await makeVerifiedUser(request);
    await page.goto(`${FRONTEND}/login`);
    await page.locator('input[type="email"]').fill(creds.email);
    await page.locator('input[type="password"]').fill(creds.password);
    await page.getByRole('button', { name: /^sign in$/i }).click();
    await page.waitForURL((u) => !u.pathname.startsWith('/login'));

    await page.goto(`${FRONTEND}/admin/users`);
    // RequireAdmin redirects to /
    await expect(page).toHaveURL((u) => u.pathname === '/');
  });
});
