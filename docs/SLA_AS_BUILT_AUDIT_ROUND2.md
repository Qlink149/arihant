# Arihant CRM — As-Built SLA Audit (Round 2)

**Document type:** As-built state report (post-client-review spec)  
**Audit date:** 18 August 2026  
**Repository:** Arihant CRM (`ArihanthCRM_-main`)  
**Method:** Code read on current working tree — not the June 2026 `docs/SLA_ENGINE_AUDIT_REPORT.md`, not README memory, not prior audit claims.

**Rules applied:**
- Every claim cites file path, function/class, and line where possible.
- `NOT FOUND` used where logic was searched but absent.
- States: **BUILT**, **PARTIAL**, **NOT BUILT** (or **NOT FOUND**).
- Descoped items (D1–D13) still in code are flagged under **Undocumented behaviour**.

---

## 1. Executive summary

### B-items (to build / change)

| Count | State |
|-------|--------|
| **1** | BUILT |
| **4** | PARTIAL |
| **7** | NOT BUILT |

- **BUILT:** B12 (Junk requires Lost Reason)
- **PARTIAL:** B1, B3, B4, B11
- **NOT BUILT:** B2, B5, B6, B7, B8, B9, B10

### Descoped items still live (may need removing)

| ID | What the code still does |
|----|--------------------------|
| **D4** | Nurturing auto-sets `temperature: "Warm"` after 24h if label empty — `backend/crm/services/sla_engine.py` ~642–665 |
| **B11 leftover** | Re-engaged auto-moves to `Gone Cold` at 48h — `sla_engine.py` ~1035–1045 |
| **D13 leftover** | Terminal regex matches `advance paid` / `booked` / `dropped` though not UI statuses — `backend/crm/constants/lead_status.py` 26–29 |

### Top 5 handover risks

1. **Half-built Escalation Queue looks done.** Page + `/escalations` API shipped 5 Aug 2026, but columns, visibility, and feeders do not match B3/B4.
2. **Re-engaged 48h still auto-sets Gone Cold** while also creating an admin escalation task — opposite of B11.
3. **Assignment 1h is not the B1 rule.** Clock starts at `created_at_dt`, ignores activity, global round-robin — not assignment-based, not activity-gated, not project-pooled.
4. **No attempt counter (B6), so B7=15 and B8=30 cannot fire.** RNR reminders cap at 3 buckets.
5. **No General Manager role.** Shariff seeded as `rep`. Escalation Queue is `admin` + `manager`. Spec wants Admin + GM Shariff only.

---

## 2. Change log since last audit

Last published in-repo audit: `docs/SLA_ENGINE_AUDIT_REPORT.md` dated **5 June 2026**.

| Commit | Date | What changed | Spec ID | Complete? |
|--------|------|----------------|---------|-----------|
| `2bf398f` | 2026-07-07 | Added Interested / Junk / Unqualified; replaced auto SV status hops with `next_action_date` follow-ups (Visit Completed 3d, SV Follow-up 1 3d, SV Follow-up 2 7d) | D7/D8 (descoped auto-status), Interested SLA | Yes for removing auto-status; **not** B10 2h/72h |
| `41ad75f` | 2026-07-20 | Cap RNR reminders at 3 buckets; one open reminder at a time | undocumented RNR hygiene | Yes |
| `d963f38` | 2026-08-05 | **30m → 1h reassign**; Escalation Queue page + `GET /escalations`; IST task due times; briefly added RNR 48h/15d Admin **ownership transfer** (reverted 12 days later) | B1, B3 | **Incomplete** |
| `329f7eb` | 2026-08-05 | Fix blank New status + fair round-robin counts (`$and` query) | B2-adjacent routing | Yes (global RR only) |
| `a286eda` | 2026-08-05 | Manual CRM creates assign to **creator**, skip `route_new_lead` | B1-adjacent | Yes |
| `c1b237f` | 2026-08-17 | Stop RNR 48h/15d **ownership transfer to Admin**; escalate as tasks only; RNR query matches current status | undocumented (RNR steal bug) | Yes |

