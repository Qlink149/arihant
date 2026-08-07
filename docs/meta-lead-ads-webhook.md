# Meta Lead Ads → CRM Webhook

Real-time Instant Form submissions from Facebook/Instagram Lead Ads into Arihant CRM.

## Callback (after deploy)

| | |
|--|--|
| **Callback URL** | `https://arihant-api.claraai.tech/api/meta/leads/webhook` |
| **Verify Token** | Value of `META_LEAD_VERIFY_TOKEN` in production `.env` (generate with `openssl rand -hex 24`) |
| **Subscribe to** | Page object → field **`leadgen`** |

## Env vars

```
META_APP_ID=
META_APP_SECRET=
META_PAGE_ID=383431805163700
META_PAGE_ACCESS_TOKEN=          # Page token with leads_retrieval (NOT CAPI token)
META_LEAD_VERIFY_TOKEN=
META_LEAD_FORM_PROJECT_MAP={"2124096745052549":"reserve-16","1874174036585908":"mira","4309061012643289":"melange","28059295887006740":"krsna","1858929181319661":"vivriti"}
```

## Form → project map

| Form ID | Project |
|---------|---------|
| `2124096745052549` | Reserve 16 |
| `1874174036585908` | Mira |
| `4309061012643289` | Mélange |
| `28059295887006740` | Krsna |
| `1858929181319661` | Vivriti |

## Subscribe the Page to the app

After the webhook verifies in Meta App Dashboard:

```bash
curl -i -X POST \
  "https://graph.facebook.com/v21.0/383431805163700/subscribed_apps?subscribed_fields=leadgen&access_token=PAGE_ACCESS_TOKEN"
```

## Behaviour

1. Meta notifies `POST` with `leadgen_id` (signed with App Secret).
2. We fetch lead `field_data` from Graph using the Page token.
3. Lead is created/soft-deduped via the same intake path as website forms (`source=Facebook Lead Form`).
4. Audited in Mongo `meta_lead_ads_logs` (idempotent on `leadgen_id`).

## Ops / troubleshooting

Prod env file on the droplet: `/opt/arihant/.env` (container started with `--env-file` via `/opt/arihant/redeploy.sh`).

### Symptom: leads in Fresh, not in Clara

Clara is a **separate** Meta webhook consumer from Fresh. Check:

1. App logs for `Meta leadgen` / `unmapped form` / `graph_fetch_failed` / `invalid signature`
2. Mongo `meta_lead_ads_logs` (`success`, `reason`)
3. Page token health (below)

Meta **App Dashboard → Test** payloads with IDs `444444444…` will always log `unmapped_form` / `graph_fetch_failed` and will **not** create CRM leads. That is expected.

### Refresh `META_PAGE_ACCESS_TOKEN` (required when Graph returns code 190)

User/session logout invalidates short-lived user-derived Page tokens (`OAuthException` 190 / subcode 467). Prefer a **long-lived Page token** (or System User) with `leads_retrieval` (+ page subscription perms).

1. Meta Business / Graph API Explorer → select the Arihant app + Page → generate Page token with `leads_retrieval`, `pages_manage_metadata`, `pages_show_list`, `pages_read_engagement`.
2. Exchange for long-lived if needed (Meta docs: long-lived page access token).
3. On the droplet, update **only** `META_PAGE_ACCESS_TOKEN=` in `/opt/arihant/.env` (do not wipe other keys).
4. Recreate the container so env reloads: `/opt/arihant/redeploy.sh` **or** stop/rm/run with the same `--env-file` (pull optional).
5. Validate + resubscribe + backfill:

```bash
# from backend/ locally with updated .env, or docker exec into fastapi-backend
python scripts/meta_lead_ads_ops.py health
python scripts/meta_lead_ads_ops.py subscribe
python scripts/meta_lead_ads_ops.py backfill --match-phone 8754025211 --match-phone 9790942415
# if Graph still cannot find them but Fresh confirmed contacts:
python scripts/meta_lead_ads_ops.py manual-contacts
```
