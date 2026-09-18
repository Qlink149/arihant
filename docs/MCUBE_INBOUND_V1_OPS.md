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
MCUBE_AUTO_CREATE_LEADS=true # unknown inbound callers → New lead assigned to Admin
```

Kill switch: with `MCUBE_ENABLED=false`, events are still **stored** in `mcube_events` (apikey redacted) but leads/timeline are not updated.

## Behavior (V1)

| Scenario | Result |
|----------|--------|
| Known phone (single lead match) | `calls` upsert + activity timeline `type: call` with `recording_url` on hangup |
| Unknown phone (no lead) | Auto-create **New** lead, assign to **Admin** (`roshni@arihantspaces.com`), timeline + recording |
| Ambiguous phone (multiple leads) | Admin notification only — **no** auto-create |
| CONNECTING (On Call) | Partial `calls` row; timeline waits for hangup |
| VOICEMSG / voicemail hangup | Finalized as `VOICEMAIL`; timeline + missed-call notify if applicable |
| Browser GET ping (URL test) | Stored in `mcube_events`, skipped for `calls`/leads |

Timeline writes are SLA-safe: `$push context_updates` + `$set last_call_at_dt` only (no `updated_at` bump on existing leads).

## Cron mop-up (same schedule family as process-slas)

```
POST /api/v1/cron/process-mcube-events
Authorization: Bearer <CRON_SECRET>
```

Reclaims `mcube_events` where `processed=false` and `attempts < 5`.

## Verification checklist

1. `mcube_events` row (no raw apikey)
2. `calls` row with `empemail` / `callfrom` / `filename`
3. Lead `context_updates` entry `type: call` with `recording_url` and **Listen to recording** link in Digital Twin
4. Unknown caller → new lead under Admin with source `MCUBE Inbound`

## Backfill (after deploy)

On droplet inside `fastapi-backend` container:

```bash
python scripts/backfill_mcube_timeline.py          # dry-run
python scripts/backfill_mcube_timeline.py --apply  # write
```

Fixes: reprocess failed events, missing timelines, auto-create from past unmatched calls, delete orphan `call_id=null` rows.

## Freshworks cutover checklist

1. Deploy Clara inbound endpoint + set env secrets.
2. Align Clara `users.email` with MCUBE `empemail` values ([MCUBE_AGENT_EMAIL_ALIGNMENT.md](MCUBE_AGENT_EMAIL_ALIGNMENT.md)).
3. Ask MCUBE to point Group On Hangup/On Call from  
   `http://10.40.180.9/connector/1576_Arihant_foundation_and_housing_limited.php`  
   → Clara URL above.
4. Place one test inbound call; verify checklist above.
5. Confirm Freshworks no longer receives new call posts; keep Freshworks historical data as-is.

## Out of V1

Outbound click-to-call, Call Logs UI, auto stage changes.