### Explicit confirm/deny of believed changes

| Claim | Verdict |
|-------|---------|
| Assignment timer 30 min → 1 hour (B1) | **Confirmed** — `3600` business seconds, flag `sla_flags.new.reassign_1h_at_dt` in `d963f38`. **Not complete vs B1 spec** (see B1 row). |
| Project-pool assignment (B2) | **Denied** — global fewest-open-New round-robin in `assignment_router.py`. `git log -S "project_pool"`: NOT FOUND. |
| Escalation Queue (B3/B4) | **Confirmed page exists** (`d963f38`). **Not complete** vs B3 columns or B4 feeders. |
| Attempt-counter (B6) | **Denied** — no field on lead schema or UI. |

---

## 3. As-built status table

### D — descoped (should not be built)

| ID | Item | State | Actual value in code | File:line | Notes |
|----|------|-------|----------------------|-----------|-------|
| D1 | Hard lock preventing manual `New` | **NOT BUILT** (correct) | Status `<select>` maps all `UI_LEAD_STATUSES` including `New`; no disable | `frontend/src/components/leads/LeadProfileHeader.jsx` 550–562 | Agents may set New |
| D2 | Block leaving Contacted without outcome | **NOT BUILT** (correct) | `logged_outcome` only validated **if present**; leaving Contacted has no outcome check | `backend/crm/services/lead_service.py` 500–518 | Allowed outcomes: `Interested`, `Not Interested`, `Follow-up Scheduled`, `Others` |
| D3 | Outcome-driven Contacted timers | **NOT BUILT** (correct) | Fixed `48h` agent task + `72h` admin task | `backend/crm/services/sla_engine.py` 611–640 | Calendar hours |
| D4 | Nurturing 24h grace → Warm | **BUILT (descoped leftover)** | After 24h calendar with empty temperature → `$set temperature: "Warm"` | `sla_engine.py` 642–665 | Conflicts with on-entry Hot/Warm hard require |
| D5 | Warm 7d + 14d per-lead alert | **NOT BUILT** (correct vs new spec) | Hot **2 calendar days**, Warm **4 calendar days**, stop after 14 days in Nurturing; separate 14d admin batch | `sla_engine.py` 667–706; `nurturing_review.py` 17–31 | Client said keep existing — this **is** existing |
| D6 | Hot 3-day no-interaction alert | **NOT FOUND** | — | Looked: `sla_engine.py` nurturing rule, `nurturing_review.py` | Only Hot 2d follow-up task |
| D7 | Auto `Visit Completed → SV Follow Up 1` at 7d | **NOT BUILT** (correct) | `next_action_date` +3 IST days; no status mutation | `lead_service.py` 614–615; `sla_engine.py` 842–884 | Removed in `2bf398f` |
| D8 | Auto `SV Follow Up 1 → SV Follow Up 2` at 7d | **NOT BUILT** (correct) | SV Follow-up 1: `next_action_date` +3 days; no status hop | `lead_service.py` 618–620; `sla_engine.py` 886–923 | |
| D9 | Gone Cold entry guardrail | **NOT FOUND** | No min follow-ups / RNR attempts on save | `lead_service.py` 596–601 | Any status may become Gone Cold |
| D10 | Future Prospect mandatory-field hard block | **NOT FOUND** | Only stamps `future_prospect_entered_at_dt` | `lead_service.py` 624–625 | Optional fields: `reason_for_purchase`, `possession_requirement` |
| D11 | Future Prospect 60-day review | **NOT BUILT** (correct) | **90 calendar days** check-in; cycle ≥3 → `"Manager review (3 cycles reached)"` to admin | `sla_engine.py` 1126–1173 | 90 days confirmed |
| D12 | Closed Won payment/booking gate | **NOT FOUND** | No payment/booking validation | `lead_service.py` status-change block | |
| D13 | Post-win sub-stages | **NOT BUILT** as UI statuses (correct) | Import maps `advance paid` / `awaiting completion` / `handed over` → `Closed Won`. Terminal regex still matches `advance paid` | `import_status_map.py` 34–37; `lead_status.py` 26–29 | Regex leftover |

