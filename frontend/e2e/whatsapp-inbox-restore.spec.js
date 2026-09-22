/**
 * WhatsApp Team Inbox — scroll/selection restore after lead profile navigation.
 * Requires e2e stack (see docs/AI_TESTING_AND_PLANNING.md).
 */
const { test, expect } = require('@playwright/test');
const { getRunId, createE2ELead, cleanupRun } = require('./helpers/api.cjs');
const { authenticatePage, refreshApiSession } = require('./helpers/auth.cjs');
const { postWatiInbound } = require('./helpers/watiWebhook.cjs');
const { e2eFirstName } = require('./helpers/safety.cjs');

test.describe.configure({ timeout: 120_000 });

test.describe('WhatsApp inbox restore', () => {
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
      await cleanupRun(runId, phones);
    } catch {
      /* ignore */
    }
  });

  test('returns to same thread after Open Lead Overview and back', async ({ page }) => {
    const phone = `9198${String(Date.now()).slice(-8)}`;
    phones.push(phone);

    const lead = await createE2ELead(adminToken, {
      phone,
      first_name: e2eFirstName(runId),
      last_name: 'Restore',
    });

    await postWatiInbound({
      waId: phone,
      text: 'E2E restore scroll test inbound',
      senderName: e2eFirstName(runId),
    });

    await authenticatePage(page);
    await page.goto('/whatsapp');
    await expect(page.getByText('WhatsApp').first()).toBeVisible({ timeout: 20000 });

    const thread = page.getByTestId(`wa-thread-${lead.id}`);
    await thread.click({ timeout: 15000 }).catch(async () => {
      await page.getByText(phone.slice(-4)).first().click();
    });
    await expect(page.getByRole('button', { name: /Open Lead Overview/i })).toBeVisible({
      timeout: 15000,
    });

    await page.getByRole('button', { name: /Open Lead Overview/i }).click();
    await expect(page).toHaveURL(new RegExp(`/lead/${lead.id}#lead-overview`), {
      timeout: 15000,
    });

    await page.getByTestId('back-btn').click();
    await expect(page).toHaveURL(/\/whatsapp/, { timeout: 15000 });

    await expect(thread).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole('button', { name: /Open Lead Overview/i })).toBeVisible({
      timeout: 10000,
    });
  });
});
