const { test, expect } = require('@playwright/test');
const { authenticatePage } = require('./helpers/auth.cjs');

/**
 * batch2 item 3 (#56 hardening): the Lead Overview grid must load
 * independently of getData()/getReps() - a transient failure in either must
 * never leave the overview stuck empty/loading forever, and a genuine
 * overview-fetch failure must show a visible error + retry, never an empty
 * grid that looks like "no leads".
 */
test.describe.configure({ mode: 'serial' });

test.describe('My Dashboard overview resilience (#56 hardening)', () => {
  test('overview still loads when getReps() (team-status) fails', async ({ page }) => {
    await page.route('**/api/activity/team-status', (route) => route.fulfill({ status: 500, body: '{}' }));

    await authenticatePage(page);
    await page.goto('/my-dashboard');

    // The overview grid must appear even though team-status 500'd.
    await expect(page.getByTestId('lead-overview-grid')).toBeVisible({ timeout: 30000 });
    // And it must not be stuck showing the error state instead.
    await expect(page.getByTestId('lead-overview-error')).toHaveCount(0);
  });

  test('overview shows a visible error + retry when the overview fetch itself fails', async ({ page }) => {
    await page.route('**/api/my-dashboard/lead-overview**', (route) =>
      route.fulfill({ status: 500, body: '{}' })
    );

    await authenticatePage(page);
    await page.goto('/my-dashboard');

    // Must show the error state with a Retry control, never an empty grid
    // (an empty grid would be indistinguishable from "no leads").
    await expect(page.getByTestId('lead-overview-error')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('lead-overview-error').getByRole('button', { name: /retry/i })).toBeVisible();
    await expect(page.getByTestId('lead-overview-grid')).toHaveCount(0);

    // Retry succeeds once the route is unblocked.
    await page.unroute('**/api/my-dashboard/lead-overview**');
    await page.getByTestId('lead-overview-error').getByRole('button', { name: /retry/i }).click();
    await expect(page.getByTestId('lead-overview-grid')).toBeVisible({ timeout: 30000 });
  });
});
