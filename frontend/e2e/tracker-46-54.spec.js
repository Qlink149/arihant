const { test, expect } = require('@playwright/test');
const {
  getRunId,
  loginApi,
  fetchMe,
  createE2ELead,
  cleanupRun,
  apiJson,
  runPython,
} = require('./helpers/api.cjs');
const { authenticatePage, refreshApiSession } = require('./helpers/auth.cjs');
const { e2eFirstName } = require('./helpers/safety.cjs');

test.describe.configure({ mode: 'serial' });
test.describe.configure({ timeout: 120_000 });

test.describe('Change Tracker 46–54 (disposable e2e DB)', () => {
  /** @type {string[]} */
  const phones = [];
  let adminToken;
  let adminMe;
  let repToken;
  let repMe;
  let runId;

  async function ensureAdminApi() {
    const { tokens, me } = await refreshApiSession();
    adminToken = tokens.access_token;
    adminMe = me;
  }

  test.beforeAll(async () => {
    runId = getRunId();
    process.env.E2E_RUN_ID = runId;
    await ensureAdminApi();
    const repEmail = process.env.E2E_REP_EMAIL || 'e2e-rep@arihant.local';
    const repPassword = process.env.E2E_REP_PASSWORD || 'E2eRep!Pass123';
    const repLogin = await loginApi(repEmail, repPassword);
    repToken = repLogin.access_token;
    repMe = await fetchMe(repToken);
  });

  test.afterAll(async () => {
    try {
      cleanupRun(phones);
    } catch (err) {
      console.warn('cleanupRun warning:', err.message);
    }
  });

  test('#46/#48 Today\'s Leads tile shows rolling 24h + re-enquiry copy', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {
      assigned_user_id: repMe.id,
      assigned_to: 'E2E Rep',
      assigned_to_name: 'E2E Rep',
      project: 'E2E Todays Leads Project',
    });
    phones.push(lead.phone);

    await authenticatePage(page, {
      email: process.env.E2E_REP_EMAIL || 'e2e-rep@arihant.local',
      password: process.env.E2E_REP_PASSWORD || 'E2eRep!Pass123',
    });
    await page.goto('/my-dashboard');
    await page.getByTestId('lead-overview-todays_leads').waitFor({ state: 'visible', timeout: 30000 });
    const tile = page.getByTestId('lead-overview-todays_leads');
    await expect(tile).toBeVisible();
    // Freshly created leads always count via the rolling-24h clause.
    await expect(tile).toContainText(/[1-9]\d*/);
    await expect(tile).toContainText(/last 24h|re-enquir/i);

    const oldLead = await createE2ELead(adminToken, {
      assigned_user_id: repMe.id,
      assigned_to: 'E2E Rep',
      assigned_to_name: 'E2E Rep',
      project: 'E2E Reenquiry Project',
    });
    phones.push(oldLead.phone);
    const twoDaysAgo = new Date(Date.now() - 48 * 3600 * 1000).toISOString();
    const nowIso = new Date().toISOString();
    runPython('scripts/e2e_fixtures.py', [
      'patch-lead',
      '--run-id',
      runId,
      '--lead-id',
      oldLead.id,
      '--json',
      JSON.stringify({
        created_at: twoDaysAgo,
        created_at_dt: twoDaysAgo,
        re_enquired_at: nowIso,
      }),
    ]);
    const overview = await apiJson('GET', '/my-dashboard/lead-overview', { token: (
      await loginApi(
        process.env.E2E_REP_EMAIL || 'e2e-rep@arihant.local',
        process.env.E2E_REP_PASSWORD || 'E2eRep!Pass123'
      )
    ).access_token });
    const todays = (overview.metrics || []).find((m) => m.key === 'todays_leads');
    expect((todays && todays.count) || 0).toBeGreaterThan(0);
  });

  test('#49 DataDna Lead Overview shows Email + Lost Reason fields', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {
      project: 'E2E DataDna Project',
    });
    phones.push(lead.phone);
    await apiJson('PUT', `/leads/${lead.id}`, {
      token: adminToken,
      body: { email: 'e2e_datadna_buyer@example.com' },
    });

    await authenticatePage(page);
    await page.goto(`/lead/${lead.id}`);
    await page.getByTestId('data-dna-grid').waitFor({ state: 'visible', timeout: 30000 });
    const toggle = page.getByTestId('lead-overview-toggle');
    if (await toggle.isVisible()) {
      const emailCard = page.getByTestId('data-dna-email');
      if (!(await emailCard.isVisible().catch(() => false))) {
        await toggle.click();
      }
    }
    await expect(page.getByTestId('data-dna-email')).toBeVisible();
    await expect(page.getByTestId('data-dna-email')).toContainText('e2e_datadna_buyer@example.com');
    await expect(page.getByTestId('data-dna-lost_reason')).toBeVisible();
  });

  test('#50 Received transfers only shows leads still assigned to me', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, { project: 'E2E Transfer Project' });
    phones.push(lead.phone);

    // Transfer lead -> rep (admin is org-editor, can transfer any lead).
    await apiJson('POST', '/leads/transfer', {
      token: adminToken,
      body: { lead_id: lead.id, to_rep: repMe.full_name, to_user_id: repMe.id },
    });

    const repLogin = await loginApi(
      process.env.E2E_REP_EMAIL || 'e2e-rep@arihant.local',
      process.env.E2E_REP_PASSWORD || 'E2eRep!Pass123'
    );
    repToken = repLogin.access_token;

    const beforeReassign = await apiJson('GET', '/transfers?direction=incoming&since_days=365', {
      token: repToken,
    });
    const beforeIds = (beforeReassign.transfers || []).map((t) => t.lead_id);
    expect(beforeIds).toContain(lead.id);

    // Reassign away from rep -> admin. Received (still-owned) view must drop it.
    await ensureAdminApi();
    await apiJson('POST', '/leads/transfer', {
      token: adminToken,
      body: { lead_id: lead.id, to_rep: adminMe.full_name, to_user_id: adminMe.id },
    });

    const repLogin2 = await loginApi(
      process.env.E2E_REP_EMAIL || 'e2e-rep@arihant.local',
      process.env.E2E_REP_PASSWORD || 'E2eRep!Pass123'
    );
    repToken = repLogin2.access_token;
    const afterReassign = await apiJson('GET', '/transfers?direction=incoming&since_days=365', {
      token: repToken,
    });
    const afterIds = (afterReassign.transfers || []).map((t) => t.lead_id);
    expect(afterIds).not.toContain(lead.id);

    // UI: My Dashboard Received tab reflects the same still-owned semantics.
    await authenticatePage(page, {
      email: process.env.E2E_REP_EMAIL || 'e2e-rep@arihant.local',
      password: process.env.E2E_REP_PASSWORD || 'E2eRep!Pass123',
    });
    await page.goto('/my-dashboard');
    await page.getByTestId('tab-transfers').click();
    await page.getByTestId('transfer-subtab-received').click();
    await expect(page.getByTestId('transfers-section')).toBeVisible();
    const firstName = e2eFirstName(runId);
    await expect(page.getByText(firstName)).toHaveCount(0);
  });

  test('#51 Location interested filter label + exact match', async ({ page }) => {
    await ensureAdminApi();
    const leadA = await createE2ELead(adminToken, {
      project: 'E2E Location Project A',
    });
    phones.push(leadA.phone);
    await apiJson('PUT', `/leads/${leadA.id}`, { token: adminToken, body: { location: 'E2E Chennai' } });

    const leadB = await createE2ELead(adminToken, {
      project: 'E2E Location Project B',
    });
    phones.push(leadB.phone);
    await apiJson('PUT', `/leads/${leadB.id}`, { token: adminToken, body: { location: 'E2E Chennai Suburbs' } });

    await authenticatePage(page);
    await page.goto('/virtual-customer');
    await expect(page.getByTestId('virtual-customer-title')).toBeVisible();
    const locationFilter = page.getByTestId('location-filter');
    await expect(locationFilter).toBeVisible();
    await expect(locationFilter).toContainText('Location interested');

    await page.goto(`/virtual-customer?locations=${encodeURIComponent('E2E Chennai')}`);
    await expect(page.getByTestId(`lead-phone-${leadA.id}`)).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId(`lead-phone-${leadB.id}`)).toHaveCount(0);
  });

  test('#53/#54 Site visit completion is logged and reported by project', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {
      assigned_user_id: repMe.id,
      assigned_to: 'E2E Rep',
      assigned_to_name: 'E2E Rep',
      project: 'E2E Visit Report Project',
    });
    phones.push(lead.phone);

    // First visit completion.
    await apiJson('PUT', `/leads/${lead.id}`, {
      token: adminToken,
      body: { lead_status: 'Visit Completed' },
    });
    // Move away, then complete again — must still log (not first-stamp-only).
    await apiJson('PUT', `/leads/${lead.id}`, {
      token: adminToken,
      body: { lead_status: 'Follow-up Scheduled' },
    });
    await apiJson('PUT', `/leads/${lead.id}`, {
      token: adminToken,
      body: { lead_status: 'Visit Completed' },
    });

    const report = await apiJson(
      'GET',
      `/analytics/site-visits?preset=month&sales_owner_id=${repMe.id}`,
      { token: adminToken }
    );
    const projectRow = (report.by_project || []).find((r) => r.project === 'E2E Visit Report Project');
    expect(projectRow).toBeTruthy();
    expect(projectRow.count).toBeGreaterThanOrEqual(2);

    await authenticatePage(page);
    await page.goto('/site-visits');
    await expect(page.getByTestId('site-visits-page')).toBeVisible();
    await expect(page.getByTestId('site-visits-total')).toBeVisible();
  });
});
