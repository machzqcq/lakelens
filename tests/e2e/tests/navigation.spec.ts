import { test, expect } from '../fixtures';

const PAGES = [
  { path: '/',                  heading: /Dashboard|Total Cost/i },
  { path: '/cost-explorer',     heading: /Cost Explorer/i },
  { path: '/user-footprint',    heading: /User Footprint/i },
  { path: '/trends',            heading: /Trends/i },
  { path: '/compute',           heading: /Compute Resources/i },
  { path: '/analytics',         heading: /Advanced Analytics|Anomalies/i },
  { path: '/chatbot',           heading: /Chatbot/i },
  { path: '/admin/users',       heading: /Users/i },
  { path: '/admin/roles',       heading: /Roles/i },
];

for (const { path, heading } of PAGES) {
  test(`page ${path} renders for admin without console errors`, async ({ adminPage: page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(`console.error: ${msg.text()}`);
    });

    await page.goto(path);
    await expect(page.getByRole('heading', { name: heading }).first()).toBeVisible({ timeout: 10_000 });

    // Filter out the noise that's normal in dev (network 404 on optional assets, etc.)
    const real = errors.filter((e) =>
      !/devtools|favicon|ResizeObserver|net::ERR_FAILED.*\.map/i.test(e),
    );
    expect(real, `Console errors on ${path}:\n${real.join('\n')}`).toEqual([]);
  });
}

test('theme switcher floats top-right and opens menu', async ({ adminPage: page }) => {
  await page.goto('/');
  const btn = page.getByRole('button', { name: /switch theme/i });
  await expect(btn).toBeVisible();
  await btn.click();
  // Menu shows all six themes
  for (const name of ['Light', 'Dark', 'Midnight', 'Forest', 'Sunset', 'Ocean']) {
    await expect(page.getByText(name, { exact: true })).toBeVisible();
  }
});