### B — to build / change

| ID | Item | State | Actual value in code | File:line | Notes |
|----|------|-------|----------------------|-----------|-------|
| B1 | Lead assignment timer 1h from assignment, no activity | **PARTIAL** | `business_seconds_elapsed(created, now) < 3600` → `reassign_new_lead()`; flag `sla_flags.new.reassign_1h_at_dt`; skips if legacy `reassign_30m_at_dt` set. Start = **`created_at_dt`**. `has_meaningful_contact_since()` **never called** | `sla_engine.py` 476–503; `lead_sla_utils.py` 17–33 | Business hours only. Separate 2h calendar `"Alert Admin"` for intake 10:00–17:00 IST Mon–Sat |
| B2 | Project-based assignment pools | **NOT BUILT** | Global RR: roles `rep\|agent\|sales\|presales`, fewest open New, on-duty today, business hours. Fallback: first `admin` | `assignment_router.py` 74–156 | Agent names in seed only, not mapped to projects |
| B3 | Escalation Queue, Admin+GM only | **PARTIAL** | `/escalation-queue`; `GET /escalations` requires `role in ("admin", "manager")`. Columns: Lead, Reason, Status, Assignee, Age — **not** days in RNR / last note | `App.js` 74–96; `notifications.py` 169–233; `EscalationQueuePage.js` 107–114 | No `general_manager` role. Shariff = `rep` in `seed_db_v2.py` 233 |
| B4 | Queue feeders | **PARTIAL** | **RNR:** 24h/48h/15d → admin escalation tasks. **Re-engaged 48h:** admin alert. **Interested 2 weeks:** NOT FOUND (7d only). **Visit Completed 72h:** NOT FOUND (3d only) | `sla_engine.py` 582–609, 708–741, 842–884, 993–1045 | Queue = all `notification_type=="escalation"` |
| B5 | Agent missed-pickup metric | **NOT FOUND** | Sales Dashboard: total, hot, warm, negotiation, rnr, site_visits, deals_won, deals_lost — no pickup metric | `SalesDashboardPage.js` 59–88; `analytics.py` | `reassign_1h_at_dt` written but not aggregated |
| B6 | Manual attempt counter | **NOT FOUND** | No attempt field on schema or UI | `lead_schemas.py`; `tasks.py` 99–117 | |
| B7 | RNR escalate at 15 attempts | **NOT BUILT** | Time-based: `24h`, `48h`, **`15 * 24` hours (`15d`)** — task `"RNR Lead — 15 Days Uncontacted — High Priority Admin Review"` | `sla_engine.py` 582–609 | See O1 |
| B8 | Gone Cold at 30 attempts, manual | **NOT BUILT** | Manual status pick. SLA: 30 **calendar days** — `"Re-evaluate - re-engage or close"` | `sla_engine.py` 1093–1124 | |
| B9 | Nurture auto Hot/Warm from outcomes | **NOT BUILT** (minor partial) | On enter Nurturing: hard-require Hot or Warm. No 3-neutral downgrade. **Partial:** call summary `intent_level` high/low → Hot/Warm when already Nurturing | `nurture_temperature.py` 71–88; `call_summary.py` ~31–33 | Plus D4 auto-Warm |
| B10 | Visit Completed 2h + 72h escalation | **NOT BUILT** | On entry: `next_action_date` **+3 IST days**. No 2h agent alert, no 72h queue | `lead_service.py` 614–615; `sla_engine.py` 842–884 | |
| B11 | Re-engaged 48h: remove Gone Cold; admin → queue | **PARTIAL** | 12h/24h agent tasks; 48h `"Re-engaged — Admin alert"` to admin **AND** `$set lead_status: "Gone Cold"` | `sla_engine.py` 993–1045 | t0 task on enter: `"Re-engaged lead — qualify intent"` (`lead_service.py` 823–832) |
| B12 | Junk Lost Reason required | **BUILT** | `lost_reason is required when marking lead as lost/junk`; Junk = free text; Unqualified/Closed Lost = picklist | `lead_service.py` 528–542; `lost_reason.py` 5–21 | Junk-specific reasons not yet defined (client owes 2–3) |

