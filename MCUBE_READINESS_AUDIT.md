# MCUBE Readiness Audit — Arihant Spaces CRM
Date: 2026-08-24
Commit: 2eb98c6
Branch: main

## 1. Executive Summary

The CRM already has external webhook patterns (WhatsApp/WATI, Webflow, Zapier, API-key intake), phone normalization to last-10 digits, a lead timeline (`context_updates` + `lead_events`), in-app + Brevo notifications, and a partial call surface (`POST /leads/{id}/call-summary` with `type: "call"` timeline entries). There is **no** MCUBE telephony integration — `"mcube"` appears only as a `lead_source` picklist value.

Production API evidence points at a DigitalOcean droplet (Gunicorn, 1 worker); Vercel configs exist but backend `vercel.json` has no crons. SLA runs only via HTTP `POST /api/v1/cron/process-slas` with `CRON_SECRET`. No Celery/queue/worker; no Caddyfile in-repo; no object storage for call recordings (GridFS is CSV-export only).

**Biggest risk:** any call webhook that updates a lead through paths that bump `updated_at_dt` will restart SLA timers that key or fall back on that field (especially Nurturing Warm and leads missing stage-entry `*_entered_at_dt`). Combined with `coerce_datetime` treating naive strings as UTC, MCUBE’s naive IST timestamps will be stored wrong unless converted explicitly.

## 2. Blockers

### BL-1 — Lead writes bump `updated_at_dt` and reset SLA fallback clocks
- **Evidence:** `backend/crm/services/lead_service.py:726-727` always sets both on `update_lead`; `backend/crm/api/v1/endpoints/call_summary.py:29-38` sets `updated_at_dt` on call summary; Nurturing Warm queries `"updated_at_dt": {"$lt": cutoff_24h}` at `backend/crm/services/sla_engine.py:647`.
- **Why it blocks:** Designing inbound call persistence before deciding a SLA-safe write path risks silently resetting timers.
- **Options:** (a) write call logs to a separate collection only; (b) lead touch that deliberately omits `updated_at_dt` (pattern exists in `lead_follow_up.py` / `ai_lead_regen.py`); (c) accept reset and clear/re-stamp stage clocks intentionally.

### BL-2 — Naive datetime coercion assumes UTC, not IST
- **Evidence:** `backend/crm/utils/helpers.py:47-48` — if `dt.tzinfo is None: return dt.replace(tzinfo=timezone.utc)`.
- **Why it blocks:** MCUBE sends naive IST strings like `"2023-10-12 11:49:57"`. Passing them through `coerce_datetime` stores them 5.5h wrong and corrupts SLA/business-time math.
- **Options:** Convert IST→UTC with `ZoneInfo("Asia/Kolkata")` before write (same idea as `ist_wall_to_utc_dt` at `helpers.py:18-30`); never feed raw MCUBE strings to `coerce_datetime`.

### BL-3 — No agent DID/extension field and no admin UI to edit user telephony fields
- **Evidence:** User schema has only optional `phone` (`backend/crm/models/schemas/user_schemas.py:7-11`); roles are `admin|manager|rep` only. `frontend/src/pages/PlatformOpsPage.js:16-41` is platform-operator list + impersonation — no user-field edit form. `adminCreateUser` exists in `frontend/src/services/api.js:80` but no page calls it for edits.
- **Why it blocks:** Outbound click-to-call and inbound agent-DID matching need a durable agent↔MCUBE number mapping with an ops path to maintain it.
- **Options:** Add `mcube_number` (or similar) to user schema + admin edit UI; or maintain mapping outside CRM (script/ops sheet) short-term.

## 3. Risks

### RK-1 — Dual deploy targets; BackgroundTasks reliability depends on runtime
- **Evidence:** DO droplet via `backend/Dockerfile:27-33` + `.github/workflows/deploy-do.yml`; Vercel via `backend/index.py:1-2`, `backend/vercel.json:1-3`. Prod docs cite `arihant-api.claraai.tech` / droplet `.env`.
- **Why it bites:** Webhook post-processing via `BackgroundTasks` is fine on long-lived Gunicorn; unreliable on Vercel serverless freeze-after-response.
- **Mitigation:** Treat DO gunicorn as the webhook host; do critical work in-request or durable store-then-process.

### RK-2 — No job queue; cron schedule not in-repo
- **Evidence:** No Celery/APScheduler/RQ/arq in requirements. SLA is HTTP-hit only (`cron.py:36-40`). `backend/vercel.json` has no `crons` array (contradicts some docs claiming Vercel Cron).
- **Why it bites:** Call follow-up jobs have nowhere to land except in-request work, `BackgroundTasks`, or new infrastructure.

### RK-3 — Phone duplicate clusters unknown; matching quality unknown
- **Evidence:** Unique sparse index on `normalized_phone` (`state.py:271-276`); live duplicate sample not run (see §9).
- **Why it bites:** Inbound caller-ID match may hit multiple leads; product policy for disambiguation is unset.

### RK-4 — No recording storage path
- **Evidence:** GridFS only for lead CSV export (`lead_export_service.py:355-368`); no S3/Spaces/Cloudinary client for CRM media.
- **Why it bites:** Recording URLs from MCUBE need a store-or-proxy strategy before UI playback.

### RK-5 — Webhook ACK patterns differ
- **Evidence:** WhatsApp/Webflow/Zapier return 200 `{"status":"ok"}` even on processing errors (`whatsapp.py:210-214`, `webflow_leads_webhook.py:48-51`); lead intake returns non-2xx on failures.
- **Why it bites:** MCUBE retry behavior depends on whether failures ACK or signal; wrong choice causes duplicates or silent loss.

