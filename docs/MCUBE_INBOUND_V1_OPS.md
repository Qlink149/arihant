# MCUBE Inbound V1 — Ops handoff

## Endpoint to give MCUBE (Jyoti)

Configure Classic **On Call** and **On Hangup** to:

```
https://<CLARA_API_HOST>/api/v1/telephony/mcube/inbound?token=<MCUBE_WEBHOOK_SECRET>
```

- Prefer Hangup (includes `filename` recording + final `dialstatus` / `duration`).
- Same URL for On Call (partial events upsert by `callid`).
- Auth is query `token` (or header `X-Webhook-Secret`). **Not** the MCUBE `apikey` from the push body.

## Env (droplet)

```
MCUBE_ENABLED=false          # flip true when ready to process
MCUBE_WEBHOOK_SECRET=...     # long random secret
MCUBE_ALLOWED_IPS=           # optional; leave empty at first
MCUBE_ALLOWLIST_ENFORCE=false
```

Kill switch: with `MCUBE_ENABLED=false`, events are still **stored** in `mcube_events` (apikey redacted) but leads/timeline are not updated.

## Cron mop-up (same schedule family as process-slas)

```
POST /api/v1/cron/process-mcube-events
Authorization: Bearer <CRON_SECRET>
```

Reclaims `mcube_events` where `processed=false` and `attempts < 5`.

## Freshworks cutover checklist

1. Deploy Clara inbound endpoint + set env secrets.
2. Align Clara `users.email` with MCUBE `empemail` values ([MCUBE_AGENT_EMAIL_ALIGNMENT.md](MCUBE_AGENT_EMAIL_ALIGNMENT.md)).
3. Ask MCUBE to point Group On Hangup/On Call from  
   `http://10.40.180.9/connector/1576_Arihant_foundation_and_housing_limited.php`  
   → Clara URL above.
4. Place one test inbound call; verify:
   - `mcube_events` row (no raw apikey)
   - `calls` row with `empemail` / `callfrom` / `filename`
   - Lead `context_updates` entry `type: call` (if phone matched)
5. Confirm Freshworks no longer receives new call posts; keep Freshworks historical data as-is.

## Out of V1

Outbound click-to-call, Call Logs UI, auto stage changes.