### P — phase 2 (deferred)

| ID | Item | State | Actual value in code | File:line | Notes |
|----|------|-------|----------------------|-----------|-------|
| P1 | Auto `New → RNR` after call attempt | **NOT BUILT** | No auto-transition on call note | `whatsapp_service.py` 2363 | Correctly deferred |
| P2 | RNR D+2 customer WA (WATI) | **NOT BUILT** | `"RNR Stale (3 days)"` rule: `send_whatsapp: False` | `reminders.py` 120 | No Interested-button template |
| P3 | 24h pre-visit customer WA (WATI) | **NOT BUILT** as auto-send | Agent task `"Send WA Reminder to Client"`; rep reminder via Gupshup `clara_reminder_1` | `sla_engine.py` 770–798; `reminders.py` 217–258 | Not customer WATI |

---

## Status model

### Canonical UI statuses (18)

`New`, `RNR`, `Contacted`, `Nurturing`, `Interested`, `Site Visit Scheduled`, `Visit Completed`, `SV Follow-up 1`, `SV Follow-up 2`, `Negotiation`, `Gone Cold`, `Future Prospect`, `Re-engaged`, `Junk`, `Unqualified`, `Closed Won`, `Closed Lost`

Sources: `backend/crm/constants/lead_status.py` 5–23; `frontend/src/constants/leadStatus.js` 3–21.

**Spec name drift:** code uses `SV Follow-up 1/2` (hyphen); spec uses spaces.

**Legacy aliases still matched by SLA:**
- `Open` + `original_fw_status=New` → treated as New (`sla_engine.py` 70–81)
- `SV Completed – Follow Up` — matcher exists; rule deprecated and not invoked (`sla_engine.py` 983–991)

### Transition matrix

**NOT FOUND.** Any status → any status. Dropdown lists all `UI_LEAD_STATUSES` (`LeadProfileHeader.jsx` 558–562).

### Terminal statuses (timers stop)

Regex: `closed|booked|advance paid|dropped|junk|unqualified` (`lead_status.py` 26–29).

| Status | SLA timers stop? |
|--------|------------------|
| Junk, Unqualified, Closed Won, Closed Lost | Yes |
| Booked / Advance Paid / Dropped (legacy) | Yes (regex) |
| Gone Cold, Future Prospect, Re-engaged, Negotiation | No — own timers |

On any status change: pending SLA **tasks** cancelled (`lead_service.py` 558–566). `is_rnr` cleared on terminal (604–605). SLA **flags** only partially unset per status.

---

## 4. Full timer inventory

### Business hours

**Mon–Sat 10:00–17:30 IST** (`backend/crm/utils/business_time.py` 12–16). Sunday excluded.

New 2h intake window: **10:00–17:00 IST** Mon–Sat (`sla_engine.py` 150–159).

### Scheduler

- Endpoint: `POST /api/v1/cron/process-slas` (`backend/crm/api/v1/endpoints/cron.py` 36–40)
- Requires: `Authorization: Bearer {CRON_SECRET}`
- Lock: job `process_slas`, TTL 4 minutes (`sla_engine.py` 33–34)
- **Cron expression in repo:** NOT FOUND — `backend/vercel.json` has no crons. Production schedule (DigitalOcean/external): NOT FOUND in repo.

### SLA engine rules (`SLAEngineService.process_all_slas`)