### RK-6 — Partial/dead call UI
- **Evidence:** `call_summary` API + `CallSummary` schema exist; `leadsAPI.addCallSummary` in `api.js` has no React caller found; timeline can render `type === 'call'`.
- **Why it bites:** Easy to assume call logging is product-ready when only the API half exists.

## 4. Reusable Assets

| Asset | Citation | Reuse for |
|-------|----------|-----------|
| Shared-secret webhook verify (`token` / `X-Webhook-Secret`) | `webflow_leads_service.py:70-86`, `zapier_leads_service.py:36-52` | MCUBE webhook auth pattern |
| HMAC webhook verify (Gupshup) | `whatsapp.py:17-35` | If MCUBE provides signature headers |
| Cron Bearer secret | `cron.py:14-33` | Any scheduled call reconciliation |
| `normalize_phone` / `format_phone_for_gupshup` | `helpers.py:55-74` | Caller-ID normalize + dial format |
| `utc_now` / `iso_utc_now` / `ist_wall_to_utc_dt` | `helpers.py:9-30` | Timestamp storage convention |
| `create_notification` + dedupe_key | `notification_service.py:63-120` | Missed-call / recording-ready alerts |
| Brevo `send_sla_alert_email` | `brevo_service.py:224-230` | Email alerts for call failures |
| `context_updates` timeline + DigitalTwin UI | `call_summary.py:16-27`, `DigitalTwinPage.js:411-414,1037-1048` | Display call events |
| `log_lead_event` → `lead_events` | `lead_events.py:10-32` | Audit trail for call webhooks |
| SLA `_queue_task` / `_queue_lead_mutation` / bulk flush | `sla_engine.py:284-398,1175-1230` | If call-triggered SLA tasks are required |
| WhatsApp authenticated `<audio>` proxy | `WaAuthenticatedMedia.jsx`, `whatsapp.py` media proxy | Recording playback pattern |
| Lead duplicate groups + merge | `lead_service.py:368-394,1043-1070` | Multi-match inbound resolution UI |
| Per-route auth omission (no global JWT middleware) | `main.py:35-49` | New public webhook routes |

## 5. Gaps

| ID | Description | Files likely touched | Size |
|----|-------------|----------------------|------|
| GP-1 | MCUBE inbound webhook endpoint + auth + raw payload persistence | new endpoint/service under `backend/crm/api/v1/endpoints/`, `services/` | M |
| GP-2 | Outbound click-to-call HTTP client to MCUBE | new service; lead detail UI CTA | M |
| GP-3 | Call log collection/schema (CDR, direction, agent, recording URL, outcome) | models, indexes in `state.py`, API | M |
| GP-4 | SLA-safe lead touch (or explicit product decision to bump activity) | `lead_service` or dedicated writer | S |
| GP-5 | Agent↔MCUBE number field + admin edit UI | `user_schemas.py`, auth/users API, new React page/component | M |
| GP-6 | Inbound phone match + duplicate disambiguation | match service; possibly DigitalTwin / notification | M |
| GP-7 | Recording storage or durable proxy + player on lead timeline | storage client or proxy; DigitalTwin | L |
| GP-8 | IST-naive timestamp parse helper for MCUBE payloads | `helpers.py` | S |

## 6. Section Findings

### A. Deployment topology and runtime

**A1. Which files define deployment?**

| Path | Present |
|------|---------|
| `backend/vercel.json` | Yes |
| `frontend/vercel.json` | Yes |
| `backend/Dockerfile` | Yes |
| `docker-compose*` | **Not found** |
| `Caddyfile` | **Not found** |
| `.github/workflows/deploy-do.yml` | Yes |
| `.github/workflows/pytest.yml` | Yes (CI, not deploy) |
| DO App Spec / `.do/` | **Not found** |

Related: `backend/index.py` (Vercel ASGI entry); droplet script `/opt/arihant/redeploy.sh` referenced by CI but not in this repo.

**A2. Is FastAPI served from Vercel, DigitalOcean, or both?**

**Both targets exist in-repo; production docs point at DigitalOcean droplet. No in-repo route split.**

Vercel entry:
```1:2:backend/index.py
"""Vercel / ASGI entrypoint (must live next to requirements.txt)."""
from crm.main import app  # noqa: F401
```

```1:3:backend/vercel.json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "installCommand": "pip install -r requirements.txt"
}
```

DO container:
```27:33:backend/Dockerfile
CMD ["gunicorn", "crm.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "1", \
     "--timeout", "120", \
```

Deploy workflow SSHes to droplet and runs `/opt/arihant/redeploy.sh` (`.github/workflows/deploy-do.yml:107-114`). All routers mount under `/api` (`main.py:49`) — no split of routes between hosts.

Whether Vercel still serves live API traffic today: **UNKNOWN — could not determine** from repo alone (configs exist; operational docs emphasize droplet).

**A3. Where does the SLA cron run, and how is it triggered?**

**HTTP-hit cron endpoint** — not a container sidecar process, not system crontab in-repo, not Vercel `crons` in current `vercel.json`.

```36:40:backend/crm/api/v1/endpoints/cron.py
@router.post("/process-slas")
async def process_slas(authorization: str | None = Header(default=None)):
    _verify_cron_secret(authorization)
    result = await SLAEngineService().process_all_slas()
    return result
```

