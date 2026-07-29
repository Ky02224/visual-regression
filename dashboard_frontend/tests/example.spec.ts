import { test, expect } from '@playwright/test';

test('dashboard frontend shell loads', async ({ page }) => {
  const response = await page.goto('/demo/index.html?lang=en-US', { waitUntil: 'domcontentloaded' });
  expect(response?.ok()).toBeTruthy();
  await expect(page).toHaveTitle(/halo/i);
});