| Trigger | Duration | Clock | Creates | Notifies | File:line |
|---------|----------|-------|---------|----------|-----------|
| New, no 1h flag | `3600s` | **Business** | `reassign_new_lead()` | `"New Lead Assigned"` to new owner | `sla_engine.py` 476–503 |
| New, intake window | `2h` | **Calendar** | Task `"Alert Admin"` `sla_threshold=2h` | Admin, `notification_type=escalation` | `sla_engine.py` 505–533 |
| RNR stay | every `4*3600s` biz, max 3 buckets | **Business** | Task `"RNR Reminder"` `reminder_1..3` | Assigned agent | `sla_engine.py` 535–580 |
| RNR | `24h` / `48h` / `15d` | **Calendar** | `"RNR Escalation — Admin Review Required"` / `"RNR Lead — 15 Days Uncontacted — High Priority Admin Review"` | Admin | `sla_engine.py` 582–609 |
| Contacted | `48h` | Calendar | `"Follow up — log outcome for this lead"` | Agent | `sla_engine.py` 611–640 |
| Contacted | `72h` | Calendar | `"Admin Alert — Contacted lead unactioned 72h"` | Admin | same |
| Nurturing empty label | `24h` | Calendar | `$set temperature: "Warm"` | none | `sla_engine.py` 642–665 |
| Nurturing Hot | `2d` cadence, max 14d in stage | Calendar | `"Hot Lead Follow-up"` | Agent | `sla_engine.py` 667–706 |
| Nurturing Warm | `4d` cadence, max 14d | Calendar | `"Warm Lead Follow-up"` | Agent | same |
| Nurturing 14d+ | `14d` | Calendar | In-app + Brevo email to admin | Admin | `nurturing_review.py`; cron `/nurturing-review` |
| Interested | `7d` | Calendar | Sets `next_action_date` today | none | `sla_engine.py` 708–741 |
| SV Scheduled, no date | immediate | — | `"Missing Visit Date: Update Required"` | Agent | `sla_engine.py` 748–768 |
| SV Scheduled, pre-visit | `24h` before visit | Calendar | `"Send WA Reminder to Client"` | Agent | `sla_engine.py` 770–798 |
| SV Scheduled, post-visit | `24h` after visit | Calendar | `"Post-Visit Follow-up"` | Agent | `sla_engine.py` 800–840 |
| Visit Completed | `3d` | Calendar | `next_action_date` today | none | `sla_engine.py` 842–884 |
| SV Follow-up 1 | `3d` | Calendar | `next_action_date` today | none | `sla_engine.py` 886–923 |
| SV Follow-up 2 | `7d` | Calendar | NAD + admin notif + Brevo email | Admin | `sla_engine.py` 925–981 |
| Negotiation | `48h` / `7d` / `15d` | Calendar | follow-up / stalled / admin review tasks | Agent; 15d Admin | `sla_engine.py` 1047–1091 |
| Gone Cold | `30d` | Calendar | `"Re-evaluate - re-engage or close"` | Agent | `sla_engine.py` 1093–1124 |
| Future Prospect | `90d` repeating | Calendar | `"90-day check-in"`; cycle≥3 manager review | Agent; Admin | `sla_engine.py` 1126–1173 |
| Re-engaged enter | t0 | — | `"Re-engaged lead — qualify intent"` | Agent | `lead_service.py` 823–832 |
| Re-engaged | `12h` / `24h` / `48h` | Calendar | see B11; **48h sets Gone Cold** | Agent; 48h Admin | `sla_engine.py` 993–1045 |

### Related jobs (not main SLA engine)

| Job | Schedule | What | File |
|-----|----------|------|------|
| `POST /api/v1/cron/nurturing-review` | docs say `30 3 * * *` UTC | 14d Nurturing admin batch + email | `nurturing_review.py` |
| `POST /api/v1/cron/process-reminders` | hourly loop exists unwired | Gupshup WA to **reps** + in-app | `reminders.py`, `state.py` 646–656 |
| `reminder_scheduler` | `asyncio.sleep(3600)` | **NOT wired** from `main.py` | `state.py` 646–656 |

### Timer cancel / reset