Auth: `Authorization: Bearer {CRON_SECRET}` (`cron.py:14-33`). Work runs in-request via `process_all_slas()` with Mongo lock job `"process_slas"`.

**Who schedules the HTTP call in production:** **UNKNOWN — could not determine** (no cron expression, crontab, or DO scheduled-job config in repo). Docs that claim Vercel crons contradict empty `backend/vercel.json`.

**A4. Can a long-lived background process run in the same runtime that would serve an HTTP webhook?**

| Runtime | Long-lived? | `BackgroundTasks` after response |
|---------|-------------|----------------------------------|
| **DO Gunicorn + 1 Uvicorn worker** (`Dockerfile:27-33`) | Yes | Generally usable — process stays up |
| **Vercel serverless** | No | **Not reliable** — may freeze/terminate after response |

SSE comments assume single worker (`notifications_stream.py:10-14`). SLA itself awaits work inside the HTTP handler (does not rely on BackgroundTasks).

**A5. Queue / worker / scheduler?**

**None of:** Celery, APScheduler, RQ, arq (not in requirements).

What exists instead:
1. HTTP cron routes `/api/v1/cron/*` (`cron.py`)
2. MongoDB `cron_locks` for SLA
3. Unwired `reminder_scheduler` in `state.py:666-676` — **not** started from `main.py` startup (`main.py:61-68`)
4. FastAPI `BackgroundTasks` / `asyncio.create_task`
5. In-process SSE notification queues

**A6. Caddy?**

**Caddyfile not present.** No `trusted_proxies` / `ProxyHeadersMiddleware` in app. App reads `X-Forwarded-For` for intake IP logging only (`lead_intake.py:22-28`). SlowAPI uses `get_remote_address` (`rate_limit.py:1-4`). Proxy-front auth/rate-limit: **UNKNOWN — could not determine** (not in repo).

---

### B. Existing webhook and integration patterns

**B1. External-system routes**

All under `/api` (`main.py:49`). No Razorpay/payment callbacks found.

| Caller | Method + path | Definition |
|--------|---------------|------------|
| WATI / Gupshup WhatsApp | `POST /api/whatsapp/webhook` | `whatsapp.py:181` |
| Webflow | `POST /api/webflow/leads/webhook` | `webflow_leads_webhook.py:17` |
| Zapier Meta forms | `POST /api/zapier/leads/webhook` | `zapier_leads_webhook.py:17` |
| Website intake | `POST /api/v1/leads/intake` | `lead_intake.py:31` |
| Cron | `POST /api/v1/cron/process-slas` | `cron.py:36` |
| Cron | `POST /api/v1/cron/nurturing-review` | `cron.py:43` |
| Cron | `POST /api/v1/cron/process-reminders` | `cron.py:51` |
| Cron | `POST /api/v1/cron/backfill-lead-stats` | `cron.py:58` |

Also public (not third-party webhooks): `GET /api/`, `GET /api/health`; auth login/refresh.

**B2. Authentication (quoted)**

WhatsApp — Gupshup HMAC; WATI none:
```181:214:backend/crm/api/v1/endpoints/whatsapp.py
@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    ...
      provider=wati     → no HMAC check
      provider=gupshup  → enforces Gupshup HMAC signature
```

```17:35:backend/crm/api/v1/endpoints/whatsapp.py
async def _verify_gupshup_signature(request: Request) -> None:
    x_hub_signature = request.headers.get("x-hub-signature-256")
    ...
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
```

Webflow / Zapier — shared secret query `token` or header `X-Webhook-Secret` (`webflow_leads_webhook.py:27-32`, `zapier_leads_webhook.py:27-32`; verify via `hmac.compare_digest`).

Lead intake — `X-API-Key` hashed lookup (`lead_intake.py:31-54`, `api_key_service.py:84-93`).

Cron — `Authorization: Bearer <CRON_SECRET>` (`cron.py:14-33`).

**B3. How JWT is bypassed**

**There is no global auth middleware.** `main.py` adds CORS + SlowAPI only (`main.py:35-43`). JWT is opt-in via `Depends(get_current_user)` (`state.py:214`, `state.py:630+`). External routes simply omit that dependency and do local secret checks.

**B4. Raw inbound payload persistence before processing?**

**No dedicated pre-process raw store.** WhatsApp attaches `raw_payload` on `whatsapp_messages` **during** upsert (`whatsapp_service.py:1405-1419`, also Gupshup paths ~2345/2421). Webflow/Zapier: no raw dump. Lead intake writes `lead_intake_logs` metadata only (`lead_intake_service.py:237-252`) — not raw body.

**B5. Success / failure responses**

| Route | Success | Processing failure | Auth non-2xx |
|-------|---------|-------------------|--------------|
| WhatsApp | 200 `{"status":"ok"}` | 200 `{"status":"ok"}` | Gupshup 401/500 HMAC |
| Webflow/Zapier | 200 `{"status":"ok"}` | 200 ACK after auth | 401 |
| Lead intake | 2xx from ingest | 500 | 401/400/422/429 |
| Cron | 200 + result dict | global 500 handler | 401/503 |

WhatsApp always-200 on processing errors (`whatsapp.py:210-214`).

**B6. Outbound HTTP clients**

No shared timeout/retry wrapper. Per-call `httpx.AsyncClient` for WATI, Gupshup reminders, Brevo (`brevo_service.py:128-134`, timeout 30s), Meta CAPI; sync `requests` for LLM. Razorpay: **not present**.

