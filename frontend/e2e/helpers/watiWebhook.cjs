const { assertSafeE2EConfig } = require('./safety.cjs');

async function postWatiInbound({
  waId,
  text = 'E2E inbound hello',
  senderName = 'E2E Customer',
  messageId,
} = {}) {
  assertSafeE2EConfig({
    environment: process.env.E2E_ENVIRONMENT,
    dbName: process.env.E2E_DB_NAME,
    apiBase: process.env.E2E_API_URL,
    baseURL: process.env.E2E_BASE_URL,
  });
  const apiBase = (process.env.E2E_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
  const body = {
    eventType: 'message',
    owner: false,
    waId: waId || process.env.E2E_PHONE || '',
    whatsappMessageId:
      messageId || `wamid.E2E_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    text,
    senderName,
    type: 'text',
  };
  if (!body.waId) throw new Error('postWatiInbound requires waId');

  const res = await fetch(`${apiBase}/api/whatsapp/webhook`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(`webhook ${res.status}: ${JSON.stringify(data)}`);
  }
  return { ...data, waId: body.waId, whatsappMessageId: body.whatsappMessageId };
}

module.exports = { postWatiInbound };
