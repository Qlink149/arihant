# Channel Partner Lead Forms → CRM Webhook

Serves the 3 client-hosted channel-partner submission pages:

- https://projects.arihantspaces.com/cp-leads-r16/
- https://projects.arihantspaces.com/cp-leads-melange/
- https://projects.arihantspaces.com/cp-leads-mira/

Unlike the Webflow/Zapier webhooks, this endpoint returns **real HTTP status codes** (not an always-200 ACK), and **rejects a lead outright if the mobile number already exists anywhere in the CRM** — it never silently merges it the way Webflow/Zapier resubmissions do. These are the client's own forms; the visitor should see a validation or duplicate message, not a silently dropped submission.

## Callback (after deploy)

| | |
|--|--|
| **Callback URL** | `https://arihant-api.claraai.tech/api/channel-partner/leads/webhook?token=<CHANNEL_PARTNER_WEBHOOK_SECRET>` |
| **Auth** | Shared secret via query `token` (or header `X-Webhook-Secret`) |
| **Method** | `POST` — accepts JSON (`Content-Type: application/json`) or a plain HTML form post (`application/x-www-form-urlencoded` / `multipart/form-data`) |

Generate a secret:

```bash
openssl rand -hex 24
```

## Env vars

```
CHANNEL_PARTNER_WEBHOOK_SECRET=
```

Set on the droplet in `/opt/arihant/.env`, then recreate the container so the env reloads.

## Field map

These are exactly the Field IDs from the client's form-builder mapping table. Common aliases (`Mobile Number`, `mobile_number`, `phone`, etc.) are also accepted defensively, but the form should send these:

| Field | Field ID | Required |
|---|---|---|
| First Name | `first_name` | **Yes** |
| Last Name | `last_name` | No |
| Email | `email` | No |
| Mobile Number | `mob_number` | **Yes** |
| Channel Partner | `channel_partner` | No (see below) |
| Project (Hidden) | `project` | **Yes** — must resolve to one of the 3 projects below |
| Comments | `comments` | No |

## Project field → CRM project

Each page's hidden `project` field sends one of these values (both the exact hidden-field spelling and the normally-spaced variant resolve to the same project):

| Submitted `project` value | CRM project |
|---|---|
| `Anna Nagar - Mira` | Mira |
| `ECR - Reserve16` (client's exact spelling, no space) | Reserve 16 |
| `ECR - Reserve 16` | Reserve 16 |
| `Saligramam Melange` | Mélange |

Any other value returns `400 unknown_project` — only these 3 forms are wired up today.

## Channel Partner list

The dropdown's canonical list (kept in sync in `backend/crm/constants/lead_picklists.py::CANONICAL_CHANNEL_PARTNERS` and `frontend/src/constants/leadPicklists.js::CANONICAL_CHANNEL_PARTNERS`):

Home Konnect, Propmart, PropLeaf, Kaaviya Homes, Nobroker, Chennai Gated Community, Southzone Realty, Medsea Properties, Proptiger, Thara Properties, JLL, Prop Smile, Reliable Consultancy, C4 Realty, Proffiz, Estates61, Ground7Realty, Options Realtors & Tenancy Management, SRS Properties, Elite Realtors, Property Book, Rare Property, Meadows Realty, Zubair Realty, Tora, Propjoy, Housepecker, Hanu Reddy, Gopal Realty, Right Choice, Avishtra, 24K, 3pin Realty, F&P Homes, Connection Point, Property Pistol, 5star Realestate, Prop Crest, Individual, Others.

Matching is case/whitespace-insensitive. **A blank or unrecognized value never blocks the lead** — it's stored as-is (or left empty) and flagged in `intake_meta.channel_partner_unmatched` for cleanup later. Add new partners to both lists above as they're onboarded; the lead is still created in the meantime.

## HTTP contract

| Case | Status | Body |
|---|---|---|
| Bad/missing secret | `401` | `{"status":"error","reason":"unauthorized"}` |
| Unknown project | `400` | `{"status":"error","reason":"unknown_project", "message": "..."}` |
| Missing first name | `400` | `{"status":"error","reason":"missing_required_field","message":"First name is required."}` |
| Missing mobile number | `400` | `{"status":"error","reason":"missing_required_field","message":"Mobile number is required."}` |
| **Mobile number already exists anywhere in the CRM** | **`409`** | `{"status":"duplicate","message":"A lead with this mobile number already exists in Clara CRM."}` |
| Same submission retried within 10 seconds (double-click) | `200` | `{"status":"ok","lead_id":"...","deduped":true}` |
| New lead created | `201` | `{"status":"created","lead_id":"..."}` |

The `409` is intentional and different from every other lead-intake path in this CRM (Webflow/Zapier/API-key merge a matching phone as a resubmission). A channel partner should not get attribution credit for a customer already in the system under any status, project, or age — the landing page should show the visitor something like "You're already registered with us, our team will be in touch," not create a second record.

## What happens on success

- The lead is created with `lead_source = "channel partner"` and `channel_partner = "<selected partner>"`.
- The comment (if any) is added as the first note on the lead's timeline (shows up under "Recent note" immediately, same as an agent-typed note).
- The timeline's "Lead created" entry records which partner and project it came from.
- The lead is routed into the normal assignment pool for that project (Reserve 16 / Mélange / Mira), exactly like any other new lead.
- The lead is visible and filterable in Virtual Customer by the new **Channel Partner** filter, and the field can be viewed/corrected from the lead profile's Lead Overview grid.

## Phone-matching note

Matching uses the same `normalize_phone()` the rest of the CRM already relies on (`backend/crm/utils/helpers.py`) — it reduces any submitted number, with or without a `+91` country code, to the same 10-digit canonical form already stored on every existing lead. A read-only production audit (2026-09-29) confirmed all 30,195 leads with a phone number already have this field populated with no collisions, so the duplicate check is reliable today with no data backfill required.

## Smoke test

```bash
curl -s -X POST 'https://arihant-api.claraai.tech/api/channel-partner/leads/webhook?token=<CHANNEL_PARTNER_WEBHOOK_SECRET>' \
  -H 'Content-Type: application/json' \
  -d '{
    "first_name": "Test",
    "last_name": "Lead",
    "email": "test@example.com",
    "mob_number": "9000000000",
    "channel_partner": "Home Konnect",
    "project": "Saligramam Melange",
    "comments": "Smoke test — safe to delete"
  }'
```

Submit the same body twice in a row to see the `409 duplicate` response.

## Test coverage

- `backend/tests/test_channel_partner_leads_unit.py` — field extraction, project/partner resolution, required-field validation, duplicate-reject behavior, idempotency.
- `backend/tests/test_lead_intake_unit.py` — `ingest_lead(duplicate_policy="reject")` regression tests (old duplicates, race conditions, default "merge" behavior for Webflow/Zapier/API-key unchanged).
