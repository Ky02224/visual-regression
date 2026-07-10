import { test, expect } from '@playwright/test';

test('demo index loads and shows locale badge', async ({ page }) => {
  await page.goto('/demo/index.html?lang=en-US');
  await expect(page.locator('[data-locale-badge]')).toHaveText(/English \(US\)/i);
});
