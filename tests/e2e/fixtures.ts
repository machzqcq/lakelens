/**
 * Reusable Playwright fixtures.
 *
 * - `adminPage` — a `page` that's already logged in as the bootstrap admin.
 *                  Reuses a single storage state across the test suite so
 *                  we don't pay the login cost per test.
 *
 * Storage state is captured once via `auth.setup.ts` (a setup project) and
 * loaded with `storageState`. See playwright.config.ts if you want to wire
 * setup projects.
 */

import { test as base, expect, type Page } from '@playwright/test';

export const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.local';
export const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'TestAdmin12345!';

interface Fixtures {
  adminPage: Page;
}

async function loginAs(page: Page, email: string, password: string) {
  await page.goto('/login');
  // Clear pre-filled values from EXPOSE_DEV_CREDENTIALS=true so we test
  // the real form behavior.
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill(password);
  await page.getByRole('button', { name: /^sign in$/i }).click();
  // Wait for redirect away from /login
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 15_000 });
}

export const test = base.extend<Fixtures>({
  adminPage: async ({ page }, use) => {
    await loginAs(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await use(page);
  },
});

export { expect, loginAs };