---

### C. Datetime and timezone convention

**C1. Are datetimes stored as timezone-aware UTC or naive IST?**

**Timezone-aware UTC** via `utc_now()`.

```9:15:backend/crm/utils/helpers.py
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc_now() -> str:
    return utc_now().isoformat()
```

Lead create (`lead_service.py:247-250`):
```
"created_at": now_iso,
"created_at_dt": now_dt,
"updated_at": now_iso,
"updated_at_dt": now_dt,
```

Lead update always (`lead_service.py:726-727`):
```
patch["updated_at"] = now_iso
patch["updated_at_dt"] = now_dt
```

Intake create same pattern (`lead_intake_service.py:459-505`). Naive values in `coerce_datetime` are tagged as UTC (`helpers.py:47-48`) — **not** IST.

**C2. `_dt` suffix convention**

| Pair | Role | Writers |
|------|------|---------|
| `updated_at` (ISO string) | Legacy string / API surface | Same paths as `_dt` |
| `updated_at_dt` (BSON datetime) | Indexed ranges, SLA | `utc_now()` on create/update |
| `gone_cold_entered_at_dt` | Stage-entry clock | Status → Gone Cold in `update_lead` (`lead_service.py:596-600`) |

No `gone_cold_entered_at` string twin found. `LeadResponse` exposes `created_at`/`updated_at` as datetime; `extra="ignore"` drops bare Mongo `_dt` fields from typed response (`lead_schemas.py:105-106`).

**C3. `business_time.py` tz handling**

```12:27:backend/crm/utils/business_time.py
IST = ZoneInfo("Asia/Kolkata")
BUSINESS_START = time(10, 0)
BUSINESS_END = time(17, 30)
...
def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

def _to_ist(dt: datetime) -> datetime:
    return _ensure_utc(dt).astimezone(IST)
```

`business_seconds_elapsed` converts both ends to IST, counts Mon–Sat 10:00–17:30 overlap (`business_time.py:99-123`).

**C4. API → React**

Backend emits ISO UTC. Frontend `frontend/src/utils/datetime.js` treats naive strings as UTC (appends `Z`) then displays with `timeZone: 'Asia/Kolkata'` via `formatDateTimeIST` (`datetime.js:1-40`, `56-63`). Client conversion = parse-as-UTC → display-as-IST.

**C5. One-line rule for MCUBE timestamps**

**Convert MCUBE’s naive IST wall time to timezone-aware UTC before write** (e.g. parse then `.replace(tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(timezone.utc)`), store BSON `*_dt` UTC + matching ISO `*_at`; **never** pass naive IST through `coerce_datetime` (it tags naive as UTC). Prefer the `ist_wall_to_utc_dt` pattern (`helpers.py:18-30`).

---

### D. SLA engine coupling

**D1. Every SLA rule and t0 field**

Invoked from `process_all_slas` (`sla_engine.py:1232-1257`).

| Rule | t0 / clock | Cite |
|------|------------|------|
| New 1h reassign | `created_at_dt` + business seconds | ~490-493 |
| New 2h admin alert | `created_at_dt` | ~505-518 |
| RNR reminders / escalate | `rnr_entered_at_dt` or `updated_at_dt` | ~546, 117-122, 587-589 |
| Contacted 48h/72h | `contacted_at_dt` or `updated_at_dt` | ~621 |
| Nurturing → Warm | **`updated_at_dt` only** | **647** |
| Nurturing Hot/Warm cadence | `nurture_entered_at_dt` or `updated_at_dt` | ~670 |
| Interested 7d | `interested_entered_at_dt` or `updated_at_dt` | ~718 |
| Visit scheduled missing date | status + missing `visit_date_dt` | ~748-752 |
| Visit pre_24h / post_24h | `visit_date_dt` ± 24h | ~770-815 |
| Visit completed 3d | `visit_sla_reference_dt` → `visit_completed_at_dt` → `updated_at_dt` | ~863-866 |
| SV Follow-up 1 / 2 | dedicated `*_entered_at_dt` only | ~898, 937 |
| Negotiation | `negotiation_entered_at_dt` or `updated_at_dt` | ~1064 |
| Gone Cold 30d | `gone_cold_entered_at_dt` or `updated_at_dt` | ~1099 |
| Future Prospect 90d | `future_prospect_entered_at_dt` or `updated_at_dt` | ~1132 |
| Re-engaged | `reengaged_at_dt` or `updated_at_dt` | ~1007-1016 |

Fallback helper `_entered_at_or_updated_fallback` (`sla_engine.py:107-114`).

**D2. Rules still keyed on `updated_at_dt`**

- **Sole primary:** Nurturing empty-temperature Warm (`sla_engine.py:647`).
- **Primary-or-fallback:** RNR, Contacted, Nurturing cadence, Interested, Visit Completed, Negotiation, Gone Cold, Future Prospect, Re-engaged.
- **Not using `updated_at_dt` as t0:** New (`created_at_dt`), Visit Scheduled (visit date), SV Follow-up 1/2 (dedicated fields only).

**D3. Lead write path and `updated_at_dt`**

Main mutator `update_lead` **unconditionally**:
```726:727:backend/crm/services/lead_service.py
    patch["updated_at"] = now_iso
    patch["updated_at_dt"] = now_dt
```
then `update_one` `$set`. Create also sets both (`lead_service.py:247-250`). Other bumpers: call summary, notes, intake, WhatsApp context, assignment, campaigns, transfers, SLA `_queue_*` lead ops.

