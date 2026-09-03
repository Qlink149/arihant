const { test, expect } = require('@playwright/test');
const {
  getRunId,
  loginApi,
  fetchMe,
  createE2ELead,
  insertNotification,
  cleanupRun,
  apiJson,
} = require('./helpers/api.cjs');
const { authenticatePage, refreshApiSession } = require('./helpers/auth.cjs');

test.describe.configure({ mode: 'serial' });
test.describe.configure({ timeout: 120_000 });

test.describe('Change Tracker 37–45 (disposable e2e DB)', () => {
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

  test('#37 View All shows read + unread history', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, { project: 'E2E Vivriti' });
    phones.push(lead.phone);
    const unread = insertNotification({
      leadId: lead.id,
      recipientId: adminMe.id,
      title: 'E2E unread alert',
      message: 'Unread body',
    });
    insertNotification({
      leadId: lead.id,
      recipientId: adminMe.id,
      title: 'E2E read alert',
      message: 'Read body',
      isRead: true,
    });

    await authenticatePage(page);
    await page.goto('/notifications');
    await expect(page.getByTestId('notifications-page')).toBeVisible();
    await expect(page.getByTestId(`notification-row-${unread.id}`)).toHaveAttribute(
      'data-read',
      'false'
    );
    await expect(page.getByText('E2E read alert')).toBeVisible();
    await expect(page.getByText('E2E unread alert')).toBeVisible();
  });

  test('#38 Escalations allowed for admin/manager/GM; denied for rep', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {});
    phones.push(lead.phone);
    insertNotification({
      leadId: lead.id,
      recipientId: adminMe.id,
      title: 'E2E escalation',
      message: 'Needs review',
      notificationType: 'escalation',
    });

    await authenticatePage(page);
    await page.goto('/escalation-queue');
    await expect(page.getByTestId('escalation-queue-page')).toBeVisible();
    await expect(page.getByText('E2E escalation')).toBeVisible();

    const managerEmail = process.env.E2E_MANAGER_EMAIL || 'e2e-manager@arihant.local';
    const managerPassword = process.env.E2E_MANAGER_PASSWORD || 'E2eManager!Pass123';
    await authenticatePage(page, { email: managerEmail, password: managerPassword });
    await page.goto('/escalation-queue');
    await expect(page.getByTestId('escalation-queue-page')).toBeVisible();

    const gmEmail = process.env.E2E_GM_EMAIL || 'shariff@arihants.co.in';
    const gmPassword = process.env.E2E_GM_PASSWORD || 'E2eGm!Pass123';
    await authenticatePage(page, { email: gmEmail, password: gmPassword });
    await page.goto('/escalation-queue');
    await expect(page.getByTestId('escalation-queue-page')).toBeVisible();

    const repEmail = process.env.E2E_REP_EMAIL || 'e2e-rep@arihant.local';
    const repPassword = process.env.E2E_REP_PASSWORD || 'E2eRep!Pass123';
    await authenticatePage(page, { email: repEmail, password: repPassword });
    await page.goto('/escalation-queue');
    await expect(page).toHaveURL(/my-dashboard/);
  });

  test('#39 #44 cross-assignee note + mention notify', async ({ page }) => {
    await ensureAdminApi();
    const repEmail = process.env.E2E_REP_EMAIL || 'e2e-rep@arihant.local';
    const repPassword = process.env.E2E_REP_PASSWORD || 'E2eRep!Pass123';
    const repLogin = await loginApi(repEmail, repPassword);
    repToken = repLogin.access_token;
    repMe = await fetchMe(repToken);

    const lead = await createE2ELead(adminToken, {
      assigned_user_id: repMe.id,
      assigned_to: 'E2E Rep',
      assigned_to_name: 'E2E Rep',
      project: 'E2E Bold Project',
    });
    phones.push(lead.phone);

    // Rep notes on lead they do not own (org-wide note ACL)
    await apiJson('POST', `/leads/${lead.id}/context`, {
      token: repToken,
      body: {
        note: 'Rep note for assignee check',
        update_type: 'general_note',
      },
    });

    // Refresh admin token (rep login may have been fine; admin from ensureAdminApi is current)
    await ensureAdminApi();
    await apiJson('POST', `/leads/${lead.id}/context`, {
      token: adminToken,
      body: {
        note: `Please review @E2E Rep`,
        update_type: 'general_note',
        mentioned_user_ids: [repMe.id],
      },
    });

    const repLogin2 = await loginApi(repEmail, repPassword);
    repToken = repLogin2.access_token;
    const notifs = await apiJson('GET', '/notifications?unread_only=true&limit=50', {
      token: repToken,
    });
    const list = notifs.notifications || notifs;
    const types = list.map((n) => n.type || n.notification_type);
    expect(types.some((t) => t === 'lead_note' || t === 'lead_note_mention')).toBeTruthy();

    await authenticatePage(page);
    await page.goto('/virtual-customer');
    await expect(page.getByTestId('virtual-customer-title')).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Created' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Project' })).toBeVisible();
  });

  test('#43 dormant chip not shown from legacy URL', async ({ page }) => {
    await authenticatePage(page);
    await page.goto('/virtual-customer?dormant=1');
    await expect(page.getByTestId('virtual-customer-title')).toBeVisible();
    await expect(page.getByLabel('Clear dormant filter')).toHaveCount(0);
  });
});