- Any status change → cancel pending `source=sla` tasks (`lead_service.py` 558–566)
- Move to Contacted → unset New 1h/30m/2h flags (`lead_service.py` 584–593)
- Re-enter RNR → unset `sla_flags.rnr` (`lead_service.py` 577–580)
- `visit_date_dt` change → cancel pre-24h visit task (`lead_service.py` 633–654)
- Complete post-visit SLA task → reset `visit_sla_reference_dt` (`tasks.py` 573–575)
- **New 1h timer NOT reset** on note/call/assignment — only on leaving New or Contacted flag unset

---

## 5. Validation inventory

| Status | Field | Hard block or warning | File:line |
|--------|-------|------------------------|-----------|
| Nurturing | `temperature` Hot/Warm | **Hard block** 400 | `nurture_temperature.py` 76–88 |
| Non-Nurturing | `temperature` | Hard block if set; cleared otherwise | `nurture_temperature.py` 48–60 |
| Nurturing | general note before task | **Hard block** 409 | `tasks.py` 86–97 |
| Contacted | `logged_outcome` | Hard block **only if field sent** | `lead_service.py` 500–518 |
| Contacted | `logged_outcome=Others` | Hard block: reason required | `lead_service.py` 517–518 |
| Unqualified / Closed Lost | `lost_reason` | Hard block; picklist only | `lead_service.py` 528–542; `lost_reason.py` |
| Junk / Dropped | `lost_reason` | Hard block; **free text** | `lead_service.py` 531–534 |
| Site Visit Scheduled | `visit_date_dt` | **Soft warning** only | `LeadProfileHeader.jsx` 660–669 |
| Site Visit Scheduled | assigned sales manager | **NOT FOUND** | — |
| New | manual selection | No lock | `LeadProfileHeader.jsx` 558–562 |
| Closed Won | payment/booking | **NOT FOUND** | — |
| Future Prospect | mandatory fields | **NOT FOUND** | — |
| Gone Cold | 2 FU + 2 RNR | **NOT FOUND** | — |
| Post-visit SLA task | `task_outcome` | Hard block | `tasks.py` 527–535 |

---

## 6. Notifications and task labels

SLA delivery channels: **in-app notification** (SSE bell) + **task** on agent/admin task list. Email via **Brevo** for Nurturing 14d batch and SV Follow-up 2 7d only. **No WhatsApp from SLA engine.**

Default task `reminder_method`: `"default"` (`backend/crm/constants/task.py`).

### Exact SLA task description strings (engine)

| Description (exact) | sla_rule | sla_threshold | Recipient | notification_type |
|---------------------|----------|---------------|-----------|-------------------|
| `"Alert Admin"` | new | 2h | admin | escalation |
| `"RNR Reminder"` | rnr | reminder_1/2/3 | lead owner | action_required |
| `"RNR Escalation — Admin Review Required"` | rnr | 24h, 48h | admin | escalation |
| `"RNR Lead — 15 Days Uncontacted — High Priority Admin Review"` | rnr | 15d | admin | escalation |
| `"Follow up — log outcome for this lead"` | contacted | 48h | owner | action_required |
| `"Admin Alert — Contacted lead unactioned 72h"` | contacted | 72h | admin | escalation |
| `"Hot Lead Follow-up"` / `"Warm Lead Follow-up"` | nurturing | hot_2d / warm_4d | owner | action_required |
| `"Missing Visit Date: Update Required"` | visit_scheduled | missing_date | owner | action_required |
| `"Send WA Reminder to Client"` | visit_scheduled | pre_24h | owner | action_required |
| `"Post-Visit Follow-up"` | visit_scheduled | post_24h | owner | action_required |
| `"Re-engaged — follow up required"` | reengaged | 12h | owner | action_required |
| `"Re-engaged escalation"` | reengaged | 24h | owner | action_required |
| `"Re-engaged — Admin alert"` | reengaged | 48h | admin | escalation |
| `"Re-engaged lead — qualify intent"` | reengaged | t0 | owner | action_required |
| `"Negotiation follow-up"` | negotiation | 48h | owner | action_required |
| `"Negotiation stalled — review deal status"` | negotiation | stalled_7d | owner | action_required |
| `"Negotiation overdue — Admin review required"` | negotiation | admin_15d | admin | escalation |
| `"Re-evaluate - re-engage or close"` | gone_cold | 30d | owner | action_required |
| `"90-day check-in"` | future_prospect | 90d | owner | action_required |
| `"Manager review (3 cycles reached)"` | future_prospect | manager_review | admin | escalation |