**D4. If a call webhook writes to a lead, which SLA timers reset?**

**No MCUBE webhook exists today.** Closest path `POST /leads/{lead_id}/call-summary` **does** bump `updated_at_dt` (`call_summary.py:29-38`).

Therefore, if a call webhook follows the same pattern:
- Timers with **dedicated stage fields set** → **not reset** (still use entry `_dt`).
- Timers that **fallback to / key off `updated_at_dt`** (esp. **Nurturing Warm**, and any lead missing stage-entry `_dt`) → clock **restarts** from this write.
- Does **not** clear `sla_flags` (already-fired thresholds stay fired).

If writes go through a path that **omits** `updated_at_dt` (see D5), those fallback timers are **not** reset.

**D5. Paths that deliberately do not bump `updated_at_dt`?**

**Yes.** Examples:
- `recompute_lead_next_action_date` — only `$set`/`$unset` `next_action_date` (`lead_follow_up.py:34-42`).
- AI regen — sets AI fields + `ai_last_generated_at_dt` without activity stamp (`ai_lead_regen.py:173-183`).
- Also: nurture task id write without activity stamp; inventory blocked-reason write.

**D6. `_queue_task` / `_queue_lead_mutation`, dedupe, bulk flush**

Signatures (`sla_engine.py:284-299`, `388-396`):
```python
def _queue_task(self, lead, description, dedupe_key, flag_path, now_dt, now_iso,
                name_to_user_id, escalation_target=None, priority="medium",
                sla_rule="", sla_threshold="", extra_lead_set=None, due_date=None) -> None

def _queue_lead_mutation(self, lead_id, set_fields, flag_path, now_dt, now_iso, summary_key) -> None
```

Dedupe: task keys like `sla:{rule}:{threshold}:{lead_id}`; notifications `notif:{dedupe_key}`; unique sparse indexes (`state.py:299-308`).

Bulk flush: accumulate `InsertOne`/`UpdateOne` on `_task_ops` / `_notif_ops` / `_event_ops` / `_lead_ops`; `_flush_bulk_writes` → `bulk_write(..., ordered=False)` tolerating `BulkWriteError` (`sla_engine.py:1175-1230`, `1259`). Note: `_queue_task` itself also `$set`s `updated_at_dt` on the lead when stamping the flag (`sla_engine.py:373-384`).

**D7. Terminal/closed exclusion**

```26:45:backend/crm/constants/lead_status.py
CLOSED_LEAD_STATUS_REGEX = re.compile(
    r"closed|booked|advance paid|dropped|junk|unqualified",
    re.IGNORECASE,
)
...
def terminal_exclusion_clause() -> dict:
    return {"$not": {"$regex": CLOSED_LEAD_STATUS_REGEX.pattern, "$options": "i"}}
```

Applied on every SLA rule via `_rule_query` (`sla_engine.py:235-241`) plus `sla_paused` exclusion. Gone Cold is **not** terminal under this regex.

**D8. Duplicate avoidance across cron ticks**

1. `sla_flags.{rule}.{threshold}_at_dt` — query requires flag not set; on fire, set to `now_dt`.
2. Unique `dedupe_key` on tasks/notifications.

Example flag paths: `sla_flags.new.reassign_1h_at_dt`, `sla_flags.nurturing.temperature_warm_at_dt`, `sla_flags.interested.7d_at_dt`, `sla_flags.gone_cold.reevaluate_30d_at_dt`. Test shape with empty `sla_flags: {}` then assert flag written (`test_interested_sla.py:18-39`).

**D9. Cron vs event-driven**

**Primary:** cron `POST /v1/cron/process-slas` → `process_all_slas()`.

**Event-driven entry points:**
1. Re-engaged t0 qualify task on status change in `update_lead` (`lead_service.py:823-832`) via `create_sla_task_for_lead`.
2. Same helper on website intake re-engage (`lead_intake_service.py:437-448`).
3. Status-change side effects: cancel pending SLA tasks; stamp stage-entry `*_entered_at_dt`; clear selected `sla_flags`; unlock `sla_paused` (`lead_service.py:558-631`).
4. Separate crons: nurturing-review, process-reminders (`cron.py:43-55`).

No general “on any status change, run all SLA rules” hook.

---

### E. Lead model and phone data

**E1. Full lead schema**

See `LeadBase` / `LeadUpdatePatch` / `LeadResponse` in `backend/crm/models/schemas/lead_schemas.py:7-151` (full paste in research; key fields include `phone`, `work_phone`, status/source, SLA stage `*_entered_at_dt` fields, AI fields, `context_updates`, `created_at`/`updated_at`). Create also persists fields beyond schema (`intent`, `vip`, `assigned_to`, `routing_state`, etc. in `lead_service.create_lead`).

**E2. Phone fields**

| Name | Type | Required? | Role |
|------|------|-----------|------|
| `phone` | `Optional[str]` | No (schema) | Primary |
| `work_phone` | `Optional[str]` | No | Alternate |
| `normalized_phone` | derived | — | Dedup/search |
| `normalized_work_phone` | derived | — | Search |

Intake requires email **or** phone (`lead_intake_service.py:164-168`).

**E3. Live phone formats (~50 sample)**

**UNKNOWN — could not determine.** Live Mongo sample via `backend/.env` was not authorized at execute time (plan default). Searched: seed/normalize comments only. Code stores raw phone plus last-10 `normalized_phone` (`helpers.py:55-63`); intake stores raw digits max 32 (`lead_intake_service.py:90-95`).

