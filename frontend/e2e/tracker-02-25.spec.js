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
const { postWatiInbound } = require('./helpers/watiWebhook.cjs');
const { installWatiOutboundMocks } = require('./helpers/mockWati.cjs');
const { e2eFirstName } = require('./helpers/safety.cjs');

test.describe.configure({ mode: 'serial' });
test.describe.configure({ timeout: 120_000 });

function istYmd(offsetDays = 0) {
  const utc = Date.now() + offsetDays * 86400000;
  const ist = new Date(utc + 5.5 * 3600000);
  return ist.toISOString().slice(0, 10);
}

test.describe('Change Tracker 02–25 (disposable e2e DB)', () => {
  /** @type {string[]} */
  const phones = [];
  /** @type {string[]} */
  const filterViewIds = [];
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

  async function ensureRepApi() {
    const repEmail = process.env.E2E_REP_EMAIL || 'e2e-rep@arihant.local';
    const repPassword = process.env.E2E_REP_PASSWORD || 'E2eRep!Pass123';
    const repLogin = await loginApi(repEmail, repPassword);
    repToken = repLogin.access_token;
    repMe = await fetchMe(repToken);
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
    for (const id of filterViewIds) {
      try {
        await ensureAdminApi();
        await apiJson('DELETE', `/leads/filter-views/${id}`, { token: adminToken });
      } catch (err) {
        console.warn('filter-view cleanup:', err.message);
      }
    }
    try {
      cleanupRun(phones);
    } catch (err) {
      console.warn('cleanupRun warning:', err.message);
    }
  });

  test('#3 WhatsApp is in the left nav', async ({ page }) => {
    await authenticatePage(page);
    await expect(page.getByRole('link', { name: 'WhatsApp' })).toBeVisible();
    await page.getByRole('link', { name: 'WhatsApp' }).click();
    await expect(page).toHaveURL(/\/whatsapp/);
  });

  test('#2 Edit note persists; no delete control', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {});
    phones.push(lead.phone);

    await apiJson('POST', `/leads/${lead.id}/context`, {
      token: adminToken,
      body: { note: 'Original E2E note', update_type: 'general_note' },
    });

    const detail = await apiJson('GET', `/leads/${lead.id}`, { token: adminToken });
    const updates = detail.context_updates || [];
    const row = updates.find((u) => String(u.description || u.note || '').includes('Original E2E note'));
    expect(row).toBeTruthy();
    const idx = typeof row._mongo_index === 'number' ? row._mongo_index : updates.indexOf(row);
    await apiJson('PATCH', `/leads/${lead.id}/context/${idx}`, {
      token: adminToken,
      body: {
        note: 'Edited E2E note',
        timestamp: row.timestamp || undefined,
        entry_type: row.type || row.update_type || 'general_note',
        previous_description: 'Original E2E note',
      },
    });

    const afterDetail = await apiJson('GET', `/leads/${lead.id}`, { token: adminToken });
    const notes = afterDetail.context_updates || [];
    expect(JSON.stringify(notes)).toMatch(/Edited E2E note/);

    await authenticatePage(page);
    await page.goto(`/lead/${lead.id}`);
    await expect(page.getByTestId('context-timeline')).toBeVisible();
    await expect(page.getByText('Edited E2E note')).toBeVisible();
    await expect(page.getByTitle('Edit note')).toBeVisible();
    await expect(page.getByTitle(/delete note/i)).toHaveCount(0);
  });

  test('#4 inbound WhatsApp reply notifies assignee', async () => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {
      assigned_user_id: repMe.id,
      assigned_to: 'E2E Rep',
      assigned_to_name: 'E2E Rep',
    });
    phones.push(lead.phone);

    await postWatiInbound({
      waId: lead.phone.replace(/\D/g, ''),
      text: 'E2E reply to auto message',
    });

    await ensureRepApi();
    const notifs = await apiJson('GET', '/notifications?unread_only=true&limit=50', {
      token: repToken,
    });
    const list = notifs.notifications || notifs;
    const types = list.map((n) => n.type || n.notification_type);
    expect(types).toContain('whatsapp_reply');
  });

  test('#5 RNR status does not auto-reassign ownership', async () => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {
      assigned_user_id: repMe.id,
      assigned_to: 'E2E Rep',
      assigned_to_name: 'E2E Rep',
    });
    phones.push(lead.phone);
    await apiJson('PUT', `/leads/${lead.id}`, {
      token: adminToken,
      body: { lead_status: 'RNR', is_rnr: true },
    });
    const after = await apiJson('GET', `/leads/${lead.id}`, { token: adminToken });
    expect(after.assigned_user_id).toBe(repMe.id);
  });

  test('#6 note clears Missed Follow-ups metric membership', async () => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {
      assigned_user_id: repMe.id,
      assigned_to: 'E2E Rep',
      assigned_to_name: 'E2E Rep',
    });
    phones.push(lead.phone);
    runPython('scripts/e2e_fixtures.py', [
      'patch-lead',
      '--run-id',
      runId,
      '--lead-id',
      lead.id,
      '--json',
      JSON.stringify({ next_action_date: istYmd(-2) }),
    ]);

    await ensureRepApi();
    const before = await apiJson('GET', `/leads?metric=missed_follow_up&mine=1&limit=200`, {
      token: repToken,
    });
    const beforeList = Array.isArray(before) ? before : before.leads || [];
    expect(beforeList.some((l) => (l.id || l.lead_id) === lead.id)).toBeTruthy();

    await apiJson('POST', `/leads/${lead.id}/context`, {
      token: adminToken,
      body: { note: 'Called; rescheduled', update_type: 'call_note' },
    });

    await ensureRepApi();
    const after = await apiJson('GET', `/leads?metric=missed_follow_up&mine=1&limit=200`, {
      token: repToken,
    });
    const afterList = Array.isArray(after) ? after : after.leads || [];
    expect(afterList.some((l) => (l.id || l.lead_id) === lead.id)).toBeFalsy();
  });

  test('#7 Back to Explorer stays visible while scrolling', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {});
    phones.push(lead.phone);
    await authenticatePage(page);
    await page.goto(`/lead/${lead.id}`);
    const back = page.getByTestId('back-btn');
    await expect(back).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(back).toBeVisible();
    const pos = await back.evaluate((el) => {
      const sticky = el.closest('[class*="sticky"]');
      return sticky ? getComputedStyle(sticky).position : getComputedStyle(el).position;
    });
    expect(pos).toBe('sticky');
  });

  test('#8 Escalation queue reachable for admin', async ({ page }) => {
    await authenticatePage(page);
    await page.goto('/escalation-queue');
    await expect(page.getByTestId('escalation-queue-page')).toBeVisible();
  });

  test('#9 #10 #18 #19 #40 #41 #42 VC columns: phone, timestamps, project, owner', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, { project: 'E2E Vivriti' });
    phones.push(lead.phone);

    await authenticatePage(page);
    await page.goto(`/virtual-customer?search=${encodeURIComponent(e2eFirstName(runId))}`);
    await expect(page.getByTestId(`lead-phone-${lead.id}`)).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole('columnheader', { name: 'Sales owner' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Created' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Updated' })).toBeVisible();
    await expect(page.getByTestId(`lead-created-${lead.id}`)).toContainText(/\d{1,2}:\d{2}/);
    await expect(page.getByTestId(`lead-updated-${lead.id}`)).toContainText(/\d{1,2}:\d{2}/);
    const phoneWeight = await page.getByTestId(`lead-phone-${lead.id}`).evaluate((el) => getComputedStyle(el).fontWeight);
    expect(Number(phoneWeight) >= 600 || phoneWeight === 'bold').toBeTruthy();
    const projectWeight = await page.getByTestId(`lead-project-${lead.id}`).evaluate((el) => getComputedStyle(el).fontWeight);
    expect(Number(projectWeight) >= 600 || projectWeight === 'bold').toBeTruthy();
  });

  test('#11 filters survive Back to Explorer', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, { project: 'E2E Restore Project' });
    phones.push(lead.phone);
    const agent = encodeURIComponent(e2eFirstName(runId));
    await authenticatePage(page);
    await page.goto(`/virtual-customer?agent=${agent}&projects=${encodeURIComponent('E2E Restore Project')}`);
    await expect(page.getByTestId(`lead-phone-${lead.id}`)).toBeVisible({ timeout: 20000 });
    await page.getByTestId(`lead-phone-${lead.id}`).click();
    await expect(page).toHaveURL(new RegExp(`/lead/${lead.id}`));
    await page.getByTestId('back-btn').click();
    await expect(page).toHaveURL(/virtual-customer/);
    await expect(page).toHaveURL(/agent=/);
    await expect(page).toHaveURL(/projects=/);
  });

  test('#12 #13 org dashboard status chart + time filter drill to VC', async ({ page }) => {
    await authenticatePage(page);
    await page.goto('/dashboard');
    await expect(page.getByTestId('lead-status-chart')).toBeVisible({ timeout: 30000 });
    await expect(page.getByText('Lead Status Distribution')).toBeVisible();
    await page.getByTestId('time-filter-dropdown').click();
    await page.getByTestId('time-filter-30').click();
    await expect(page.getByTestId('time-filter-dropdown')).toContainText(/30/);
    await page.getByTestId('rnr-tile').click();
    await expect(page).toHaveURL(/virtual-customer/);
    await expect(page).toHaveURL(/metric=rnr/);
  });

  test('#15 saved view keeps sales owner + status', async ({ page }) => {
    await ensureAdminApi();
    const mine = await createE2ELead(adminToken, {
      assigned_user_id: adminMe.id,
      assigned_to: adminMe.full_name,
      assigned_to_name: adminMe.full_name,
    });
    const other = await createE2ELead(adminToken, {
      assigned_user_id: repMe.id,
      assigned_to: 'E2E Rep',
      assigned_to_name: 'E2E Rep',
    });
    phones.push(mine.phone, other.phone);
    await apiJson('PUT', `/leads/${other.id}`, { token: adminToken, body: { lead_status: 'Contacted' } });

    const view = await apiJson('POST', '/leads/filter-views', {
      token: adminToken,
      body: {
        name: `E2E ${runId.slice(0, 8)} owner+new`,
        filters: { sales_owners: [adminMe.full_name], statuses: ['New'] },
      },
    });
    if (view.id) filterViewIds.push(view.id);

    const listed = await apiJson(
      'GET',
      `/leads?sales_owners=${encodeURIComponent(adminMe.full_name)}&statuses=New&limit=200`,
      { token: adminToken }
    );
    const rows = Array.isArray(listed) ? listed : listed.leads || [];
    const ids = rows.map((l) => l.id);
    expect(ids).toContain(mine.id);
    expect(ids).not.toContain(other.id);

    await authenticatePage(page);
    await page.goto('/virtual-customer');
    await expect(page.getByTestId('filter-views-bar')).toBeVisible();
  });

  test('#16 VIP tag is editable', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {});
    phones.push(lead.phone);
    await authenticatePage(page);
    await page.goto(`/lead/${lead.id}`);
    await page.getByTestId('toggle-vip').click();
    await ensureAdminApi();
    const after = await apiJson('GET', `/leads/${lead.id}`, { token: adminToken });
    expect(Boolean(after.vip || after.vip_manual)).toBeTruthy();
  });

  test('#22 per-project brochure buttons (mocked WATI)', async ({ page }) => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, { project: 'Vivriti' });
    phones.push(lead.phone);
    const capture = [];
    await installWatiOutboundMocks(page, { capture });
    await authenticatePage(page);
    await page.goto(`/lead/${lead.id}`);
    await page.getByTestId('whatsapp-btn').click();
    await expect(page.getByText(/Send Brochure PDF/i)).toHaveCount(0);
    await page.getByTestId('send-brochure-vivriti').click();
    await expect.poll(() => capture.length, { timeout: 15000 }).toBeGreaterThan(0);
    expect(JSON.stringify(capture[0])).toMatch(/vivriti/i);
  });

  test('#23 RNR queue drill-down uses current RNR only', async () => {
    await ensureAdminApi();
    const rnr = await createE2ELead(adminToken, {});
    const junk = await createE2ELead(adminToken, {});
    phones.push(rnr.phone, junk.phone);
    await apiJson('PUT', `/leads/${rnr.id}`, { token: adminToken, body: { lead_status: 'RNR', is_rnr: true } });
    await apiJson('PUT', `/leads/${junk.id}`, { token: adminToken, body: { lead_status: 'Contacted', is_rnr: false } });
    const listed = await apiJson('GET', '/leads?metric=rnr&limit=200', { token: adminToken });
    const rows = Array.isArray(listed) ? listed : listed.leads || [];
    const ids = rows.map((l) => l.id);
    expect(ids).toContain(rnr.id);
    expect(ids).not.toContain(junk.id);
  });

  test('#24 Unqualified card exists on My Dashboard', async ({ page }) => {
    await authenticatePage(page);
    await page.goto('/my-dashboard');
    await expect(page.getByTestId('lead-overview-unqualified')).toBeVisible({ timeout: 30000 });
  });

  test('#25 task 11:00 IST stores 05:30 UTC', async () => {
    await ensureAdminApi();
    const lead = await createE2ELead(adminToken, {});
    phones.push(lead.phone);
    const dueDate = istYmd(1);
    const created = await apiJson('POST', `/leads/${lead.id}/tasks`, {
      token: adminToken,
      body: {
        description: 'E2E IST task',
        due_date: dueDate,
        due_time: '11:00',
        priority: 'medium',
        assigned_to: adminMe.full_name,
        assigned_user_id: adminMe.id,
      },
    });
    const taskId = created.task_id;
    expect(taskId).toBeTruthy();
    const tasks = await apiJson('GET', `/tasks?lead_id=${lead.id}`, { token: adminToken });
    const list = Array.isArray(tasks) ? tasks : tasks.tasks || [];
    const row = list.find((t) => t.id === taskId) || list[0];
    expect(row).toBeTruthy();
    expect(String(row.due_at_dt || row.due_at || '')).toMatch(/T05:30/);
    expect(String(row.due_time || '')).toMatch(/11:00/);
  });
});
