# Lead Intake API

Public, multi-tenant endpoint for external websites (e.g. Mélange “Request a Call”) to submit leads into Arihant CRM.

**Caller model:** server-to-server only. The client’s backend holds the API key and POSTs to this API. Do **not** call this from a browser or put the API key in frontend code.

**CORS:** Keep `CORS_ORIGINS` limited to the CRM dashboard origin(s). This intake endpoint does not need the marketing site origin.

---

## Endpoint

```
POST /api/v1/leads/intake
```

**Auth header (required):**

```
X-API-Key: <plaintext_api_key>
```
clara will provide this

---

## Request body

| Field | Type | Required | Notes |
|-------|------|----------|--------|
| `first_name` | string | yes | |
| `last_name` | string | no | Stored as `""` if omitted |
| `email` | string | email **or** phone | Validated if present |
| `phone` | string | email **or** phone | Digits kept (country code); spaces/dashes stripped |
| `budget` | string | no | |
| `schedule_visit` | string | no | Free text / date preference |
| `consent` | boolean | yes | Missing → `422`. `false` is accepted and stored as `consent: false` |
| `source` | string | no | Defaults to the API key’s project name |
| `meta` | object | no | UTMs / extras (sanitized; stored as `intake_meta`) |
| `website` / `hp` | string | no | Honeypot — if filled, request still “succeeds” but lead is marked spam |

### Example

```json
{
  "first_name": "Priya",
  "last_name": "Sharma",
  "email": "priya@example.com",
  "phone": "+91 98765 43210",
  "budget": "1.5 Cr",
  "schedule_visit": "Weekend morning",
  "consent": true,
  "source": "Mélange Website",
  "meta": {
    "utm_source": "google",
    "utm_campaign": "melange_launch"
  }
}
```

---

## Success responses

**New lead — `201 Created`**

```json
{ "success": true, "lead_id": "uuid-here", "deduped": false }
```

**Soft-dedupe / double-click — `200 OK`**

Same project + matching email or phone within 30 days (or identical hit within 10 seconds):

```json
{ "success": true, "lead_id": "uuid-here", "deduped": true }
```

On dedupe the existing lead is updated (`submission_count` incremented, `updated_at` touched).

---

## Error responses

| Status | When | Body shape |
|--------|------|------------|
| `400` | Malformed JSON / empty body | `{ "success": false, "detail": "..." }` |
| `401` | Missing/invalid `X-API-Key` | `{ "success": false, "detail": "Invalid or missing API key" }` |
| `422` | Validation failed | `{ "success": false, "detail": [ { "loc": [...], "msg": "...", "type": "..." } ] }` |
| `429` | Per-key rate limit exceeded (default 60/min) | `{ "success": false, "detail": "Rate limit exceeded" }` |
| `500` | Unexpected server error | `{ "success": false, "detail": "Internal server error" }` |

Stack traces and internal details are never returned.

---

## curl example

```bash
curl -X POST "https://YOUR_API_HOST/api/v1/leads/intake" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: arihant_YOUR_KEY_HERE" \
  -d '{
    "first_name": "Priya",
    "last_name": "Sharma",
    "email": "priya@example.com",
    "phone": "+91 98765 43210",
    "budget": "1.5 Cr",
    "schedule_visit": "This Saturday",
    "consent": true,
    "meta": { "utm_source": "google" }
  }'
```

---

## Node.js example

```js
async function submitLead(payload) {
  const res = await fetch("https://YOUR_API_HOST/api/v1/leads/intake", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": process.env.ARIHANT_INTAKE_API_KEY,
    },
    body: JSON.stringify(payload),
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(`Intake failed (${res.status}): ${JSON.stringify(data)}`);
  }
  return data; // { success, lead_id, deduped }
}

await submitLead({
  first_name: "Priya",
  last_name: "Sharma",
  email: "priya@example.com",
  phone: "+91 98765 43210",
  consent: true,
  budget: "1.5 Cr",
  meta: { utm_source: "google" },
});
```

---
