# Webflow Enquiry Forms → CRM Webhook

Real-time Webflow `form_submission` events from Arihant project enquiry forms into Arihant CRM.

## Callback (after deploy)

| | |
|--|--|
| **Callback URL** | `https://arihant-api.claraai.tech/api/webflow/leads/webhook?token=<WEBFLOW_WEBHOOK_SECRET>` |
| **Auth** | Shared secret via query `token` (or header `X-Webhook-Secret`) |
| **Subscribe to** | Webflow site webhook trigger **`form_submission`** |

Generate a secret:

```bash
openssl rand -hex 24
```

## Env vars

```
WEBFLOW_WEBHOOK_SECRET=
```

Set on the droplet in `/opt/arihant/.env`, then recreate the container (`/opt/arihant/redeploy.sh` or equivalent) so the env reloads.

## Form name → project map

| Webflow form name | CRM project |
|-------------------|-------------|
| Melange Enquiry Form | Mélange |
| Mira Enquiry Form | Mira |
| Reserve 16 Enquiry Form | Reserve 16 |
| Vivriti Enquiry Form | Vivriti |
| Krsna Enquiry Form | Krsna |
| Chamiers Road Enquiry Form | Chamiers Road - Project |
| Flowers Road Enquiry Form | Flowers Road - Kilpauk |
| Guindy Enquiry Form | Guindy |
| Thoraipakkam Enquiry Form | Thoraipakkam |

**`Project-Name` is preferred** when present (shared / homepage forms). Form name is the fallback.

| Webflow `Project-Name` | CRM project |
|------------------------|-------------|
| Melange / Mélange | Mélange |
| Mira | Mira |
| Reserve 16 | Reserve 16 |
| Vivriti | Vivriti |
| Krsna | Krsna |
| Chamiers Road | Chamiers Road - Project |
| Flowers Road | Flowers Road - Kilpauk |
| Guindy | Guindy |
| Thoraipakkam | Thoraipakkam |

Placeholder values like `Select one...` are ignored.

## Field map (all forms)

| Webflow field | CRM intake |
|---------------|------------|
| `First-Name` | `first_name` |
| `Last-Name` | `last_name` |
| `phone` | `phone` |
| `Cust-EMail` | `email` |
| `Message` | `meta.message` |
| `Project-Name` | `meta.project_name` |

Also stored in `meta`: `webflow_submission_id`, `webflow_form_id`, `webflow_site_id`, `webflow_form_name`.

Defaults: `consent=true`, `source="{Project} Website"` (e.g. `Mélange Website`).

## Register in Webflow

1. Create a site webhook for trigger `form_submission` pointing at the callback URL above (include `?token=...`).
2. Or use Webflow Logic / Automations to POST the same form payload to that URL.
3. Point **only** these enquiry forms at this webhook. Do **not** also send the same submission through `/api/v1/leads/intake`, or you will double-create (soft-dedupe reduces impact but still adds noise).

## Behaviour

1. Webflow POSTs a `form_submission` envelope (`payload.name`, `payload.data`, `payload.id`, …).
2. We verify the shared secret.
3. Form name (or `Project-Name`) maps to a CRM project.
4. Lead is created/soft-deduped via the same intake path as other website forms.
5. Audited in Mongo `webflow_leads_logs` (idempotent on `submission_id`).

## Ops / troubleshooting

1. App logs for `Webflow enquiry` / `unmapped_form` / `invalid or missing secret`
2. Mongo `webflow_leads_logs` (`success`, `reason`, `form_name`, `lead_id`)
3. Mongo `lead_intake_logs` with `api_key_id` like `webflow:melange`
4. Confirm `WEBFLOW_WEBHOOK_SECRET` matches the `token` query param on the registered URL

### curl smoke test

```bash
curl -i -X POST \
  "https://arihant-api.claraai.tech/api/webflow/leads/webhook?token=YOUR_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "triggerType": "form_submission",
    "payload": {
      "name": "Melange Enquiry Form",
      "siteId": "test-site",
      "id": "test-submission-001",
      "formId": "test-form",
      "data": {
        "Project-Name": "Melange",
        "First-Name": "Test",
        "Last-Name": "Lead",
        "phone": "9876543210",
        "Cust-EMail": "test@example.com",
        "Message": "Webhook smoke test"
      }
    }
  }'
```

Expect HTTP `200` with `{"status":"ok"}` and a new/updated row in `webflow_leads_logs`.
