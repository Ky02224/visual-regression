/**
 * End-to-end coverage of the dashboard itself.
 *
 * The only spec that existed was `example.spec.ts`: it loaded the demo portal
 * page and asserted its title. That is the fixture site the tool takes pictures
 * of, not the product — so the CI step named "Run Playwright E2E tests" was
 * passing without ever loading The Lens, logging in, or rendering a route.
 *
 * These drive the real login form against the real API. Credentials come from
 * the same environment variables the server bootstraps with, so CI and a local
 * run agree without a fixture.
 */
import { expect, test } from '@playwright/test';

const ADMIN_EMAIL = process.env.LENS_ADMIN_EMAIL || 'admin';
const ADMIN_PASSWORD = process.env.LENS_ADMIN_PASSWORD || 'admin1234';

async function signIn(page) {
  await page.goto('/login');
  // The fields are labelled Username/Password; match on the accessible name so
  // this survives a restyle.
  await page.getByLabel(/username/i).fill(ADMIN_EMAIL);
  await page.getByLabel(/password/i).fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/(?!login)/, { timeout: 15000 });
}

test.describe('authentication', () => {
  test('an unauthenticated visitor is sent to the login page', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole('button', { name: /sign in/i })).toBeVisible();
  });

  test('bad credentials are rejected and do not sign the visitor in', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel(/username/i).fill(ADMIN_EMAIL);
    await page.getByLabel(/password/i).fill('definitely-not-the-password');
    await page.getByRole('button', { name: /sign in/i }).click();

    await expect(page).toHaveURL(/\/login/);
  });

  test('valid credentials reach the dashboard', async ({ page }) => {
    await signIn(page);

    await expect(page.getByRole('heading', { name: /dashboard/i }).first()).toBeVisible();
  });
});

test.describe('navigation', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  // Every route reachable from the sidebar. A page that throws renders the
  // error boundary or an empty shell, so asserting on its own heading is what
  // distinguishes "loaded" from "mounted and blew up".
  const routes: Array<[string, RegExp]> = [
    ['Actions', /actions/i],
    ['Baselines', /baselines/i],
    ['Builds', /builds/i],
    ['Integrations', /integrations/i],
    ['Users', /user management/i],
  ];

  for (const [label, heading] of routes) {
    test(`${label} renders`, async ({ page }) => {
      await page.getByRole('link', { name: label, exact: true }).click();
      await expect(page.getByRole('heading', { name: heading }).first()).toBeVisible({ timeout: 15000 });
    });
  }

  test('an unknown route shows the 404 page rather than a blank shell', async ({ page }) => {
    await page.goto('/no-such-route-exists');

    await expect(page.getByText(/404/)).toBeVisible();
  });

  test('signing out returns to the login page and the session no longer works', async ({ page }) => {
    await page.getByRole('button', { name: /sign out/i }).click();
    await expect(page).toHaveURL(/\/login/);

    // Going back to a protected route must not restore the old session.
    await page.goto('/');
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe('api surface', () => {
  test('an unknown API path answers JSON, not the SPA shell', async ({ request }) => {
    const response = await request.get('/api/definitely-not-a-route');

    expect(response.status()).toBe(404);
    expect(response.headers()['content-type'] || '').toContain('application/json');
  });

  test('the dashboard API refuses an unauthenticated caller', async ({ request }) => {
    const response = await request.get('/api/dashboard');

    expect(response.status()).toBe(401);
  });
});