**E4. Phone normalization utility**

`normalize_phone` (`helpers.py:55-63`) — strip non-digits, drop leading `91` if >10, drop leading `0`, keep last 10. **Applied on write** via `_apply_contact_phones` on create/update/import (`lead_service.py:118-125`, create ~154, update ~440-449). Search may normalize query term on read (`lead_search.py`). Also `format_phone_for_gupshup` → `91` + 10 digits (`helpers.py:66-74`).

**E5. Indexes on leads (phone)**

**In code** (`state.py:271-276`):
```python
await db.leads.create_index(
    [("normalized_phone", 1)],
    unique=True, sparse=True,
    name="leads_normalized_phone_uq_sparse",
)
```
Also compound `(project_id, normalized_phone, created_at_dt)` (`state.py:510-512`). Live `getIndexes()`: **UNKNOWN — could not determine** (DB probe not run).

**E6. Duplicate phone clusters in live data**

**UNKNOWN — could not determine** (aggregation not run). Code supports listing duplicates via `find_duplicate_lead_groups` (`lead_service.py:368-394`). Unique sparse index should prevent new duplicates of the same `normalized_phone` on insert, but historical/null/sparse cases may still cluster.

**E7. Duplicate-lead detection / merge**

Yes: `GET /leads/duplicates` → `find_duplicate_lead_groups`; `merge_leads` concatenates `context_updates`, appends `type: "merged"`, deletes duplicate — does not merge other fields (`lead_service.py:1043-1070`). Frontend merge in VirtualCustomer / `leadsAPI.merge`.

**E8. `source` / `lead_source`**

Free `Optional[str]` on schema (`lead_schemas.py:21-23`) — **not** a Pydantic enum. Canonical picklist `CANONICAL_SOURCES` in `backend/crm/constants/lead_picklists.py:128-201` (includes `"mcube"`) mirrored in `frontend/src/constants/leadPicklists.js`. Not hard-validated on write.

**E9. Lead statuses (17) and terminals**

```5:23:backend/crm/constants/lead_status.py
UI_LEAD_STATUSES = [
    "New", "RNR", "Contacted", "Nurturing", "Interested",
    "Site Visit Scheduled", "Visit Completed", "SV Follow-up 1", "SV Follow-up 2",
    "Negotiation", "Gone Cold", "Future Prospect", "Re-engaged",
    "Junk", "Unqualified", "Closed Won", "Closed Lost",
]
```

Terminal via `CLOSED_LEAD_STATUS_REGEX` among the 17: **Junk, Unqualified, Closed Won, Closed Lost**. Regex also treats historical labels containing `booked` / `advance paid` / `dropped` as terminal.

---

### F. Users, agents, and roles

**F1. User schema**

```7:11:backend/crm/models/schemas/user_schemas.py
class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    role: Literal["admin", "manager", "rep"] = "rep"
```

Persisted users also have `hashed_password`, `is_active`, session fields (`auth.py` create paths). **No extension / DID / SIP / mcube_number field.**

**F2. Roles**

`admin | manager | rep` only (`user_schemas.py:11`, `32`). Manager is distinct from admin and rep. **No General Manager / GM role** in code.

**F3. Agent ACTIVE for routing**

```60:71:backend/crm/services/assignment_router.py
async def is_active_for_routing(user: dict, now_dt: Optional[datetime] = None) -> bool:
    ...
    if not user.get("is_active", True):
        return False
    if not is_business_hours_ist(now_dt):
        return False
    activity = await db.user_activity.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
    return is_on_duty_today(activity, now_dt)
```

On-duty = login/active today IST (`business_time.py:76-88`). Ops UI: `OpsActiveStatusPage.js`.

**F4. Admin UI for editing user fields**

**No React form edits user profile fields** (name/phone/role). Closest: `frontend/src/pages/PlatformOpsPage.js` (impersonation only); `OpsActiveStatusPage.js` (read-only presence). Create-user API exists (`auth.py` admin create); `adminCreateUser` in `api.js` has no edit page. A new `mcube_number` would need **new** schema + API + UI — no existing component to hang it on.

**F5. `assigned_to` storage**

**Display name string** (`full_name`), plus `assigned_user_id` (UUID string of user `id`), `assigned_to_name` / `presales_agent` name strings (`lead_service.py:236-239`, `assignment_router.py:171-173`). Not ObjectId/email for `assigned_to`.

---

### G. Activity / timeline / notifications

**G1. Activity / timeline collections**

**Embedded timeline:** `leads.context_updates` — list of dicts; observed `type` values: `created`, `assigned`, `updated`, `note`, `call`, `whatsapp`, `merged` (no formal Enum).

**Audit collection:** `lead_events` via `log_lead_event` (`lead_events.py:10-32`):
```python
doc = {
    "id", "event_type", "lead_id", "actor_user_id", "actor_name",
    "payload", "created_at", "created_at_dt",
}
```
`event_type` strings used (no Enum): `sla_action`, `transfer_created`, `assignee_changed`, `note_added`, `note_edited`, `task_created`, `task_updated`, `lead_exact_lookup_granted`, `lead_search_grant`.

**G2. React timeline**

`frontend/src/pages/DigitalTwinPage.js` — “Context Updates Timeline” via `getTimelineForDisplay(lead?.context_updates)` (`411-414`, `1037-1048`). Call entries render key points if `update.type === 'call'` (~1194-1207). Helpers: `frontend/src/utils/contextUpdates.js`.