Notification title pattern: `"SLA: {description[:50]}"` (`sla_engine.py` 329).

Escalation target resolution: first user with role `admin` and first `manager` by `id` sort (`sla_engine.py` 458–474). Most rules hard-code `escalation_target="admin"`.

Routing notifications: `"New Lead Assigned"` (`assignment_router.py` 207); `"Leads waiting — no active agents"` (226).

### UI task reason copy (`task_enrichment.py` SLA_REASON_BY_KEY)

Includes legacy keys `("new", "30m")` and `("new", "1h")` both saying **"1 hour"** — reflects 30m→1h migration.

---

## 7. Unresolved items (O1–O5)

### O1 — Escalation: time-based or attempt-based?

**Today: time-based only.** RNR at 24h, 48h, 15 **calendar days**. No attempt field.

Options for client:
- (a) Keep time-based (already built; relabel 15d task)
- (b) Add B6 manual counter + B7 at 15 attempts (new work)
- (c) Both — queue when **either** 15 days **or** 15 attempts

### O2 — Manager vs Admin vs General Manager

| Role | Scope / access |
|------|----------------|
| `admin` | Org-wide; Settings; Sales/Marketing Dashboard; Escalation Queue; SLA escalation target; user creation; CSV import |
| `manager` | Org-wide lead scope; Escalation Queue; view-as My Dashboard; **not** Sales Dashboard |
| `rep` | Own My Dashboard pipeline; all leads viewable; no Escalation Queue |
| `agent`/`sales`/`presales` | Assignable in routing regex only |
| `is_platform_operator` | Ops pages (email flag, not role) |

**`general_manager`: NOT FOUND.** Shariff seeded as `rep` (`seed_db_v2.py` 233). B3 "Admin + GM Shariff only" needs new role or allowlist.

### O3 — Site Visit Scheduled hard-block?

**Soft-warn only.** Status saveable without `visit_date_dt`. No separate "assigned sales manager" field. SLA creates `"Missing Visit Date: Update Required"` if date missing.

### O4 — Lost Reason dropdown

Same 11-item picklist for Unqualified and Closed Lost (`lost_reason.py` 5–17). **Not filtered by status.** Junk/Dropped use **free text** at transition (`lost_reason.py` 21).

### O5 — Pipeline drop-off / Lost Reason report

**NOT FOUND** in `analytics.py`. Sales Dashboard has `deals_lost` count only. Export column `"Lost reason"` exists (`lead_export_service.py` 43) — not a funnel report.

---

## 8. Undocumented behaviour

Behaviour in code **not described** in the post-review spec (or descoped but still live):

- Re-engaged → Gone Cold at 48h (B11 says remove)
- D4: Nurturing auto-Warm after 24h empty label
- New 2h `"Alert Admin"` for 10:00–17:00 IST intake window
- RNR 24h/48h/15**d** admin tasks (not 15 attempts)
- RNR 4-business-hour reminders, max 3 per stay
- Interested 7-day follow-up (spec wants 2-week escalation)
- Visit Completed 3-day follow-up (spec wants 2h + 72h)
- Negotiation 48h / 7d / 15d timers
- Gone Cold 30-**day** re-evaluate (not 30 attempts)
- Future Prospect 90d + manager review at 3 cycles
- Nurturing 14d admin email batch
- Nurturing note gate (task required before general note)
- Global fewest-New routing + waiting queue + admin fallback
- Escalation Queue shows all escalation notifications, not only B4 feeders
- Any `manager` sees Escalations; Shariff as `rep` would not
- `has_meaningful_contact_since()` defined but never called
- Deprecated `auto_assign_lead()` still in repo, not SLA-wired
- Stale June audit doc still says 30m reassign, 72h Visit Completed, 7d auto SV hops
- `DELIVERY_READINESS.md` claims Vercel crons; `backend/vercel.json` has none

