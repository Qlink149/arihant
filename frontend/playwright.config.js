const { defineConfig, devices } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

// Load backend/.env.e2e and OVERRIDE ambient prod shell env (never use backend/.env).
const envE2e = path.resolve(__dirname, '../backend/.env.e2e');
if (!fs.existsSync(envE2e)) {
  throw new Error(
    `Missing ${envE2e} — copy backend/env.e2e.example and set MONGO_URL for the test cluster`
  );
}
const text = fs.readFileSync(envE2e, 'utf8');
for (const line of text.split(/\r?\n/)) {
  const m = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
  if (!m) continue;
  const key = m[1];
  let val = m[2];
  if (
    (val.startsWith('"') && val.endsWith('"'))
    || (val.startsWith("'") && val.endsWith("'"))
  ) {
    val = val.slice(1, -1);
  }
  process.env[key] = val;
}

process.env.E2E_ENV_FILE = envE2e;
process.env.E2E_ENVIRONMENT = process.env.ENVIRONMENT || 'e2e';
process.env.E2E_DB_NAME = process.env.DB_NAME || 'arihant_crm_e2e';
process.env.E2E_API_URL = process.env.E2E_API_URL || 'http://127.0.0.1:8000';
process.env.E2E_BASE_URL = process.env.E2E_BASE_URL || 'http://127.0.0.1:3000';
process.env.E2E_ADMIN_EMAIL =
  process.env.E2E_ADMIN_EMAIL || 'e2e-admin@arihant.local';
process.env.E2E_ADMIN_PASSWORD =
  process.env.E2E_ADMIN_PASSWORD || 'E2eAdmin!Pass123';
process.env.E2E_REP_EMAIL = process.env.E2E_REP_EMAIL || 'e2e-rep@arihant.local';
process.env.E2E_REP_PASSWORD = process.env.E2E_REP_PASSWORD || 'E2eRep!Pass123';
process.env.E2E_MANAGER_EMAIL =
  process.env.E2E_MANAGER_EMAIL || 'e2e-manager@arihant.local';
process.env.E2E_MANAGER_PASSWORD =
  process.env.E2E_MANAGER_PASSWORD || 'E2eManager!Pass123';
process.env.E2E_GM_EMAIL = process.env.E2E_GM_EMAIL || 'shariff@arihants.co.in';
process.env.E2E_GM_PASSWORD = process.env.E2E_GM_PASSWORD || 'E2eGm!Pass123';

const { assertSafeE2EConfig } = require('./e2e/helpers/safety.cjs');
assertSafeE2EConfig({
  environment: process.env.E2E_ENVIRONMENT,
  dbName: process.env.E2E_DB_NAME,
  apiBase: process.env.E2E_API_URL,
  baseURL: process.env.E2E_BASE_URL,
});

module.exports = defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
