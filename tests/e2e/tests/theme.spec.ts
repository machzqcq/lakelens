/**
 * Theme switcher: verify all six themes apply data-theme on <html> and
 * persist across reload via localStorage.
 */

import { test, expect } from '../fixtures';

const THEMES = [
  { label: 'Light',    name: 'light' },
  { label: 'Dark',     name: 'dark' },
  { label: 'Midnight', name: 'midnight' },
  { label: 'Forest',   name: 'forest' },
  { label: 'Sunset',   name: 'sunset' },
  { label: 'Ocean',    name: 'ocean' },
];

for (const { label, name } of THEMES) {
  test(`switching to ${label} sets data-theme=${name}`, async ({ adminPage: page }) => {
    await page.goto('/');
    // Open the switcher dropdown
    await page.getByRole('button', { name: /switch theme/i }).click();
    // Pick the theme
    await page.getByText(label, { exact: true }).click();

    // The attribute on <html> should flip
    await expect.poll(async () =>
      page.evaluate(() => document.documentElement.getAttribute('data-theme'))
    ).toBe(name);

    // And it should persist after a reload
    await page.reload();
    await expect.poll(async () =>
      page.evaluate(() => document.documentElement.getAttribute('data-theme'))
    ).toBe(name);
  });
}