---

## 9. WhatsApp integration (current state)

| Setting | Value |
|---------|--------|
| BSP (active) | **WATI** when `WHATSAPP_PROVIDER=wati` |
| Default | **`disabled`** (`backend/crm/core/state.py` 73–76) |
| Legacy | Gupshup dead-code; reminder cron still uses Gupshup templates to **reps** |

### WATI templates (agent/inbox, not SLA-automated)

| Template | Use |
|----------|-----|
| `arihant_new_lead_ack_v1` | Auto-ack on new lead (if WATI enabled) |
| `arihant_pricing_v1` | Send pricing |
| `arihant_brochure_v1` | Send brochure |
| `arihant_site_visit_request_ack_v1` | Site visit request ack |
| `arihant_site_visit_completed_v1` | Site visit completed |

Customer-facing send: **disabled** unless env is `wati` + token configured. P2/P3 (RNR D+2 customer WA, pre-visit customer WA) **not built**.

---

## 10. Contradictions and risks

### Can leads reach 15 (B7) or 30 (B8) attempts?

**Not today.** No counter UI or field. RNR creates max **3** reminder tasks (4 business hours apart) — not 15 dial attempts. 15d escalate is **calendar days**. Gone Cold is manual; 30d task is **days**, not attempts.

If B6 is added manually:
- Without enforcement, agents may under-count or inflate counts
- With P2 (RNR D+2 WA) deferred, reaching 15 attempts is weeks of manual logging

### Spec inconsistencies to resolve with client

| Issue | Detail |
|-------|--------|
| B1 start time | Spec: assignment time. Code: `created_at_dt`. After one reassign, flag set — no second 1h clock |
| B3 GM | Spec: Shariff GM. Seed: `rep`. Code: `manager` role for queue |
| B4 Interested | Spec: 2 weeks. Code: 7 days |
| B7 wording | Spec: 15 attempts. Code: 15 **days** task with similar admin wording |
| B9 vs D4 | On-entry Hot/Warm required + 24h auto-Warm if empty — contradictory |
| Status naming | `SV Follow-up` vs `SV Follow Up` |

---

## 11. Recommended client-comment framing

**Do not claim B1–B4 are complete.** Accurate statements:

1. Assignment miss timer is **1 business hour from lead create**, then **global** reassign — not 1h from assignment, not activity-based, not project pools.
2. Escalation Queue exists for **admin + manager**, showing **all** escalation notifications — not the B3 column set, not GM-only, not the four B4 feeders as specified.
3. Attempt thresholds **15 / 30 are not in the product**.
4. Re-engaged **still auto-closes to Gone Cold at 48h** — opposite of B11.
5. Junk Lost Reason **is required** (B12 built); Junk-specific reason list still pending from client.

---

## Appendix A — Key file index

| Area | Primary files |
|------|----------------|
| SLA engine | `backend/crm/services/sla_engine.py` |
| Assignment routing | `backend/crm/services/assignment_router.py` |
| Business hours | `backend/crm/utils/business_time.py` |
| Status constants | `backend/crm/constants/lead_status.py` |
| Lead updates / validation | `backend/crm/services/lead_service.py` |
| Nurture labels | `backend/crm/services/nurture_temperature.py` |
| Lost reasons | `backend/crm/constants/lost_reason.py` |
| Escalation API | `backend/crm/api/v1/endpoints/notifications.py` |
| Escalation UI | `frontend/src/pages/EscalationQueuePage.js` |
| Cron entrypoints | `backend/crm/api/v1/endpoints/cron.py` |
| WhatsApp | `backend/crm/services/whatsapp_service.py` |
| Reminders (parallel) | `backend/crm/api/v1/endpoints/reminders.py` |
| Nurturing 14d batch | `backend/crm/services/nurturing_review.py` |
| Task reason copy | `backend/crm/services/task_enrichment.py` |

---

*End of As-Built SLA Audit (Round 2)*