**G3. Notification + Brevo interfaces**

```python
# notification_service.py:63+
async def create_notification(*, recipient_user_id, recipient_name="", title, message,
    notification_type="action_required", lead_id="", ..., dedupe_key=None, ...) -> Optional[dict]

# brevo_service.py
async def send_nurturing_review_email(*, lead_count, lead_rows, admin_user_id) -> bool  # :61-66
async def send_sla_alert_email(*, subject, body_html, admin_user_id, dedupe_key) -> bool  # :224-230
```

**G4. `SLA_OVERDUE_WINDOWS` and dedup**

Defined `notification_service.py:14-25` (per-stage threshold → seconds). Used by `compute_is_overdue` for badges. Notification dedup: existing row by `dedupe_key` returned (`notification_service.py:108-112`); unique sparse index on `notifications.dedupe_key` (`state.py:308`).

**G5. Existing “call” concepts**

| Piece | Status |
|-------|--------|
| `CallSummary` schema | `call_schemas.py:6-12` |
| `POST /leads/{id}/call-summary` | `call_summary.py:10-40` — pushes `type: "call"` to `context_updates`, bumps `updated_at_dt` |
| `leadsAPI.addCallSummary` | `api.js` — **no UI caller found** |
| Timeline display | DigitalTwin can render call key_points |
| `logged_outcome` | Contacted-stage CRM outcome, not telephony |
| `last_contacted_at` | **Not found** |
| Seed/import | Can create `type: "call"` timeline rows from Call_logs.csv (`seed_db.py`, import paths) |
| `"mcube"` | lead_source picklist only (`lead_picklists.py:164`) |

---

### H. Storage, files, and media

**H1.** CSV lead import upload; lead export CSV to **Mongo GridFS** (`lead_export_service.py:355-360`). No Cloudinary/S3/Spaces SDK for CRM media. WhatsApp media proxied from WATI.

**H2.** Export download is **authenticated API** reading GridFS by job `file_id` (`leads.py:397-404`) — not public/presigned URLs. WA media: auth-required proxy + private cache.

**H3.** WhatsApp bubble `<audio>` via `WaAuthenticatedMedia.jsx`. Notification beep uses Web Audio API. **No CRM call-recording player.**

**H4.** **No app-level max body/upload size** found in code/Dockerfile/uvicorn flags. Relies on reverse-proxy defaults — **UNKNOWN** for edge limits (no Caddy/nginx config in repo).

---

### I. Security posture

**I1. Auth system**

JWT via `OAuth2PasswordBearer` (`state.py:214`); `get_current_user` validates access token + session (`state.py:630+`). **Not global middleware** — per-route `Depends(get_current_user)`. Cron/webhooks use shared secrets instead.

**I2. Rate limiting**

SlowAPI global middleware (`main.py:43`) + `limiter` (`rate_limit.py:1-4`). Decorators on auth: register 3/min, admin create 20/min, login 10/min. Separate per-API-key intake limit (~60/min default). Keyed by `get_remote_address` (peer IP, not XFF).

**I3. CORS**

```35:42:backend/crm/main.py
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)
```

Default if unset: `*`.

**I4. Secrets loading**

No Pydantic BaseSettings. Module globals from `os.environ` in `state.py` (`MONGO_URL`, `DB_NAME` required; `SECRET_KEY` with weak default). Startup validation in `secrets.py:23-42` (fatal weak `SECRET_KEY`/`CRON_SECRET` unless `ENVIRONMENT=test`). Template: `backend/env.example`. DO droplet `/opt/arihant/.env` referenced in docs; Vercel/DO GitHub secrets for deploy.

**I5. Secrets committed to repo?**

- `.env` / `.env.*` are gitignored (`.gitignore:16-22`).
- No hardcoded `mongodb+srv://...@` or long API keys found under `backend/crm` via pattern search.
- Weak default string `"arihant-secret-key-change-in-production"` remains in source (`state.py:57`) — blocked at startup in non-test envs by `validate_production_secrets`.
- Full git-history secret scan: **UNKNOWN — could not determine** (history probe not authorized at execute time).

**I6. IP allowlist**

**None in application code.** No `ALLOWED_IPS` / whitelist middleware found.

---

### J. Database operations

**J1. Migrations**

**No migrations directory.** Schema evolution is code-driven (Pydantic + flexible Mongo documents). Indexes ensured at startup via `ensure_db_indexes()` (`main.py:66`, `state.py:251+`).

**J2. Where indexes are created**

In code at startup (`ensure_db_indexes` in `state.py`). Seed scripts also create some indexes. Manual ops: **UNKNOWN** beyond code.

**J3. Approximate document counts**

**UNKNOWN — could not determine** (live `estimated_document_count` not run). Collections referenced in code include `leads`, `users`, `tasks`, `lead_events`, `whatsapp_messages`, `notifications`, `lead_intake_logs`, `cron_locks`.

**J4. Staging vs production**

Distinguished by env vars: `MONGO_URL`, `DB_NAME`, `ENVIRONMENT` (`env.example:1-11`). CI uses `DB_NAME: arihant_crm_test`, `ENVIRONMENT: test` (`.github/workflows/pytest.yml:35-41`). A separate staging database/host is **not** defined as a named config in-repo — **UNKNOWN** whether a staging cluster exists operationally.

---

### K. Testing

**K1. Framework / location / how to run**

Backend: pytest (`backend/pyproject.toml`, `requirements-dev.txt`). Frontend: Vitest (`frontend/package.json` `"test": "vitest run"`). CI: `.github/workflows/pytest.yml`.

