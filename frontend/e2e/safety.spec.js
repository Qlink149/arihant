const { test, expect } = require('@playwright/test');
const {
  assertSafeE2EConfig,
  ALLOWED_DB,
  BLOCKED_HOSTS,
} = require('./helpers/safety.cjs');

test.describe('E2E safety rails', () => {
  test('assertSafeE2EConfig accepts allowlisted local config', () => {
    expect(() =>
      assertSafeE2EConfig({
        environment: 'e2e',
        dbName: 'arihant_crm_e2e',
        apiBase: 'http://127.0.0.1:8000',
        baseURL: 'http://127.0.0.1:3000',
      })
    ).not.toThrow();
    expect(ALLOWED_DB.has('arihant_crm_e2e')).toBeTruthy();
  });

  test('assertSafeE2EConfig refuses production DB name', () => {
    expect(() =>
      assertSafeE2EConfig({
        environment: 'e2e',
        dbName: 'arihant_crm',
        apiBase: 'http://127.0.0.1:8000',
        baseURL: 'http://127.0.0.1:3000',
      })
    ).toThrow(/DB_NAME/);
  });

  test('assertSafeE2EConfig refuses live API host', () => {
    expect(() =>
      assertSafeE2EConfig({
        environment: 'e2e',
        dbName: 'arihant_crm_e2e',
        apiBase: `https://${BLOCKED_HOSTS[0]}`,
        baseURL: 'http://127.0.0.1:3000',
      })
    ).toThrow(/live host/);
  });
});
