const { test, expect } = require('@playwright/test');
const { authenticatePage } = require('./helpers/auth.cjs');

/**
 * Release smoke: the dashboards touched by the Meta Ads / RNR / location / normalization work
 * must render without a crash (uncaught page error or the route error boundary), the Marketing
 * page must show the Meta Ads section with data and sync status, and the marketing APIs must be
 * admin-only server-side (SOP v3.1 s3).
 */
test.describe.configure({ mode: 'serial' });

function trackErrors(page) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  return errors;
}

async function expectNoCrash(page, errors) {
  await expect(page.getByText(/something went wrong/i)).toHaveCount(0);
  expect(errors, errors.join('\n')).toEqual([]);
}

test.describe('Dashboards smoke (admin)', () => {
  test('Marketing page: Meta Ads section loads with data and sync status', async ({ page }) => {
    const errors = trackErrors(page);
    await authenticatePage(page);
    await page.goto('/marketing-dashboard');

    await expect(page.getByTestId('marketing-dashboard')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('meta-ads-section')).toBeVisible();
    await expect(page.getByTestId('meta-ads-last-sync')).toContainText(/Last synced|Never synced/);
    await expect(page.getByTestId('meta-ads-project-filter')).toBeVisible();

    // widen the range so the synced Jul-Sep data is inside it, then data (not the empty state) must show
    await page.getByTestId('meta-ads-date-from').fill('2026-07-09');
    await page.getByTestId('meta-ads-date-to').fill('2026-10-07');
    await expect(page.getByTestId('meta-ads-empty-state')).toHaveCount(0, { timeout: 20000 });
    await expect(page.getByTestId('meta-ads-section').getByText('Spend', { exact: true })).toBeVisible();
    await expect(page.getByTestId('meta-ads-section').getByText('CPL', { exact: true })).toBeVisible();

    // existing manual-entry section is still there
    await expect(page.getByTestId('add-spend-btn')).toBeVisible();
    await expectNoCrash(page, errors);
  });

  for (const [name, path, testid] of [
    ['Org dashboard', '/dashboard', 'dashboard-greeting'],
    ['Sales dashboard', '/sales-dashboard', 'sales-dashboard-title'],
    ['Virtual Customer (leads + location filter)', '/virtual-customer', 'location-filter'],
  ]) {
    test(`${name} renders without a crash`, async ({ page }) => {
      const errors = trackErrors(page);
      await authenticatePage(page);
      await page.goto(path);
      await expect(page.getByTestId(testid)).toBeVisible({ timeout: 45000 });
      await expectNoCrash(page, errors);
    });
  }

  test('My Dashboard renders without a crash', async ({ page }) => {
    const errors = trackErrors(page);
    await authenticatePage(page);
    await page.goto('/my-dashboard');
    await expect(page.getByTestId('lead-overview-grid')).toBeVisible({ timeout: 45000 });
    await expectNoCrash(page, errors);
  });
});

test.describe('Marketing is admin-only (rep)', () => {
  test('rep is redirected away and the APIs return 403', async ({ page }) => {
    const { tokens } = await authenticatePage(page, {
      email: process.env.E2E_REP_EMAIL,
      password: process.env.E2E_REP_PASSWORD,
    });
    await page.goto('/marketing-dashboard');
    await expect(page).not.toHaveURL(/marketing-dashboard/, { timeout: 15000 });

    const headers = { Authorization: `Bearer ${tokens.access_token}` };
    for (const url of ['/api/marketing/dashboard', '/api/meta-ads/dashboard', '/api/meta-ads/last-sync']) {
      const r = await page.request.get(`${process.env.E2E_API_URL}${url}`, { headers });
      expect(r.status(), url).toBe(403);
    }
  });
});
