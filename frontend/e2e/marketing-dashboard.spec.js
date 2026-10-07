const fs = require('fs');
const { test, expect } = require('@playwright/test');
const { authenticatePage } = require('./helpers/auth.cjs');

/**
 * Marketing dashboard (Meta Ads): KPIs with period deltas, trend, project funnel, the
 * campaign -> ad set -> ad drill-down, the per-entity drawer, filters, CSV export, the admin
 * "Sync now" flow, the collapsed Offline-channels panel, and server-side admin-only access.
 *
 * Needs the e2e stack with Meta Ads data synced into the e2e DB (the default 30-day window
 * ends ~2026-10-07; Meta's last spend day is 2026-09-24, so the 30-day preset has data and
 * the 7-day preset is legitimately empty).
 */
test.describe.configure({ mode: 'serial' });

function trackErrors(page) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  return errors;
}

async function openMarketing(page) {
  await authenticatePage(page);
  await page.goto('/marketing-dashboard');
  await expect(page.getByTestId('meta-ads-section')).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('meta-kpi-value-spend')).not.toHaveText('—', { timeout: 30000 });
}

test.describe('Marketing dashboard (admin)', () => {
  test('KPIs, deltas, trend chart and legend render', async ({ page }) => {
    const errors = trackErrors(page);
    await openMarketing(page);

    for (const k of ['spend', 'leads', 'cpl', 'impressions', 'clicks', 'ctr', 'cpm']) {
      await expect(page.getByTestId(`meta-kpi-${k}`)).toBeVisible();
      await expect(page.getByTestId(`meta-kpi-delta-${k}`)).toBeVisible();
    }
    await expect(page.getByTestId('meta-kpi-value-spend')).toContainText('₹');

    await expect(page.getByTestId('meta-trend')).toBeVisible();
    // Meta's last spend day in the e2e data is 2026-09-24: the trailing gap is called out, not hidden
    await expect(page.getByTestId('meta-trend-gap-note')).toContainText('2026-09-24');
    await expect(page.getByTestId('meta-ads-chart-legend')).toContainText('Spend');
    await page.getByTestId('meta-trend-mode-cpl').click();
    await expect(page.getByTestId('meta-ads-chart-legend')).toContainText('Cost per lead');
    await page.getByTestId('meta-trend-mode-reach').click();
    await expect(page.getByTestId('meta-ads-chart-legend')).toContainText('Impressions');
    expect(errors, errors.join('\n')).toEqual([]);
  });

  test('date presets change the numbers; an empty range shows the empty state', async ({ page }) => {
    await openMarketing(page);
    const thirty = await page.getByTestId('meta-kpi-value-spend').innerText();

    await page.getByTestId('meta-preset-90d').click();
    await expect(page.getByTestId('meta-kpi-value-spend')).not.toHaveText(thirty, { timeout: 20000 });

    // Meta has no spend in the last 7 days of the e2e data -> honest empty state, not zeros
    await page.getByTestId('meta-preset-7d').click();
    await expect(page.getByTestId('meta-ads-empty-state')).toBeVisible({ timeout: 20000 });
  });

  test('project filter changes the KPIs', async ({ page }) => {
    await openMarketing(page);
    const before = await page.getByTestId('meta-kpi-value-spend').innerText();
    await page.getByTestId('meta-ads-project-filter').click();
    await page.getByRole('menuitemcheckbox', { name: /ECR - Reserve 16/ }).click();
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('meta-kpi-value-spend')).not.toHaveText(before, { timeout: 20000 });
    await expect(page.getByTestId('meta-ads-project-filter')).toContainText(/ECR - Reserve 16/);
  });

  test('project funnel shows Meta vs CRM columns and the definitions note', async ({ page }) => {
    await openMarketing(page);
    await expect(page.getByTestId('meta-funnel')).toBeVisible();
    await expect(page.getByTestId('meta-funnel-note')).toContainText('different numbers');
    await expect(page.getByTestId('meta-funnel-row-ECR - Reserve 16')).toBeVisible();
    await expect(page.getByTestId('meta-funnel-total')).toBeVisible();
    await expect(page.getByTestId('meta-attribution')).toContainText('Campaign attribution');
  });

  test('campaign -> ad set -> ad drill-down, then the entity drawer', async ({ page }) => {
    await openMarketing(page);
    const table = page.getByTestId('meta-entities');
    await expect(table.locator('[data-testid^="meta-row-campaign-"]').first()).toBeVisible({ timeout: 20000 });

    await table.locator('[data-testid^="meta-expand-campaign-"]').first().click();
    const adsetRow = table.locator('[data-testid^="meta-row-adset-"]').first();
    await expect(adsetRow).toBeVisible({ timeout: 20000 });

    await table.locator('[data-testid^="meta-expand-adset-"]').first().click();
    await expect(table.locator('[data-testid^="meta-row-ad-"]').first()).toBeVisible({ timeout: 20000 });

    // open the campaign in the drawer: per-day rows incl. reach/frequency
    await table.locator('[data-testid^="meta-open-campaign-"]').first().click();
    const drawer = page.getByTestId('meta-entity-drawer');
    await expect(drawer).toBeVisible();
    await expect(page.getByTestId('meta-drawer-table')).toBeVisible({ timeout: 20000 });
    await expect(drawer.getByRole('columnheader', { name: 'Reach' })).toBeVisible();
    await expect(drawer.getByRole('columnheader', { name: 'Freq.' })).toBeVisible();
    expect(await drawer.locator('[data-testid^="meta-drawer-day-"]').count()).toBeGreaterThan(0);
    await page.keyboard.press('Escape');
    await expect(drawer).toHaveCount(0);
  });

  test('status filter, search and sorting', async ({ page }) => {
    await openMarketing(page);
    const count = page.getByTestId('meta-entities-count');
    await expect(count).toContainText(/Showing \d+ of \d+ campaigns/, { timeout: 20000 });
    const all = await count.innerText();

    await page.getByTestId('meta-status-paused').click();
    await expect(count).not.toHaveText(all, { timeout: 20000 });
    const rows = page.getByTestId('meta-entities').locator('[data-testid^="meta-row-campaign-"]');
    for (const pill of await rows.locator('td:nth-child(2) span').allInnerTexts()) {
      expect(pill).toBe('Paused');
    }
    await page.getByTestId('meta-status-all').click();

    await page.getByTestId('meta-entity-search').fill('zzz-no-such-campaign');
    await expect(page.getByTestId('meta-entities-empty')).toBeVisible({ timeout: 20000 });
    await page.getByTestId('meta-entity-search').fill('R-16');
    await expect(rows.first()).toBeVisible({ timeout: 20000 });
    for (const t of await rows.locator('button[data-testid^="meta-open-campaign-"]').allInnerTexts()) {
      expect(t.toLowerCase()).toContain('r-16');
    }

    // sorting by spend ascending flips the first row
    await page.getByTestId('meta-entity-search').fill('');
    await expect(rows.first()).toBeVisible({ timeout: 20000 });
    const firstDesc = await rows.first().getAttribute('data-testid');
    await page.getByTestId('meta-sort-spend').click(); // already spend desc -> asc
    await expect.poll(async () => rows.first().getAttribute('data-testid'), { timeout: 20000 }).not.toBe(firstDesc);
  });

  test('Export CSV downloads the campaign rows', async ({ page }) => {
    await openMarketing(page);
    await expect(page.getByTestId('meta-entities').locator('[data-testid^="meta-row-campaign-"]').first()).toBeVisible({ timeout: 20000 });
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('meta-export-csv').click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/^meta-ads-campaigns_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.csv$/);
    const text = fs.readFileSync(await download.path(), 'utf8');
    expect(text).toContain('Campaign,Campaign ID,Status,Objective,Project,Spend');
    expect(text.split('\r\n').length).toBeGreaterThan(2);
  });

  test('Sync now: disables while running, then refreshes and re-enables', async ({ page }) => {
    await openMarketing(page);
    let phase = 'idle';
    let polls = 0;
    await page.route('**/api/meta-ads/sync', async (route) => {
      phase = 'running';
      await route.fulfill({ json: { started: true } });
    });
    await page.route('**/api/meta-ads/last-sync', async (route) => {
      if (phase === 'idle') return route.continue();
      polls += 1;
      if (polls < 2) {
        return route.fulfill({ json: { status: 'ok', started_at: '2026-10-07T00:00:00+00:00', running: true } });
      }
      return route.fulfill({ json: { status: 'ok', started_at: '2026-10-07T12:00:00+00:00', running: false } });
    });

    const btn = page.getByTestId('meta-ads-sync-now');
    await expect(btn).toHaveText(/Sync now/);
    await btn.click();
    await expect(btn).toBeDisabled();
    await expect(btn).toHaveText(/Syncing/);
    await expect(page.getByTestId('meta-ads-last-sync')).toContainText('Sync in progress');
    await expect(btn).toBeEnabled({ timeout: 30000 });
    await expect(btn).toHaveText(/Sync now/);
    await expect(page.getByTestId('meta-ads-last-sync')).toContainText('Last synced');
    await expect(page.getByTestId('meta-kpi-value-spend')).not.toHaveText('—');
  });

  test('Offline channels (manual entry) is collapsed below the Meta section and expands', async ({ page }) => {
    await openMarketing(page);
    const toggle = page.getByTestId('offline-channels-toggle');
    await expect(toggle).toContainText('Offline channels (manual entry)');
    await expect(page.getByTestId('marketing-metrics')).toHaveCount(0);

    // it sits below the Meta section
    const metaBox = await page.getByTestId('meta-ads-section').boundingBox();
    const toggleBox = await toggle.boundingBox();
    expect(toggleBox.y).toBeGreaterThan(metaBox.y + metaBox.height - 1);

    await toggle.click();
    await expect(page.getByTestId('marketing-metrics')).toBeVisible();

    // the header button still opens the add-spend modal
    await page.getByTestId('add-spend-btn').click();
    await expect(page.getByTestId('add-spend-modal')).toBeVisible();
  });
});

test.describe('Marketing dashboard is admin-only (rep)', () => {
  test('new Meta Ads endpoints return 403 for a rep', async ({ page }) => {
    const { tokens } = await authenticatePage(page, {
      email: process.env.E2E_REP_EMAIL,
      password: process.env.E2E_REP_PASSWORD,
    });
    const headers = { Authorization: `Bearer ${tokens.access_token}` };
    const base = process.env.E2E_API_URL;
    for (const url of [
      '/api/meta-ads/overview',
      '/api/meta-ads/breakdown?level=campaign',
      '/api/meta-ads/entity/campaign/123/daily',
      '/api/meta-ads/project-funnel',
    ]) {
      const r = await page.request.get(`${base}${url}`, { headers });
      expect(r.status(), url).toBe(403);
    }
    const sync = await page.request.post(`${base}/api/meta-ads/sync`, { headers });
    expect(sync.status()).toBe(403);
  });
});
