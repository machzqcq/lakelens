/**
 * Chatbot end-to-end. Skipped unless LLM_TEST_KEY is set, because the
 * chatbot fans out to a real LLM provider and would otherwise burn $.
 *
 * To run:
 *   LLM_TEST_KEY=<google-api-key> npx playwright test chatbot.spec.ts
 */

import { test, expect } from '../fixtures';

test.skip(
  !process.env.LLM_TEST_KEY,
  'Set LLM_TEST_KEY to your Google API key to run the chatbot e2e.',
);

test('chatbot returns SQL + result + explanation', async ({ adminPage: page }) => {
  // The Chatbot page accepts an api_key in the request body — we inject it
  // via window.localStorage isn't an option, so we route the network call.
  await page.route('**/api/chat/ask', async (route, request) => {
    const body = JSON.parse(request.postData() || '{}');
    body.api_key = process.env.LLM_TEST_KEY;
    await route.continue({ postData: JSON.stringify(body) });
  });

  await page.goto('/chatbot');
  await expect(page.getByRole('heading', { name: /Chatbot/i })).toBeVisible();

  // Wait for the model list (10-min cache; first hit can be slow)
  await page.waitForResponse(
    (r) => r.url().endsWith('/api/chat/models') && r.ok(),
    { timeout: 30_000 },
  );

  await page.getByPlaceholder(/Ask a question/i).fill('How many billing rows per cloud?');
  await page.getByRole('button', { name: /^ask$/i }).click();

  // The result section eventually shows row count + the table
  await expect(page.getByText(/row.* returned/i)).toBeVisible({ timeout: 60_000 });
  // The "LLM call details" disclosure renders
  await expect(page.getByText(/LLM call details/i)).toBeVisible();
});
