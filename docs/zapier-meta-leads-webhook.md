# Meta Instant Forms → Zapier → CRM Webhook

Real-time Facebook/Instagram Instant Form leads into Arihant CRM via the client's Zapier Zap.

Clara no longer subscribes to Meta `leadgen` webhooks. Zapier holds the Meta connection and POSTs the filled lead here.

## Callback (after deploy)

| | |
|--|--|
| **Callback URL** | `https://arihant-api.claraai.tech/api/zapier/leads/webhook?token=<ZAPIER_WEBHOOK_SECRET>` |
| **Auth** | Shared secret via query `token` (or header `X-Webhook-Secret`) |
| **Method** | `POST` JSON |

Generate a secret:

```bash
openssl rand -hex 24
```

## Env vars

```
ZAPIER_WEBHOOK_SECRET=
META_LEAD_FORM_PROJECT_MAP={"2124096745052549":"reserve-16","1874174036585908":"mira","4309061012643289":"melange","28059295887006740":"krsna","1858929181319661":"vivriti"}
```

Set `ZAPIER_WEBHOOK_SECRET` on the droplet in `/opt/arihant/.env`, then recreate the container (`/opt/arihant/redeploy.sh`) so the env reloads.

Keep CAPI outbound vars unchanged (`META_ACCESS_TOKEN`, `META_DATASET_ID`). Those are **CRM → Meta**, not this webhook.

## Form ID → project

| Form ID | Project |
|---------|---------|
| `2124096745052549` | Reserve 16 |
| `1874174036585908` | Mira |
| `4309061012643289` | Mélange |
| `28059295887006740` | Krsna |
| `1858929181319661` | Vivriti |

Unknown Form ID is logged as `unmapped_form` and **not** ingested.

## Field map

| Zap field | Required | CRM |
|-----------|----------|-----|
| Form ID | **yes** | Project (table above) |
| Email **or** Phone Number | **yes** (one of them) | `email` / `phone` |
| Lead ID | no | Idempotency (`zapier_leads_logs.leadgen_id`). Missing → `anon:{uuid}` (retries may duplicate) |
| First Name | no | Default `Unknown` |
| Last Name | no | `""` |
| Created At | no | `meta.created_at` |
| Budget | no | `budget` |
| Site Visit Preference | no | `schedule_visit` |

Defaults: `consent=true`, `source=Facebook Lead Form`.

Snake_case aliases (`form_id`, `phone_number`, …) are also accepted.

## Zapier setup

1. Trigger: Facebook Lead Ads (or existing Meta Zap).
2. Action: **Webhooks by Zapier → POST**.
3. URL: callback above (include `?token=...`).
4. Payload type: JSON. Map the fields in the table.
5. Unsubscribe Clara’s old Meta App callback (`/api/meta/leads/webhook`) so native Meta and Zap cannot both fire.

## Behaviour

1. Zapier POSTs JSON (auth via shared secret).
2. Form ID maps to a CRM project.
3. Lead is created/soft-deduped via the same intake path as website forms (`source=Facebook Lead Form`) — assignment + WhatsApp ack.
4. Audited in Mongo `zapier_leads_logs` (idempotent on Meta Lead ID).

## CRM → Meta (outbound, separate)

Inbound Zap does **not** send events back to Meta.

Outbound is Meta **Conversions API** (`QualifiedLead`) using `META_ACCESS_TOKEN` + `META_DATASET_ID`. Admin test: `POST /api/internal/meta-capi/test`. It is not auto-fired on Zap ingest.

## Ops / troubleshooting

1. App logs for `Zapier Meta lead` / `unmapped_form` / `invalid or missing secret`
2. Mongo `zapier_leads_logs` (`success`, `reason`, `form_id`, `lead_id`)
3. Mongo `lead_intake_logs` with `api_key_id` like `zapier-meta:melange`
4. Confirm `ZAPIER_WEBHOOK_SECRET` matches the Zap URL `token`

### curl smoke test

```bash
curl -i -X POST \
  "https://arihant-api.claraai.tech/api/zapier/leads/webhook?token=YOUR_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "Created At": "2026-08-13T10:00:00+05:30",
    "Lead ID": "test-lead-001",
    "Form ID": "4309061012643289",
    "First Name": "Test",
    "Last Name": "Lead",
    "Email": "test@example.com",
    "Phone Number": "9876543210",
    "Budget": "",
    "Site Visit Preference": ""
  }'
```

Expect HTTP `200` with `{"status":"ok"}` and a row in `zapier_leads_logs`.
