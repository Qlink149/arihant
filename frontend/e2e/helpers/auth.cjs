const { loginApi, fetchMe } = require('./api.cjs');
const { assertSafeE2EConfig } = require('./safety.cjs');

/**
 * Sign in via the login form so AuthContext hydrates correctly.
 * @param {import('@playwright/test').Page} page
 * @param {{ email?: string, password?: string }} [creds]
 */
async function authenticatePage(page, creds = {}) {
  assertSafeE2EConfig({
    environment: process.env.E2E_ENVIRONMENT,
    dbName: process.env.E2E_DB_NAME,
    apiBase: process.env.E2E_API_URL,
    baseURL: process.env.E2E_BASE_URL,
  });
  const email = creds.email || process.env.E2E_ADMIN_EMAIL || 'e2e-admin@arihant.local';
  const password = creds.password || process.env.E2E_ADMIN_PASSWORD || 'E2eAdmin!Pass123';

  await page.goto('/login');
  await page.evaluate(() => {
    try {
      localStorage.clear();
      sessionStorage.clear();
    } catch (_) {
      /* ignore */
    }
  });
  await page.goto('/login');
  await page.getByTestId('login-email-input').waitFor({ state: 'visible', timeout: 30000 });
  await page.getByTestId('login-email-input').fill(email);
  await page.getByTestId('login-password-input').fill(password);
  await page.getByTestId('login-submit-btn').click();
  await page.getByTestId('notifications-btn').waitFor({ state: 'visible', timeout: 45000 });

  const access = await page.evaluate(() => localStorage.getItem('token'));
  const refresh = await page.evaluate(() => localStorage.getItem('refresh_token'));
  const me = await fetchMe(access);
  return {
    tokens: { access_token: access, refresh_token: refresh },
    me,
  };
}

/** Fresh API token without touching the browser session. */
async function refreshApiSession() {
  const email = process.env.E2E_ADMIN_EMAIL || 'e2e-admin@arihant.local';
  const password = process.env.E2E_ADMIN_PASSWORD || 'E2eAdmin!Pass123';
  const tokens = await loginApi(email, password);
  const me = await fetchMe(tokens.access_token);
  return { tokens, me };
}

module.exports = { authenticatePage, refreshApiSession };
