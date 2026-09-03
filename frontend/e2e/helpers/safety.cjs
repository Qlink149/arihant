/**
 * Fail closed before any E2E write. Mirrors backend/scripts/e2e_cleanup.py rails.
 */

const ALLOWED_DB = new Set(['arihant_crm_e2e', 'arihant_crm_test']);
const ALLOWED_ENV = new Set(['development', 'test', 'e2e']);
const BLOCKED_HOSTS = [
  'arihant-api.claraai.tech',
  'crm-sales-next.preview.emergentagent.com',
];

function assertSafeE2EConfig(cfg = {}) {
  const environment = String(cfg.environment || process.env.E2E_ENVIRONMENT || '').toLowerCase();
  const dbName = String(cfg.dbName || process.env.E2E_DB_NAME || '').trim();
  const apiBase = String(cfg.apiBase || process.env.E2E_API_URL || '').trim().toLowerCase();
  const baseURL = String(cfg.baseURL || process.env.E2E_BASE_URL || '').trim().toLowerCase();

  if (!ALLOWED_ENV.has(environment)) {
    throw new Error(
      `E2E refuse: E2E_ENVIRONMENT=${environment || '(empty)'} must be development|test|e2e`
    );
  }
  if (!ALLOWED_DB.has(dbName)) {
    throw new Error(
      `E2E refuse: E2E_DB_NAME=${dbName || '(empty)'} must be arihant_crm_e2e (or arihant_crm_test)`
    );
  }
  for (const host of BLOCKED_HOSTS) {
    if (apiBase.includes(host) || baseURL.includes(host)) {
      throw new Error(`E2E refuse: URL points at live host ${host}`);
    }
  }
  if (apiBase && !/localhost|127\.0\.0\.1/.test(apiBase)) {
    throw new Error(`E2E refuse: E2E_API_URL must be localhost/127.0.0.1, got ${apiBase}`);
  }
  return { environment, dbName, apiBase, baseURL };
}

function randomE2EPhone() {
  const n = Math.floor(1000000000 + Math.random() * 8999999999);
  const ten = String(n).slice(0, 10);
  if (ten === '9116914178') return randomE2EPhone();
  return `91${ten}`;
}

function e2eFirstName(runId) {
  return `E2E_${String(runId).slice(0, 8)}`;
}

module.exports = {
  assertSafeE2EConfig,
  randomE2EPhone,
  e2eFirstName,
  ALLOWED_DB,
  ALLOWED_ENV,
  BLOCKED_HOSTS,
};
