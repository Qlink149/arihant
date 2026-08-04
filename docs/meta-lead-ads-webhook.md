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