**K2. SLA engine tests**

At least 11 SLA-focused files under `backend/tests/`:

| File | Covers |
|------|--------|
| `test_sla_contacted_targets.py` | Contacted 48h/72h targets |
| `test_sla_import_hold.py` | `sla_paused` hold |
| `test_sla_rnr_reminders.py` | RNR reminder cap |
| `test_sla_rnr_lock_and_query.py` | RNR query + cron lock |
| `test_sla_rnr_escalate_query.py` | RNR escalate, no Admin ownership steal |
| `test_sla_sv_followup.py` | Legacy SV follow-up matcher |
| `test_sla_closed_exclusion.py` | Terminal + paused exclusion |
| `test_sla_visit_completed.py` | Visit completed helpers |
| `test_sla_paused_notifications.py` | Notifications respect pause |
| `test_sla_pagination.py` | Lead pagination batches |
| `test_sla_negotiation_escalation.py` | Negotiation escalations |

Also related: `test_interested_sla.py`, `test_cron_lock.py`, `test_sv_followup_stages.py`, `test_nurturing_review.py`.

**K3. Fixtures / factories**

Mostly `unittest.mock` / `AsyncMock` unit tests. Live HTTP suite `test_my_dashboard.py` uses module fixtures against `REACT_APP_BACKEND_URL`. No shared factory package for leads/users beyond ad-hoc dicts in tests.

**K4. Throwaway DB?**

CI spins Mongo service with `DB_NAME: arihant_crm_test` (`.github/workflows/pytest.yml:35-41`). Several integration-ish tests ignored in CI. Local default is whatever `MONGO_URL`/`DB_NAME` point to — tests can hit a real DB if misconfigured.

## 7. Decisions Required From Yogansh

**DQ-1 — May a call webhook update the lead document / bump activity without resetting SLA?**  
Options: (a) separate `call_logs` only; (b) lead write without `updated_at_dt`; (c) bump activity and accept timer reset.  
**Recommendation:** (a) or (b) — SLA is the critical subsystem; do not route MCUBE through `update_lead` / call-summary-style bumps by default.

**DQ-2 — Inbound match: `normalized_phone` only, or also `work_phone`? Duplicate-phone policy?**  
Options: primary only; primary then work; always notify assignee of all matches; force merge UI.  
**Recommendation:** Match `normalized_phone` first, then `normalized_work_phone`; if >1 lead, create notification with candidates rather than auto-attach.

**DQ-3 — Where is agent DID / MCUBE extension maintained?**  
Options: new user field + admin UI; ops script/CSV; MCUBE portal only.  
**Recommendation:** User field + admin UI (BL-3) so click-to-call and inbound agent attribution stay in CRM.

**DQ-4 — Recording retention and storage**  
Options: store MCUBE URL only; download to GridFS; download to object storage (Spaces/S3).  
**Recommendation:** Persist MCUBE URL + metadata first; add object storage only if URLs expire or auth blocks playback.

**DQ-5 — Should answered/outbound calls change lead status or `logged_outcome` automatically?**  
Options: timeline-only; auto-Contacted; agent confirms in UI.  
**Recommendation:** Timeline + notification only until SLA/status rules are product-specified.

**DQ-6 — Webhook failure semantics for MCUBE**  
Options: always-200 ACK (WhatsApp style); non-2xx to trigger vendor retry (intake style).  
**Recommendation:** Align with MCUBE docs; if they retry on 5xx, return 5xx only for transient failures after durable raw ingest.

## 8. Open Questions for MCUBE

1. Exact inbound webhook payload schema, auth method (shared secret, HMAC, IP allowlist), and retry/backoff on non-2xx.
2. Timestamp timezone of naive strings like `"2023-10-12 11:49:57"` — confirm IST wall clock.
3. Caller-ID / dialed-number formats (E.164, 0-prefix, extension) for inbound and outbound.
4. Click-to-call API: auth, agent identifier (extension vs DID vs login), request/response, idempotency.
5. Recording URL lifetime, auth requirements, and whether download is allowed for archival.
6. Event types delivered (ringing, answered, missed, hangup, recording-ready) and ordering guarantees.
7. Whether one webhook covers both inbound and outbound CDRs.
8. Rate limits and max payload size for webhooks and recording callbacks.
9. Sandbox/staging credentials and a non-production endpoint for UAT without touching live agents.

## 9. Unresolved

| ID | Item | What was searched / why unknown |
|----|------|--------------------------------|
| U-1 | A2 live traffic host (Vercel vs DO only) | Repo has both configs; no live routing probe |
| U-3 | A3 who schedules `process-slas` in prod | No crontab/cron expression/DO job in repo |
| U-A6 | Reverse-proxy (Caddy/nginx) config | No Caddyfile/nginx config in repo |
| U-E3 | Live phone format distribution (~50 leads) | Mongo sample via `.env` not authorized (plan default) |
| U-E5 | Live `getIndexes()` on `leads` | Same — code indexes cited instead |
| U-E6 | Live duplicate phone group count / largest cluster | Aggregation not run |
| U-H4 | Edge max request body size | No proxy config in repo |
| U-I5 | Secrets in full git history | History secret scan not authorized (plan default); tracked source pattern search found no live connection strings |
| U-J3 | Collection document counts | `estimated_document_count` not run |
| U-J4 | Whether a staging Mongo cluster exists operationally | Only env-var distinction in-repo |
