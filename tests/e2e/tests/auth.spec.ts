import { test, expect, loginAs, ADMIN_EMAIL, ADMIN_PASSWORD } from '../fixtures';

test.describe('Login page', () => {
  test('renders branding and OAuth buttons', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByRole('heading', { name: /sign in/i })).toBeVisible();
    // Brand panel on the left
    await expect(page.getByText(/Databricks Billing/i).first()).toBeVisible();
    // Three OAuth buttons rendered (disabled when no creds configured — we
    // still expect the labels to be there).
    await expect(page.getByText(/continue with google/i)).toBeVisible();
    await expect(page.getByText(/continue with microsoft/i)).toBeVisible();
    await expect(page.getByText(/continue with github/i)).toBeVisible();
  });

  test('pre-fills creds when EXPOSE_DEV_CREDENTIALS=true', async ({ page }) => {
    await page.goto('/login');
    await expect(page.locator('input[type="email"]')).toHaveValue(ADMIN_EMAIL);
    await expect(page.locator('input[type="password"]')).toHaveValue(ADMIN_PASSWORD);
    // The little DEV hint should be visible
    await expect(page.getByText(/Pre-filled from/i)).toBeVisible();
  });

  test('wrong password shows an inline error', async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="email"]').fill(ADMIN_EMAIL);
    await page.locator('input[type="password"]').fill('definitely-wrong');
    await page.getByRole('button', { name: /^sign in$/i }).click();
    await expect(page.getByText(/invalid email or password/i)).toBeVisible();
    // Still on /login
    await expect(page).toHaveURL(/\/login/);
  });

  test('successful login redirects to dashboard', async ({ page }) => {
    await loginAs(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await expect(page).toHaveURL((url) => url.pathname === '/');
    // Sidebar shows the admin email
    await expect(page.getByText(ADMIN_EMAIL).first()).toBeVisible();
  });
});

test.describe('Protected routes', () => {
  test('unauthenticated visit to / bounces to /login', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/login/);
  });

  test('logout clears session and returns to /login', async ({ adminPage: page }) => {
    await page.getByRole('button', { name: /sign out/i }).click();
    await expect(page).toHaveURL(/\/login/);
  });
});
