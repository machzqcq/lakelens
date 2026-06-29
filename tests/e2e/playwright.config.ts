import { defineConfig, devices } from '@playwright/test';

/**
 * E2E config — points at the isolated test stack from docker-compose.test.yml.
 *
 *   Frontend:  http://localhost:53000
 *   Backend:   http://localhost:58000
 *
 * Spin up the stack before running:
 *   docker compose -f tests/docker-compose.test.yml up -d --build
 */
export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'html',

  use: {
    baseURL: process.env.E2E_FRONTEND_URL || 'http://localhost:53000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    // Uncomment to run cross-browser:
    // { name: 'firefox',  use: { ...devices['Desktop Firefox'] } },
    // { name: 'webkit',   use: { ...devices['Desktop Safari'] } },
  ],

  // If you want Playwright to bring the stack up on demand (useful for
  // CI in a single container), uncomment:
  // webServer: {
  //   command: 'docker compose -f ../docker-compose.test.yml up -d --build',
  //   url: 'http://localhost:53000',
  //   reuseExistingServer: true,
  //   timeout: 120_000,
  // },
});
