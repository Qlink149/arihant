const { test, expect } = require('@playwright/test');
const { getRunId, cleanupRun, apiJson } = require('./helpers/api.cjs');
const { authenticatePage, refreshApiSession } = require('./helpers/auth.cjs');
const { randomE2EPhone, e2eFirstName } = require('./helpers/safety.cjs');

/**
 * SOP v3.2 verification fixes (disposable e2e DB):
 *  - Sales Dashboard shows the "Missed pickups" column
 *  - Add Customer takes several locations of interest (SOP F8) and stores them as a list
 *  - a Sales Owner that matches no account shows NO leads (it used to drop the filter and show all)
 *  - My Dashboard keeps today's pending follow-up when an agent has many old completed tasks
 */
test.describe.configure({ mode: 'serial' });
test.describe.configure({ timeout: 120_000 });

test.describe('SOP v3.2 fixes', () => {
  /** @type {string[]} */
  const phones = [];
  let adminToken;
  let runId;

  test.beforeAll(async () => {
    runId = getRunId();
    process.env.E2E_RUN_ID = runId;
    const { tokens } = await refreshApiSession();
    adminToken = tokens.access_token;
  });

  test.afterAll(async () => {
    try {
      cleanupRun(phones);
    } catch (err) {
      console.warn('cleanupRun warning:', err.message);
    }
  });

  test('Sales Dashboard has the Missed pickups column', async ({ page }) => {
    // the browser login rotates the single admin session: use that login's token for API calls
    ({ tokens: { access_token: adminToken } } = await authenticatePage(page));
    await page.goto('/sales-dashboard');
    await expect(page.getByTestId('sales-team-table')).toBeVisible({ timeout: 45000 });
    await expect(page.getByTestId('sales-team-table').getByRole('columnheader', { name: /Missed pickups/ })).toBeVisible();
    const res = await apiJson('GET', '/analytics/sales-dashboard', { token: adminToken });
    expect(res.managers.length).toBeGreaterThan(0);
    for (const m of res.managers) {
      expect(typeof m.missed_pickups).toBe('number');
      expect([true, false, null]).toContain(m.is_active);
    }
  });

  test('Add Customer: several locations of interest are saved as a list', async ({ page }) => {
    const phone = randomE2EPhone();
    const firstName = e2eFirstName(runId);
    phones.push(phone);

    ({ tokens: { access_token: adminToken } } = await authenticatePage(page));
    await page.goto('/virtual-customer');
    await expect(page.getByTestId('virtual-customer-title')).toBeVisible();
    await page.getByTestId('add-customer-btn').click();
    await expect(page.getByRole('heading', { name: 'Add New Customer' })).toBeVisible();
    await page.getByPlaceholder('First Name').fill(firstName);
    await page.getByPlaceholder('+91 XXXXX XXXXX').fill(phone);

    await page.getByTestId('add-customer-location').click();
    const options = page.getByRole('menuitemcheckbox');
    await expect(options.first()).toBeVisible({ timeout: 15000 });
    const first = (await options.nth(0).innerText()).trim();
    const second = (await options.nth(1).innerText()).trim();
    await options.nth(0).click();
    await options.nth(1).click();
    await page.keyboard.press('Escape');

    await page.getByRole('button', { name: 'Add Customer' }).click();
    await expect(page.getByRole('heading', { name: 'Add New Customer' })).toBeHidden({ timeout: 15000 });

    const found = await apiJson('GET', `/leads?search=${encodeURIComponent(phone)}`, { token: adminToken });
    const lead = (found.leads || found).find((l) => (l.phone || '').includes(phone.slice(-10)));
    expect(lead, 'created lead is found').toBeTruthy();
    const loc = Array.isArray(lead.location) ? lead.location : [lead.location];
    expect(loc).toEqual(expect.arrayContaining([first, second]));
  });

  test('a Sales Owner that matches no account shows no leads', async () => {
    adminToken = (await refreshApiSession()).tokens.access_token;
    const all = await apiJson('GET', '/leads?limit=5', { token: adminToken });
    expect((all.leads || all).length).toBeGreaterThan(0);
    const stale = await apiJson('GET', '/leads?sales_owner=Roshini-no-such-account&limit=5', { token: adminToken });
    expect((stale.leads || stale).length).toBe(0);
  });
});
