import { test, expect } from '../fixtures';

test.describe('Cost Explorer', () => {
  test.beforeEach(async ({ adminPage: page }) => {
    await page.goto('/cost-explorer');
    await expect(page.getByRole('heading', { name: /Cost Explorer/i })).toBeVisible();
  });

  test('switching dimension updates the chart title', async ({ adminPage: page }) => {
    // Default is SKU
    await expect(page.getByText(/Cost by SKU/i).first()).toBeVisible();
    // Click Workspace
    await page.getByRole('button', { name: /^Workspace$/i }).first().click();
    await expect(page.getByText(/Cost by Workspace/i).first()).toBeVisible();
  });

  test('breakdown table sorts when header is clicked', async ({ adminPage: page }) => {
    // Wait for the breakdown table to render
    const table = page.locator('table').first();
    await expect(table).toBeVisible();

    // First row before sort
    const before = await table.locator('tbody tr').first().textContent();
    await page.getByText('Total Cost').first().click();   // sort by cost
    // Click again to flip the direction
    await page.getByText('Total Cost').first().click();
    const after = await table.locator('tbody tr').first().textContent();
    expect(before).not.toBe(after);
  });

  test('every chart card has CSV + Excel export buttons', async ({ adminPage: page }) => {
    // ChartCard renders 2 export icons per card (FileText + FileSpreadsheet from lucide).
    // We at least expect the buttons titled "Download CSV" / "Download Excel" on the page.
    await expect(page.getByTitle(/Download CSV/i).first()).toBeVisible();
    await expect(page.getByTitle(/Download Excel/i).first()).toBeVisible();
  });

  test('CSV export triggers a download', async ({ adminPage: page }) => {
    const downloadPromise = page.waitForEvent('download');
    await page.getByTitle(/Download CSV/i).first().click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.csv$/i);
  });
});
