const { spawnSync } = require('child_process');
const path = require('path');
const crypto = require('crypto');
const { assertSafeE2EConfig, e2eFirstName, randomE2EPhone } = require('./safety.cjs');

const BACKEND_ROOT = path.resolve(__dirname, '../../../backend');

function apiBase() {
  return (process.env.E2E_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
}

function getRunId() {
  if (!process.env.E2E_RUN_ID) {
    process.env.E2E_RUN_ID = crypto.randomUUID();
  }
  return process.env.E2E_RUN_ID;
}

function runPython(scriptRel, args = []) {
  assertSafeE2EConfig({
    environment: process.env.E2E_ENVIRONMENT,
    dbName: process.env.E2E_DB_NAME,
    apiBase: process.env.E2E_API_URL,
    baseURL: process.env.E2E_BASE_URL,
  });
  const script = path.join(BACKEND_ROOT, scriptRel);
  const envFile = process.env.E2E_ENV_FILE || path.join(BACKEND_ROOT, '.env.e2e');
  const result = spawnSync('python', [script, ...args], {
    cwd: BACKEND_ROOT,
    env: { ...process.env, E2E_ENV_FILE: envFile, PYTHONPATH: BACKEND_ROOT },
    encoding: 'utf8',
  });
  if (result.status !== 0) {
    throw new Error(
      `python ${scriptRel} failed (${result.status}):\n${result.stdout}\n${result.stderr}`
    );
  }
  return (result.stdout || '').trim();
}

async function loginApi(email, password, { retries = 5 } = {}) {
  assertSafeE2EConfig({
    environment: process.env.E2E_ENVIRONMENT,
    dbName: process.env.E2E_DB_NAME,
    apiBase: process.env.E2E_API_URL,
    baseURL: process.env.E2E_BASE_URL,
  });
  let lastErr;
  for (let i = 0; i < retries; i += 1) {
    const body = new URLSearchParams({ username: email, password });
    const res = await fetch(`${apiBase()}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
    if (res.status === 429) {
      lastErr = new Error(`login failed 429: ${await res.text()}`);
      await new Promise((r) => setTimeout(r, 7000 * (i + 1)));
      continue;
    }
    if (!res.ok) {
      throw new Error(`login failed ${res.status}: ${await res.text()}`);
    }
    return res.json();
  }
  throw lastErr || new Error('login failed after retries');
}

async function apiJson(method, pathName, { token, body } = {}) {
  const res = await fetch(`${apiBase()}/api${pathName}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body != null ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    throw new Error(`${method} ${pathName} → ${res.status}: ${text}`);
  }
  return data;
}

async function createE2ELead(token, overrides = {}) {
  const runId = getRunId();
  const phone = overrides.phone || randomE2EPhone();
  const payload = {
    first_name: e2eFirstName(runId),
    last_name: 'Lead',
    phone,
    email: `e2e_${runId.slice(0, 8)}_${Date.now()}@example.com`,
    lead_status: 'New',
    lead_source: 'E2E',
    project: overrides.project || '',
    projects: overrides.projects,
  };
  if (!payload.projects) delete payload.projects;
  if (!payload.project) delete payload.project;

  const lead = await apiJson('POST', '/leads', { token, body: payload });
  const leadId = lead.id || lead.lead_id;
  const patch = {
    e2e_run_id: runId,
    meta: { e2e_run_id: runId },
  };
  if (overrides.projects) patch.projects = overrides.projects;
  if (overrides.project != null) patch.project = overrides.project;
  if (overrides.assigned_user_id) {
    patch.assigned_user_id = overrides.assigned_user_id;
    patch.assigned_to = overrides.assigned_to || 'E2E Rep';
    patch.assigned_to_name = overrides.assigned_to_name || 'E2E Rep';
    patch.presales_agent = overrides.presales_agent || 'E2E Rep';
  }
  if (overrides.whatsapp_replied != null) patch.whatsapp_replied = overrides.whatsapp_replied;

  runPython('scripts/e2e_fixtures.py', [
    'patch-lead',
    '--run-id',
    runId,
    '--lead-id',
    leadId,
    '--json',
    JSON.stringify(patch),
  ]);
  if (overrides.context_note) {
    runPython('scripts/e2e_fixtures.py', [
      'push-note',
      '--run-id',
      runId,
      '--lead-id',
      leadId,
      '--text',
      overrides.context_note,
    ]);
  }
  if (overrides.timeline_description) {
    runPython('scripts/e2e_fixtures.py', [
      'push-timeline',
      '--run-id',
      runId,
      '--lead-id',
      leadId,
      '--type',
      overrides.timeline_type || 'created',
      '--description',
      overrides.timeline_description,
      '--agent',
      overrides.timeline_agent || 'Zapier',
      ...(overrides.timeline_project
        ? ['--project-name', overrides.timeline_project]
        : []),
    ]);
  }
  return { ...lead, id: leadId, phone, e2e_run_id: runId };
}

function insertNotification({
  leadId,
  recipientId,
  title,
  message,
  notificationType,
  isRead = false,
}) {
  const runId = getRunId();
  const args = [
    'insert-notification',
    '--run-id',
    runId,
    '--lead-id',
    leadId,
    '--recipient-id',
    recipientId,
    '--title',
    title || 'E2E notification',
    '--message',
    message || 'Open lead',
  ];
  if (notificationType) {
    args.push('--notification-type', notificationType);
  }
  if (isRead) {
    args.push('--is-read');
  }
  const out = runPython('scripts/e2e_fixtures.py', args);
  return JSON.parse(out.split('\n').filter(Boolean).pop());
}

function cleanupRun(phones = []) {
  const runId = getRunId();
  const args = ['--run-id', runId];
  for (const p of phones) args.push('--phone', p);
  return runPython('scripts/e2e_cleanup.py', args);
}

async function fetchMe(token) {
  return apiJson('GET', '/auth/me', { token });
}

module.exports = {
  getRunId,
  runPython,
  loginApi,
  apiJson,
  createE2ELead,
  insertNotification,
  cleanupRun,
  fetchMe,
};
