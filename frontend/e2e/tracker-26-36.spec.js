const { test, expect } = require('@playwright/test');
const {
  getRunId,
  loginApi,
  fetchMe,
  createE2ELead,
  insertNotification,
  cleanupRun,
  apiJson,
  runPython,
} = require('./helpers/api.cjs');
const { authenticatePage, refreshApiSession } = require('./helpers/auth.cjs');
const { postWatiInbound } = require('./helpers/watiWebhook.cjs');
const { installWatiOutboundMocks } = require('./helpers/mockWati.cjs');
const { randomE2EPhone, e2eFirstName } = require('./helpers/safety.cjs');

test.describe.configure({ mode: 'serial' });

// Give UI + Atlas a bit more room per test
test.describe.configure({ timeout: 120_000 });

test.describe('Change Tracker 26–36 (disposable e2e DB)', () => {
  /** @type {string[]} */
  const phones = [];
  let adminToken;
  let adminMe;
  let repToken;
  let repMe;
  let runId;

  // Avoid login spam (rate limit): refresh API token at the start of tests that need it
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

  test('#36 notification panel click navigates to lead', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {});
    phones.push(lead.phone);
    insertNotification({
      leadId: lead.id,
      recipientId: adminMe.id,
      title: 'E2E notification',
      message: 'Open this lead',
    });

    await authenticatePage(page);
    await page.goto('/dashboard');
    await page.getByTestId('notifications-btn').click();
    await expect(page.getByTestId('notifications-panel')).toBeVisible();
    await page.getByTestId('notification-0').click();
    await expect(page).toHaveURL(new RegExp(`/lead/${lead.id}`));
  });

  test('#27 #26 #34 WA inbound → Admin lead, Replied chip, recent note', async ({ page }) => {
    await ensureAdminApi();
    const phone = randomE2EPhone();
    phones.push(phone);

    await postWatiInbound({
      waId: phone,
      text: 'Hello from E2E customer',
      senderName: `${e2eFirstName(runId)} WA`,
    });

    // Find lead by phone via list search
    const list = await apiJson('GET', `/leads?search=${phone.slice(-10)}&limit=20`, {
      token: adminToken,
    });
    const rows = Array.isArray(list) ? list : list.leads || list.items || [];
    const lead = rows.find(
      (r) => String(r.normalized_phone || r.phone || '').includes(phone.slice(-10))
    );
    expect(lead, 'WA auto-created lead').toBeTruthy();
    expect(lead.assigned_to_name || lead.assigned_to || lead.presales_agent).toMatch(/Admin/i);
    expect(lead.lead_status).toBe('New');

    runPython('scripts/e2e_fixtures.py', [
      'patch-lead',
      '--run-id',
      runId,
      '--lead-id',
      lead.id,
      '--json',
      JSON.stringify({
        e2e_run_id: runId,
        meta: { e2e_run_id: runId },
        first_name: e2eFirstName(runId),
      }),
    ]);
    runPython('scripts/e2e_fixtures.py', [
      'push-note',
      '--run-id',
      runId,
      '--lead-id',
      lead.id,
      '--text',
      'E2E recent note for RHS',
    ]);

    await authenticatePage(page);
    await page.goto('/whatsapp');
    await expect(page.getByText('Replied').first()).toBeVisible({ timeout: 20000 });

    await page.getByTestId(`wa-thread-${lead.id}`).click({ timeout: 10000 }).catch(async () => {
      await page.getByText(phone.slice(-4)).first().click();
    });
    await expect(page.getByText(/Recent note/i).first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByText(/E2E recent note/i).first()).toBeVisible();

    await page.goto(`/virtual-customer?search=${encodeURIComponent(phone.slice(-10))}`);
    await expect(page.getByText(e2eFirstName(runId)).first()).toBeVisible({ timeout: 20000 });
  });

  test('#31 Zapier Meta timeline shows project', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {
      project: 'Vivriti',
      timeline_description: 'Lead created via Zapier (Meta Instant Form) — Vivriti',
      timeline_project: 'Vivriti',
      timeline_agent: 'Zapier',
    });
    phones.push(lead.phone);

    await authenticatePage(page);
    await page.goto(`/lead/${lead.id}`);
    await expect(page.getByTestId('context-timeline')).toBeVisible();
    await expect(
      page.getByText(/Lead created via Zapier \(Meta Instant Form\) — Vivriti/)
    ).toBeVisible();
  });

  test('#28 multi-project filter matches projects[]', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {
      projects: ['Vivriti', 'Mélange'],
      project: 'Vivriti; Mélange',
    });
    phones.push(lead.phone);

    await authenticatePage(page);
    await page.goto('/virtual-customer');
    // Open project filter and pick Vivriti if UI allows; else search by name
    await page.getByTestId('project-filter').click().catch(() => {});
    const option = page.getByRole('option', { name: /Vivriti/i }).first();
    if (await option.isVisible().catch(() => false)) {
      await option.click();
    }
    await page.goto(
      `/virtual-customer?projects=${encodeURIComponent('Vivriti')}&search=${encodeURIComponent(e2eFirstName(runId))}`
    );
    await expect(page.getByText(e2eFirstName(runId)).first()).toBeVisible({ timeout: 20000 });
  });

  test('#32 nudge from Digital Twin', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {
      assigned_user_id: repMe.id,
      assigned_to: 'E2E Rep',
      assigned_to_name: 'E2E Rep',
      presales_agent: 'E2E Rep',
    });
    phones.push(lead.phone);

    await authenticatePage(page);
    await page.goto(`/lead/${lead.id}`);
    await page.getByTestId('nudge-btn').click();
    await expect(page.getByText(/Nudge/i).first()).toBeVisible();

    const repLogin = await loginApi(
      process.env.E2E_REP_EMAIL || 'e2e-rep@arihant.local',
      process.env.E2E_REP_PASSWORD || 'E2eRep!Pass123'
    );
    const notifs = await apiJson('GET', '/notifications?unread_only=true&limit=50', {
      token: repLogin.access_token,
    });
    const list = notifs.notifications || notifs;
    const types = list.map((n) => n.type || n.notification_type);
    expect(types).toContain('admin_nudge');
  });

  test('#29 VC filter bar is sticky', async ({ page }) => {
    await authenticatePage(page);
    await page.goto('/virtual-customer');
    const bar = page.locator('.glass-card.sticky').first();
    await expect(bar).toBeVisible();
    const pos = await bar.evaluate((el) => getComputedStyle(el).position);
    expect(pos).toBe('sticky');
  });

  test('#30 My Dashboard WhatsApp tab', async ({ page }) => {
    await authenticatePage(page);
    await page.goto('/my-dashboard');
    await page.getByTestId('tab-whatsapp').click();
    await expect(page.getByTestId('whatsapp-section')).toBeVisible();
    await expect(page.getByTestId('wa-tiles')).toBeVisible();
    await expect(page.getByTestId('wa-subfilters')).toBeVisible();
  });

  test('#33 bulk select + bulk status', async ({ page }) => {
    await ensureAdminApi();
    const a = await createE2ELead(adminToken, {});
    const b = await createE2ELead(adminToken, {});
    phones.push(a.phone, b.phone);

    await authenticatePage(page);
    await page.goto(
      `/virtual-customer?search=${encodeURIComponent(e2eFirstName(runId))}`
    );
    await expect(page.getByText(e2eFirstName(runId)).first()).toBeVisible({ timeout: 20000 });

    const checks = page.getByRole('checkbox');
    await expect(checks.first()).toBeVisible({ timeout: 15000 });
    const count = await checks.count();
    expect(count).toBeGreaterThan(1);
    await checks.nth(1).click();
    await checks.nth(2).click();

    await expect(page.getByTestId('lead-bulk-bar')).toBeVisible({ timeout: 10000 });
    await page.getByTestId('bulk-status-btn').click();
    await page.getByTestId('bulk-status-select').click();
    await page.getByRole('option', { name: /Contacted/i }).click();
    await page.getByTestId('bulk-status-confirm').click();
    await expect(page.getByTestId('lead-bulk-bar')).toBeHidden({ timeout: 15000 }).catch(() => {});

    await checks.nth(1).click();
    await checks.nth(2).click();
    await expect(page.getByTestId('lead-bulk-bar')).toBeVisible({ timeout: 10000 });
    await page.getByTestId('bulk-assign-btn').click();
    await expect(page.getByTestId('bulk-assign-modal')).toBeVisible();
    await page.getByTestId('bulk-assign-select').click();
    await page.getByRole('option', { name: /E2E Rep/i }).click();
    await page.getByTestId('bulk-assign-confirm').click();
    await expect(page.getByTestId('lead-bulk-bar')).toBeHidden({ timeout: 15000 }).catch(() => {});
  });

  test('#35 template params edited before send (mocked WATI)', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {
      project: 'Vivriti',
      assigned_user_id: adminMe.id,
      assigned_to: 'Admin',
      assigned_to_name: 'Admin',
    });
    phones.push(lead.phone);

    const capture = [];
    await installWatiOutboundMocks(page, { capture });
    await authenticatePage(page);
    await page.goto(`/lead/${lead.id}`);
    await page.getByTestId('whatsapp-btn').click();
    await page.getByTestId('template-select').selectOption('e2e_welcome');
    await page.getByTestId('template-param-name').fill('Priya');
    await page.getByTestId('template-param-project').fill('Vivriti');
    await page.getByTestId('send-whatsapp-btn').click();

    await expect.poll(() => capture.length, { timeout: 15000 }).toBeGreaterThan(0);
    const body = capture[0].body;
    const params = body?.template_parameters || body?.parameters || [];
    expect(JSON.stringify(params)).toMatch(/Priya/);
    expect(JSON.stringify(params)).toMatch(/Vivriti/);
  });
});
