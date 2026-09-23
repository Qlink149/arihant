# Arihant CRM — DEEP AS-BUILT SLA AUDIT (Round 3)

**Audit date:** 2026-09-14  
**Branch / tree:** current working tree (`main`, commits through `ea0d0bf`)  
**Spec baseline:** SOP v2.0 + CRM Operations Manual supplement (locked spec in audit brief)  
**Method:** Full re-verification from code — no findings reused from Round 2 without re-checking.

---

## 1. Executive summary

### State counts (74 spec IDs)

| State | Count | Notes |
|-------|------:|-------|
| **BUILT** | 28 | Core timers for Contacted, Negotiation, Gone Cold, Future Prospect, Re-engaged 12h/24h, RNR reminders, project pools (config exists), G3 activity gate, SV status names |
| **PARTIAL** | 32 | Wrong hours/days, wrong copy/trigger, half-wired Escalation Queue, manager role drift, pool config deviations, legacy rules still running |
| **NOT BUILT** | 12 | RNR sprint R2–R7, EQ-specific triggers (I2, NU9, VC4, SF2), VC1/VC2, AS4, attempt system |
| **NOT FOUND** | 2 | LR3 pipeline drop-off report; AS2/AS3 Phase 2 plausibility flags |

### Top 10 handover risks (blast radius)

| # | Risk | State | Evidence |
|---|------|-------|----------|
| 1 | **RNR sprint system (R2–R7) entirely absent** — only time-based 24h/48h/15d + 3 reminder tasks | NOT BUILT | No `log_attempt`, no counters — searched repo; timers at `sla_engine.py:602-629` |
| 2 | **Escalation Queue shows all escalation notifications** — not EQ4 whitelist | PARTIAL | `notifications.py:147-148` filters only `notification_type: "escalation"` |
| 3 | **Re-engaged 48h auto Gone Cold still runs** — spec RE2 removed this | PARTIAL (violates spec) | `sla_engine.py:1055-1065` sets `lead_status: "Gone Cold"` |
| 4 | **Business hours Mon–Sat only** — Sunday excluded (G1/G2) | PARTIAL | `business_time.py:30-31,37-38` `weekday() == 6` → False |
| 5 | **Status change cancels ALL pending SLA tasks** — breaks parallel R8/R9 vs attempt ladder | PARTIAL | `lead_service.py:581-589` cancels all `source: "sla"` pending |
| 6 | **New 2h admin alert without pool-exhaustion gate + wrong copy** | PARTIAL | `sla_engine.py:525-553` task `"Alert Admin"`; no `pool_chain_exhausted` check |
| 7 | **24h auto-Warm still active** — NU2 descoped | PARTIAL (violates spec) | `sla_engine.py:662-685` sets `temperature: "Warm"` |
| 8 | **Production SLA depends on external cron** — not in repo | PARTIAL | `backend/vercel.json` has no `crons`; endpoint `cron.py:36-40` |
| 9 | **Project pools deviate from spec** — Gowtham co-primary; Melange/Vipassana → `roshni@` | PARTIAL | `project_assignment_pools.py:30-76` |
| 10 | **Visit Completed SLA thin** — VC1/VC2/VC4 missing | NOT BUILT | Only 3d `next_action_date` at `sla_engine.py:862-904` |

---

## 2. Change log since 18 Aug 2026

Git range: `git log --since="2026-08-17"` → **19 commits** (2026-08-17 through 2026-09-12).

| Commit | Date | Author | Files (SLA-relevant) | What changed | Spec IDs | Complete? |
|--------|------|--------|----------------------|--------------|----------|-----------|
| `599de55` | 2026-08-17 | rajendra | `RoleBasedTimeInput.jsx`, `DigitalTwinPage.js` | Fix follow-up time picker (12 PM → midnight bug) | — | N/A |
| `746f430` | 2026-08-17 | rajendra | `lead_schemas.py`, `lead_intake_service.py`, `lead_service.py`, `state.py` | Multi-project leads + re-enquiry merge; `project_ids` arrays | PP8 | **Partial** |
| `ca4e921` | 2026-08-17 | rajendra | `DataDnaGrid.jsx`, `leadFilters.js` | Lead Overview white-screen fix | — | N/A |
| `b31072b` | 2026-08-20 | Cursor Agent | `lead_export_service.py` | CSV export NameError fix | — | N/A |
| `24f314d` | 2026-08-20 | cursor[bot] | merge PR #1 | Export fix merge | — | N/A |
| `f31bcf0` | 2026-08-22 | rajendra | `state.py`, `lead_picklists.py`, `seed_db_v2.py` | Webflow project mapping (Chamiers, etc.) | PP8 | **Partial** |
| `0e28e24` | 2026-08-24 | rajendra | `platform_ops.py`, `auth.py` | Multi platform-operator emails | RO1 | N/A |
| `2eb98c6` | 2026-08-24 | rajendra | `platform_ops.py` | Mongo `$in/$regex` fix | — | N/A |
| `80691e5` | 2026-08-29 | rajendra | `lead_intake_service.py` | Re-enquiry null `submission_count` fix | — | N/A |
| `43ad3a0` | 2026-08-29 | rajendra | `lead_intake_service.py` | Re-enquiry timeline diffs | — | N/A |
| **`dc25947`** | **2026-09-04** | **rajendra** | **`sla_engine.py`**, **`project_assignment_pools.py`**, **`roles.py`**, **`assignment_router.py`**, **`lead_sla_utils.py`**, `EscalationQueuePage.js`, `lead_service.py`, `seed_db_v2.py`, 40+ files | **Largest SLA batch:** project pools, New 1h pool reassign + activity gate, RNR 4h reminders (max 3), Escalation Queue page/API, manager role, contacted outcome validation, lost reason picklist | N2–N4, R1, RO2–RO4, EQ1, PP1–PP6, G3, C2–C3, LR1 | **Partial** |
| `416811c` | 2026-09-04 | rajendra | `lead_overview_service.py`, `SiteVisitsPage.js` | Today's leads window; site visit backfill script | — | N/A |
| `b777694` | 2026-09-04 | rajendra | `nudge_pending.py`, `lead_schemas.py` | VC Nudge filter (`nudge_pending`) | — | Undocumented |
| `6c4ea51` | 2026-09-04 | rajendra | `lead_intake_service.py` | Intake null-phone fix | N1 intake | **Partial** |
| `c44a027` | 2026-09-05 | rajendra | WhatsApp attach/send | WA attachments | — | N/A |
| `c1e7246` | 2026-09-08 | rajendra | note @mentions UI | Timeline mentions | — | N/A |
| **`3f9ea32`** | **2026-09-08** | **rajendra** | **`sla_engine.py`** | Cron lock acquire fix (Mongo ms truncation) | 3.1 | **Built** |
| `139df0d` | 2026-09-09 | rajendra | `lead_follow_up.py`, `lead_overview_service.py` | Follow Up Today / Missed Follow-ups mutual exclusion | — | Undocumented |
| `a7e6ad3` | 2026-09-10 | rajendra | `mcube/*`, `cron.py` | MCUBE inbound telephony + `process-mcube-events` cron | G3 (call activity) | **Partial** |
| `ea0d0bf` | 2026-09-12 | rajendra | `VirtualCustomerPage.js` | @mentions in Add Customer notes | — | N/A |

### Part 1 explicit answers

| Question | Answer |
|----------|--------|
| **New SLA rules since 18 Aug?** | Yes: project-pool New 1h reassign (`sla_engine.py:478-523`), RNR 4h reminder buckets max 3 (`sla_engine.py:131-132,569-600`), Escalation Queue API/page (`notifications.py:130-195`, `EscalationQueuePage.js`) |
| **Existing rules changed?** | Yes: pool-based assignment replaces global RR for intake (`assignment_router.py:271+`); activity gate (`lead_sla_utils.py:65-99`); cron lock UUID fix (`sla_engine.py:416-454`) |
| **Migrations / schema?** | `pool_key`, `pool_routing`, `pool_assignment_history` on leads (`assignment_router.py:245-360`); `project_ids[]` multi-project (`746f430`); no sprint attempt fields |
| **Reverted work?** | None found in git log for SLA paths |
| **Committed but unreachable?** | `reminder_scheduler()` in `state.py:761-771` not started in `main.py`; `_process_rule_sv_followup` deprecated not called (`sla_engine.py:1003-1011`); Vercel crons absent from `backend/vercel.json` |

---

## 3. Spec compliance table

Format: `ID | Spec (short) | State | Actual value in code | File:line | Gap description`

### Global

| ID | Spec (short) | State | Actual value in code | File:line | Gap description |
|----|--------------|-------|----------------------|-----------|-----------------|
| G1 | Business hours Mon–Sun 10:00–17:30 IST | PARTIAL | Mon–**Sat** 10:00–17:30; `weekday() != 6` | `business_time.py:13-17,30-31,34-40` | Sunday excluded |
| G2 | New-lead intake window Mon–Sun 10:00–17:30 | PARTIAL | Mon–Sat 10:00–**17:00** IST | `sla_engine.py:151-160` | Sunday excluded; end 17:00 not 17:30 |
| G3 | Activity = call/note/status/outcome; not auto WA/tasks | BUILT | `has_agent_activity_since`: call, note, status, outcome; `_SYSTEM_ACTOR_NAMES` excludes SLA engine | `lead_sla_utils.py:17-23,65-99` | MCUBE call notes count as activity (`G3` partial for telephony) |
| G4 | Status names `SV Follow-up 1` / `SV Follow-up 2` | BUILT | `"SV Follow-up 1"`, `"SV Follow-up 2"` | `lead_status.py:13-14` | Matches spec hyphen + lowercase u |
| G5 | Terminal statuses stop timers | PARTIAL | Regex `closed\|booked\|advance paid\|dropped\|junk\|unqualified` | `lead_status.py:26-28,43-45` | `Closed Won`/`Closed Lost` match via `closed`; `Dropped` in regex but not in UI list |

### Roles

| ID | Spec (short) | State | Actual value in code | File:line | Gap description |
|----|--------------|-------|----------------------|-----------|-----------------|
| RO1 | Admin — full access, all escalation alerts | BUILT | Role `"admin"`; first-match admin for escalations | `user_schemas.py:12`, `sla_engine.py:461-465` | Multiple admins seeded; engine picks `sort=[("id",1)]` first |
| RO2 | Manager — Escalation Queue only; no dashboard/settings/other pipelines | PARTIAL | Role `"manager"` exists; Escalation access yes; **rep switcher** allowed | `roles.py:8-15`, `MyDashboardPage.js:132-135`, `App.js:91-94` | Manager can view other reps' dashboards via switcher |
| RO3 | Agent — own task list; no Escalation Queue | PARTIAL | Role is `"rep"` not `"agent"`; EQ blocked for rep | `user_schemas.py:12`, `App.js:116-117` | Schema uses `rep`; routing regex accepts `agent` in assignment only |
| RO4 | Report every role/permission check | PARTIAL | See Section 6 matrix | `roles.py`, `App.js`, endpoint guards | `general_manager` gets EQ access — not in spec |

### New

| ID | Spec (short) | State | Actual value in code | File:line | Gap description |
|----|--------------|-------|----------------------|-----------|-----------------|
| N1 | Auto-set New on creation; agents may select manually | BUILT | Intake sets `"lead_status": "New"`; UI dropdown unrestricted | `lead_intake_service.py:746`, `LeadProfileHeader.jsx:548-562` | No lock on manual New |
| N2 | 1 business hour timer from creation | BUILT | `3600` business seconds from `assigned_at_dt` or `created_at_dt` | `sla_engine.py:501` | Matches spec |
| N3 | Reassign only if no activity (G3) | BUILT | `has_agent_activity_since(lead, assigned)` → skip | `sla_engine.py:503-504` | Does not reassign on elapsed time alone |
| N4 | Reassign to next agent in project pool | BUILT | `reassign_new_lead_in_pool()`; requires `pool_routing: True` | `sla_engine.py:505`, `assignment_router.py:271` | Non-pool leads skip 1h reassign |
| N5 | Admin alert only if primary+fallback fail; specific copy | PARTIAL | Task `"Alert Admin"` at **2 calendar hours**; no pool exhaustion check | `sla_engine.py:525-553` | Wrong trigger, wrong copy, names no rep |

### RNR — sprint system

| ID | Spec (short) | State | Actual value in code | File:line | Gap description |
|----|--------------|-------|----------------------|-----------|-----------------|
| R1 | Reminder every 4 business hours, max 3, one open | BUILT | `_RNR_REMINDER_MAX_BUCKETS = 3`; `"RNR Reminder"`; open-query dedupe | `sla_engine.py:131-132,569-600,582-587` | Matches time-based reminder spec |
| R2 | Attempt counter — Log Attempt +1 | NOT BUILT | — | searched `log_attempt`, `rnr_attempt` — **NOT FOUND** | No field, API, or UI |
| R3 | Discrete attempt events with system timestamp | NOT BUILT | — | **NOT FOUND** | Would need event array |
| R4 | Dual counters per-rep 1–6 / global 1–18 | NOT BUILT | — | **NOT FOUND** | Only `sla_flags.rnr.reminder_{n}_at_dt` |
| R5 | Sprint 1: 6 attempts → pool transfer + Manager notify | NOT BUILT | — | **NOT FOUND** | No attempt tracking |
| R6 | Sprint 2: 12 total → Escalation Queue | NOT BUILT | — | **NOT FOUND** | 24h/48h admin tasks exist but not attempt-based |
| R7 | Sprint 3: 18 total → Admin popup summary | NOT BUILT | — | **NOT FOUND** | No popup UI |
| R8 | 15 calendar days in RNR → high-priority Admin task | PARTIAL | `(15 * 24, "15d", "RNR Lead — 15 Days Uncontacted — High Priority Admin Review", "admin")` | `sla_engine.py:605,614` | Exists but same ladder as 24h/48h; not isolated parallel track |
| R9 | 30 calendar days in RNR → auto Gone Cold | NOT FOUND | 30d rule is **Gone Cold re-evaluate** only | `sla_engine.py:1113-1144` | No RNR 30d auto-status |
| R10 | R8/R9 parallel to attempt ladder | NOT BUILT | N/A until R2–R7 built | — | Global task cancel on status change blocks parallel design |
| R11 | D+2 customer WhatsApp removed Phase 1 | BUILT | No SLA rule sends D+2 WA to RNR customers | `sla_engine.py:555-629` | Legacy `reminders.py:120` has `rnr_stale` 3d with `send_whatsapp: False` |

### Contacted

| ID | Spec (short) | State | Actual value in code | File:line | Gap description |
|----|--------------|-------|----------------------|-----------|-----------------|
| C1 | No hard block leaving Contacted without outcome | BUILT | Status change allowed without `logged_outcome` | `LeadProfileHeader.jsx:548-562` | No backend block on status alone |
| C2 | Outcome picker 6 options | PARTIAL | 4 values: `Interested`, `Not Interested`, `Follow-up Scheduled`, `Others` | `lead_service.py:528-533`, `LeadProfileHeader.jsx:62` | Missing `Needs Time`, `Call Back Later` |
| C3 | Others requires mandatory note | BUILT | HTTP 400 if `Others` without `logged_outcome_reason` | `lead_service.py:540-541`, `LeadProfileHeader.jsx:272-276` | Matches |
| C4 | 48h agent task, calendar hours | BUILT | `(48, "48h", "Follow up — log outcome for this lead", ...)` | `sla_engine.py:632-633` | Calendar `timedelta(hours=48)` |
| C5 | 72h Admin alert, calendar hours | BUILT | `(72, "72h", "Admin Alert — Contacted lead unactioned 72h", ..., "admin")` | `sla_engine.py:634,656` | Escalation notification created |
| C6 | Customer WA reply qualifies for Contacted | NOT FOUND | WA inbound stores messages; no auto-status → Contacted | `whatsapp_service.py:1650+` | Guidance only; not enforced in SLA |

### Nurturing

| ID | Spec (short) | State | Actual value in code | File:line | Gap description |
|----|--------------|-------|----------------------|-----------|-----------------|
| NU1 | Hot/Warm hard-required on entry | BUILT | HTTP 400 `"Nurture label (Hot or Warm) is required"` | `nurture_temperature.py:76-78,84-86` | Backend enforced; UI picker on status change |
| NU2 | 24h auto-default-to-Warm REMOVED | PARTIAL (violates) | Auto-sets `temperature: "Warm"` after 24h no label | `sla_engine.py:662-685` | **Still runs** — spec deleted this |
| NU3 | Hot cadence 2 calendar days | BUILT | `timedelta(days=2)` for `temp == "hot"` | `sla_engine.py:700,707` | `"Hot Lead Follow-up"` task |
| NU4 | Warm cadence 4 calendar days | BUILT | `timedelta(days=4)` for warm | `sla_engine.py:700,707` | `"Warm Lead Follow-up"` task |
| NU5 | Both stop after 14 days in Nurturing | BUILT | `if (now_dt - entered) > timedelta(days=14): continue` | `sla_engine.py:693-694` | Matches |
| NU6 | 14-day admin email digest | BUILT | `process_nurturing_review()`; Brevo email + in-app | `nurturing_review.py:17-103`, `cron.py:43-48` | Separate daily cron |
| NU7 | Auto-upgrade to Hot after positive outcome/inbound | NOT FOUND | — | grep backend — **NOT FOUND** | No auto Hot logic |
| NU8 | Auto-downgrade Warm after 3 neutral outcomes | NOT FOUND | — | **NOT FOUND** | Neutral outcomes not defined in code |
| NU9 | Hot 14d no status change → Escalation Queue | NOT BUILT | 14d batch is admin digest only, not EQ | `nurturing_review.py:64-73` | `notification_type: "action_required"` not `"escalation"` |

### Interested / Site Visit / Visit Completed / SV Follow-up

| ID | Spec (short) | State | Actual value in code | File:line | Gap description |
|----|--------------|-------|----------------------|-----------|-----------------|
| I1 | 7 days → follow-up task | PARTIAL | Sets `next_action_date` to today IST (Follow-up Today queue) | `sla_engine.py:728-761`, `lead_service.py:643-644` | Task string implicit via queue, not explicit SLA task title |
| I2 | 2 weeks no status change → Escalation Queue | NOT BUILT | — | **NOT FOUND** | No interested 14d escalation |
| SV1 | Field renamed Assign Sales Agent | PARTIAL | Labels: `"Assign"`, `"Assigned Sales Manager"`, `"Sales owner"` | `LeadProfileHeader.jsx:567`, `VirtualCustomerPage.js:1864` | No literal `"Assign Sales Agent"` |
| SV2 | Instant notification to assigned Sales Agent | PARTIAL | Assignee change logs timeline + `log_lead_event`; no dedicated SV instant notif | `lead_service.py:684-697,871-881` | Assignment notification not SV-specific |
| SV3 | Visit date hard block or soft warn | PARTIAL | SLA task `"Missing Visit Date: Update Required"` if no date; no save block | `sla_engine.py:768-788` | Soft — status change not blocked |
| SV4 | 24h before visit → agent task (not customer WA) | PARTIAL | Task `"Send WA Reminder to Client"` | `sla_engine.py:807-818` | **Wrong description** — implies customer WA; spec says agent task only |
| VC1 | 2-hour alert if feedback not logged | NOT FOUND | — | grep `2.?hour`, `visit_completed` — **NOT FOUND** | |
| VC2 | 24h after visit → auto reminder Post-visit follow-up | PARTIAL | Post-visit task on **Site Visit Scheduled** status 24h after `visit_date_dt` | `sla_engine.py:820-860` | Fires while still in SV Scheduled, not Visit Completed |
| VC3 | 3 days → next-action prompt | BUILT | `next_action_date` +3d on entry; cron backup 3d | `lead_service.py:641-642`, `sla_engine.py:862-904` | |
| VC4 | 72h no action → Escalation Queue | NOT BUILT | — | **NOT FOUND** | |
| VC5 | NO auto status change to SV Follow-up 1 | BUILT | No auto transition found | `lead_service.py` status handlers | Manual only |
| SF1 | NO auto SV Follow-up 1 → 2 | BUILT | No auto transition | `lead_service.py:645-650` | Manual only |
| SF2 | SV Follow-up 1/2 task pending 72h → Escalation Queue | NOT BUILT | SV1: 3d backup; SV2: 7d admin alert | `sla_engine.py:906-1001` | No 72h EQ trigger |

### Remaining statuses

| ID | Spec (short) | State | Actual value in code | File:line | Gap description |
|----|--------------|-------|----------------------|-----------|-----------------|
| NG1 | Negotiation 48h / 7d / 15d ladder | BUILT | `48h`, `stalled_7d`, `admin_15d` with escalation on 15d | `sla_engine.py:1070-1111` | Client signed off — intact |
| GC1 | 30-day re-evaluate task | BUILT | `"Re-evaluate - re-engage or close"`; `timedelta(days=30)` | `sla_engine.py:1113-1144` | |
| GC2 | Entry guardrails work instruction only | BUILT | No backend guard on Gone Cold entry | `lead_service.py` — no GC guard | Matches spec |
| FP1 | 90-day repeating review | BUILT | `"90-day check-in"`; `timedelta(days=90)`; `fp_cycle_count` | `sla_engine.py:1158-1177` | |
| FP2 | Admin review at 3 cycles | PARTIAL | Task `"Manager review (3 cycles reached)"` but `escalation_target="admin"` | `sla_engine.py:1179-1193` | Title says Manager; routes to admin |
| FP3 | Location/budget/unit NOT hard-required | BUILT | No required-field validation for those on FP | `lead_service.py` | |
| RE1 | Re-engaged 12h / 24h / 48h tasks | BUILT | `(12, "12h", ...)`, `(24, "24h", ...)`, `(48, "48h", ...)` | `sla_engine.py:1017-1054` | Plus T+0 `"Re-engaged lead — qualify intent"` on entry `lead_service.py:860-868` |
| RE2 | 48h = Admin alert ONLY; no auto Gone Cold | PARTIAL (violates) | 48h task + **`lead_status: "Gone Cold"` mutation** | `sla_engine.py:1055-1065` | Auto Gone Cold must be removed |
| J1 | Junk requires Lost Reason | BUILT | HTTP 400 `"lost_reason is required when marking lead as lost/junk"` | `lead_service.py:554-557` | |
| J2 | Junk same dropdown as Unqualified + 4 extras | PARTIAL | Junk: **free text**; Unqualified/Closed Lost: enum picklist | `lost_reason.py:19-21`, `LeadProfileHeader.jsx:834-855` | Not shared dropdown |
| CW1 | Single Closed Won; no payment gate | BUILT | `"Closed Won"` in UI; no booking gate in code | `lead_status.py:21` | |
| LR1 | Lost Reason mandatory Unqualified/Closed Lost | BUILT | Enum validation via `normalize_lost_reason` | `lead_service.py:558-565`, `lost_reason.py:34-39` | |
| LR2 | Applies-to column agent reference only | BUILT | No status filter on lost reason options | `lost_reason.py:5-17` | Confirmed no filtering |
| LR3 | Pipeline drop-off report | NOT FOUND | — | searched analytics, reports — **NOT FOUND** | |

### Escalation Queue

| ID | Spec (short) | State | Actual value in code | File:line | Gap description |
|----|--------------|-------|----------------------|-----------|-----------------|
| EQ1 | Visible Admin + Manager; not Agent | PARTIAL | `ESCALATION_ROLES = {admin, manager, general_manager}` | `roles.py:15-26`, `App.js:99-118` | GM included; spec says Manager not GM |
| EQ2 | Separate from normal task list | BUILT | Dedicated page `/escalation-queue`; API `/escalations` | `EscalationQueuePage.js`, `notifications.py:130` | |
| EQ3 | Columns per spec | PARTIAL | Lead, Reason, Status, Assignee, Project, Age | `EscalationQueuePage.js:126-132` | Missing: Days in Status, Total RNR Attempts, Last Note |
| EQ4 | 10 triggers feed queue | PARTIAL | See trigger table below | `sla_engine.py`, `notifications.py:147` | Most EQ triggers NOT BUILT |
| EQ5 | Queue shows only EQ triggers | PARTIAL | All `notification_type: "escalation"` | `notifications.py:147-148` | Includes RNR 24h/48h/15d, New 2h, Contacted 72h, Negotiation 15d, Re-engaged 48h, FP review |
| EQ6 | Exit: manual / terminal / Gone Cold; never time alone | PARTIAL | Mark read = resolve UI; no auto-exit on time | `EscalationQueuePage.js:212` | Auto Gone Cold on RE2 violates spirit |

**EQ4 trigger existence today:**

| Trigger | Feeds EQ? | Evidence |
|---------|-----------|----------|
| RNR Sprint 1/2/3 | NO | Not built |
| RNR 15 days | YES (as escalation notif) | `sla_engine.py:605,624` |
| New lead unactioned | YES | `sla_engine.py:549` |
| Nurturing Hot 14d | NO | Digest only `nurturing_review.py` |
| Visit Completed 72h | NO | Not built |
| SV Follow-up 72h | NO | Not built |
| Negotiation 15d | YES | `sla_engine.py:1073,1107` |
| Re-engaged 48h | YES | `sla_engine.py:1020,1050` |

### Agent Scorecard

| ID | Spec (short) | State | Actual value in code | File:line | Gap description |
|----|--------------|-------|----------------------|-----------|-----------------|
| AS1 | Existing metrics | BUILT | total, hot, warm, negotiation, rnr, site_visits, deals_won, deals_lost | `SalesDashboardPage.js:69-78,396-407` | Admin-only page |
| AS2 | Phase 2: missed pickup, RNR rate, avg attempts | NOT FOUND | — | **NOT FOUND** | |
| AS3 | Phase 2 plausibility flags | NOT FOUND | — | **NOT FOUND** | |
| AS4 | Per-agent site-visit count with date filters | PARTIAL | `site_visit_count` on lead; filter in search | `lead_search.py:344`, `DataDnaGrid.jsx:188` | No dedicated scorecard widget with 24h/weekly/monthly/quarterly |

### Project Assignment Pools

| ID | Spec (short) | State | Actual value in code | File:line | Gap description |
|----|--------------|-------|----------------------|-----------|-----------------|
| PP1 | Reserve 16 — Anusha primary; fallback chain | PARTIAL | Primary `[anusha@, gowtham@]` RR; fallback Narendran→Malathy→jigar→Anantharaman | `project_assignment_pools.py:30-40` | Gowtham co-primary; spec Anusha only |
| PP2 | Krishna — Harish + Malathy RR | BUILT | `"krsna"`: `[harish@, malathy@]` RR | `project_assignment_pools.py:42-47` | |
| PP3 | Mira — Shariff + Harish RR | BUILT | `"mira"`: `[shariff@, harish@]` RR | `project_assignment_pools.py:49-54` | |
| PP4 | Vivriti — Anusha primary; Narendran+Malathy fallback RR | BUILT | fixed primary; `fallback_mode: "rr_list"` | `project_assignment_pools.py:56-61` | |
| PP5 | Melange — all leads to Admin | PARTIAL | Fixed `roshni@`; `escalate: False` | `project_assignment_pools.py:63-68` | Roshini admin user, not role-based |
| PP6 | Vipassana — all leads to Admin | PARTIAL | Fixed `roshni@`; `escalate: False` | `project_assignment_pools.py:70-75` | Same |
| PP7 | Sprint 3 Krishna/Mira manual Admin | NOT BUILT | No sprint system | — | |
| PP8 | Project field + mapping | BUILT | `project`, `project_id`, `project_ids`, `pool_key`; `resolve_lead_project_key` | `state.py:195-246`, `assignment_router.py` | |
| PP9 | Seeded users + Gowtham | BUILT | 11 users in `USER_DEFS`; Gowtham `gowtham@arihants.co.in` role `"rep"` | `seed_db_v2.py:232-244` | Manager role not in main seed (E2E only) |

**Seeded users (`seed_db_v2.py:232-244`):**

| Name | Email | Role | Pool (by email) |
|------|-------|------|-----------------|
| Narendran S | narendran@ | rep | Reserve-16 fallback |
| Piyush | piyush@ | rep | — |
| Malathy | malathy@ | rep | Reserve-16 / Krsna / Vivriti |
| Anusha Omprakash | anusha@ | rep | Reserve-16 / Vivriti primary |
| jigar | jigar@ | rep | Reserve-16 fallback |
| shariff | shariff@ | general_manager | Mira primary |
| Harish Marlecha | harish@ | admin | Krsna / Mira primary |
| Gowtham j | gowtham@ | rep | Reserve-16 primary / default |
| Roshini | roshni@ | admin | Melange / Vipassana |
| Anantharaman | anantharaman@ | rep | Reserve-16 fallback |
| Yogansh | yogansh@claraai.tech | admin | — |

**Gowtham:** still exists, role `"rep"`, in Reserve-16 and default pool primaries (`project_assignment_pools.py:31,78`).

---

## 4. Complete timer inventory

Clock types: **BUS** = business seconds; **CAL** = calendar elapsed.

| Rule | Trigger condition | Duration | Clock | Mutation | Task string | Recipient | File:line |
|------|-------------------|----------|-------|----------|-------------|-----------|-----------|
| New pool reassign | `pool_routing: True`, no activity, pool escalates | 3600 sec | BUS | Reassign via pool | — | next pool agent | `sla_engine.py:481-523` |
| New admin alert | `created_at_dt` + intake window | 2 hours | CAL | Task + escalation notif | `"Alert Admin"` | admin | `sla_engine.py:525-553` |
| RNR reminder 1–3 | In RNR, business hours, bucket N | 4h × N | BUS | Task | `"RNR Reminder"` | assigned agent | `sla_engine.py:569-600` |
| RNR escalate 24h | `rnr_entered_at_dt` | 24 hours | CAL | Task + escalation | `"RNR Escalation — Admin Review Required"` | admin | `sla_engine.py:602-629` |
| RNR escalate 48h | same | 48 hours | CAL | Task + escalation | same | admin | `sla_engine.py:602-629` |
| RNR escalate 15d | same | 15×24 hours | CAL | Task + escalation priority `"high"` | `"RNR Lead — 15 Days Uncontacted — High Priority Admin Review"` | admin | `sla_engine.py:605,614-628` |
| Contacted 48h | `contacted_at_dt`, no outcome logged | 48 hours | CAL | Task | `"Follow up — log outcome for this lead"` | assigned agent | `sla_engine.py:632-660` |
| Contacted 72h | same | 72 hours | CAL | Task + escalation | `"Admin Alert — Contacted lead unactioned 72h"` | admin | `sla_engine.py:634,656` |
| Nurturing auto-Warm | No temperature 24h | 24 hours | CAL | Set `temperature: "Warm"` | — | — | `sla_engine.py:662-685` |
| Nurturing Hot follow-up | Hot, within 14d window | 2 days since last | CAL | Task | `"Hot Lead Follow-up"` | assigned agent | `sla_engine.py:700-726` |
| Nurturing Warm follow-up | Warm, within 14d | 4 days since last | CAL | Task | `"Warm Lead Follow-up"` | assigned agent | `sla_engine.py:700-726` |
| Nurturing 14d admin batch | `nurture_entered_at_dt` ≥14d | 14 days | CAL | In-app + email | `"{count} leads stuck in Nurturing — 14+ days"` | admin | `nurturing_review.py:17-103` |
| Interested 7d | `interested_entered_at_dt` | 7 days | CAL | Set `next_action_date` today | — (queue surfacing) | — | `sla_engine.py:728-761` |
| SV missing date | Site Visit Scheduled, no `visit_date_dt` | immediate | — | Task | `"Missing Visit Date: Update Required"` | assigned agent | `sla_engine.py:768-788` |
| SV pre-24h | Visit within 24h | 24 hours before visit | CAL | Task | `"Send WA Reminder to Client"` | assigned agent | `sla_engine.py:790-818` |
| SV post-24h | 24h after `visit_date_dt` | 24 hours | CAL | Task | `"Post-Visit Follow-up"` | assigned agent | `sla_engine.py:820-860` |
| Visit Completed 3d | Visit Completed | 3 days | CAL | Set `next_action_date` | — | — | `sla_engine.py:862-904` |
| SV Follow-up 1 3d | SV Follow-up 1 entered | 3 days | CAL | Set `next_action_date` | — | — | `sla_engine.py:906-943` |
| SV Follow-up 2 7d | SV Follow-up 2 entered | 7 days | CAL | `next_action_date` + admin notif + email | `"SV Follow-up 2 — 7-day follow-up due"` | admin | `sla_engine.py:945-1001` |
| Re-engaged T+0 | Status → Re-engaged | immediate | — | Task (on status change) | `"Re-engaged lead — qualify intent"` | assigned agent | `lead_service.py:860-868` |
| Re-engaged 12h/24h/48h | `reengaged_at_dt` | 12/24/48 hours | CAL | Task; 48h + escalation; **48h auto Gone Cold** | `"Re-engaged — follow up required"` / `"Re-engaged escalation"` / `"Re-engaged — Admin alert"` | agent / admin | `sla_engine.py:1017-1065` |
| Negotiation 48h/7d/15d | `negotiation_entered_at_dt` | 48h / 7d / 15d | CAL | Tasks; 15d escalation | `"Negotiation follow-up"` / `"Negotiation stalled — review deal status"` / `"Negotiation overdue — Admin review required"` | agent / admin | `sla_engine.py:1070-1111` |
| Gone Cold 30d | `gone_cold_entered_at_dt` | 30 days | CAL | Task | `"Re-evaluate - re-engage or close"` | assigned agent | `sla_engine.py:1113-1144` |
| Future Prospect 90d | Last check-in or entry | 90 days | CAL | Task | `"90-day check-in"` | assigned agent | `sla_engine.py:1158-1177` |
| Future Prospect cycle 3 | `fp_cycle_count >= 3` | at 90d cycle | CAL | Task + escalation | `"Manager review (3 cycles reached)"` | admin | `sla_engine.py:1179-1193` |

**On status entry (event-driven, not cron):**

| Rule | Trigger | Mutation | File:line |
|------|---------|----------|-----------|
| Interested 7d N/A | → Interested | `next_action_date` +7d IST | `lead_service.py:643-644` |
| Visit Completed 3d | → Visit Completed | `next_action_date` +3d IST | `lead_service.py:641-642` |
| SV Follow-up 1 | → SV Follow-up 1 | `next_action_date` +3d | `lead_service.py:645-647` |
| SV Follow-up 2 | → SV Follow-up 2 | `next_action_date` +7d | `lead_service.py:648-650` |

---

## 5. Complete validation inventory

| Status | Field | Hard block / soft warn / none | Error code / behaviour | File:line |
|--------|-------|--------------------------------|------------------------|-----------|
| Contacted | `logged_outcome` | Hard (when setting outcome) | HTTP 400 invalid enum | `lead_service.py:528-538` |
| Contacted | `logged_outcome_reason` | Hard when outcome=`Others` | HTTP 400 required | `lead_service.py:540-541` |
| Nurturing | `temperature` | Hard on entry | HTTP 400 Hot/Warm required | `nurture_temperature.py:76-86` |
| Nurturing | `temperature` on non-Nurturing | Hard | HTTP 400 not allowed | `nurture_temperature.py:55-58` |
| Junk / Unqualified / Closed Lost | `lost_reason` | Hard | HTTP 400 required | `lead_service.py:554-557` |
| Unqualified / Closed Lost | `lost_reason` | Hard — must be picklist | HTTP 400 invalid picklist | `lead_service.py:558-565` |
| Junk | `lost_reason` | Hard — free text allowed | HTTP 400 if empty | `lead_service.py:554-557`, `lost_reason.py:21` |
| Site Visit Scheduled | `visit_date_dt` | Soft (SLA task only) | Task not save block | `sla_engine.py:768-788` |
| Any status change | — | Cancels all pending SLA tasks | DB update | `lead_service.py:581-589` |
| Nurturing entry | follow-up task | Soft gate on notes | Requires task before notes | `lead_service.py:739-747`, `tasks.py:98-99` |
| Create lead Nurturing | `temperature` | Hard (UI + backend) | toast / HTTP 400 | `VirtualCustomerPage.js:998-1000`, `nurture_temperature.py` |
| Future Prospect / Gone Cold | location/budget/unit | None | No enforcement | — |

---

## 6. Role and permission matrix

| Capability | admin | manager | general_manager | rep | Enforced where |
|------------|:-----:|:-------:|:---------------:|:---:|----------------|
| Escalation Queue | ✓ | ✓ | ✓ | ✗ | `roles.py:25-26`, `App.js:116-117` |
| Sales Dashboard | ✓ | ✗ | ✗ | ✗ | `App.js:68-70,174` |
| Marketing Dashboard | ✓ | ✗ | ✗ | ✗ | `DashboardLayout.js:84-101` |
| Settings | ✓ | ✗ | ✗ | ✗ | `App.js:68-70` |
| Site Visits page | ✓ | ✓ | ✗ | ✗ | `App.js:189-197` OrgEditorRoute |
| Rep switcher (view other pipelines) | ✓ | ✓ | ✗ | ✗ | `MyDashboardPage.js:132-135` |
| Assign/reassign any lead | ✓ | ✓ | ✗ | owner only | `LeadProfileHeader.jsx:106-108` |
| Nudge leads | ✓ | ✓ | ✗ | ✗ | `VirtualCustomerPage.js:886-889` |
| CSV export | ✓ | ✗ | ✗ | ✗ | `lead_export_service.py:74-75` |
| CSV import | ✓ | ✗ | ✗ | ✗ | `leads.py:769-770` |
| Bulk lead update | ✓ | ✓ | ✗ | ✗ | `leads.py:504,562,593,673` |
| My Dashboard (own pipeline) | ✓ | ✓ | ✓ | ✓ | `my_dashboard.py:114-117` |
| WA inbox org-wide | ✓ | ✓ | ✗ | own | `whatsapp_service.py:1953` |
| Analytics org-wide | ✓ | ✓ | ✗ | ✗ | `analytics.py:536` |
| Platform ops | platform operator | ✗ | ✗ | ✗ | `platform_ops.py` |
| SLA escalation recipient (admin) | ✓ (first id) | loaded but rarely targeted | ✗ | ✗ | `sla_engine.py:461-476` |
| Reminder rules admin | ✓ | ✗ | ✗ | ✗ | `reminders.py:39` |

**Note:** Spec RO2 says Manager gets EQ only — current manager also gets rep switcher, Site Visits, bulk update, nudge, analytics (`PARTIAL` vs RO2).

---

## 7. Engineering deep dive

### 3.1 Scheduler and execution

**Cron entrypoints** (`cron.py`):

| Route | Handler | Auth |
|-------|---------|------|
| `POST /api/v1/cron/process-slas` | `SLAEngineService().process_all_slas()` | Bearer `CRON_SECRET` |
| `POST /api/v1/cron/nurturing-review` | `process_nurturing_review()` + email queue | same |
| `POST /api/v1/cron/process-reminders` | `process_reminders()` | same |
| `POST /api/v1/cron/backfill-lead-stats` | `backfill_lead_stats()` | same |
| `POST /api/v1/cron/process-mcube-events` | MCUBE batch | same |

Mounted at `/api` → full path `POST /api/v1/cron/process-slas` (`main.py`).

**Lock mechanism:** Mongo `cron_locks` collection; job `"process_slas"`; TTL **4 minutes**; owner UUID token; release in `finally` via `delete_one` (`sla_engine.py:34-35,416-454,1309-1311`). TTL index on `expires_at` with `expireAfterSeconds=0` (`state.py:455-465`).

**Overlap:** Second concurrent call returns `{"skipped": True, "reason": "lock_held"}` (`sla_engine.py:1257-1259`).

**6-hour downtime:** Rules are threshold-based with idempotent flags — on recovery, crossed thresholds fire once; **RNR reminder intermediate buckets are NOT backfilled** (bucket = `elapsed_biz // 14400`, capped at 3).

**Idempotency:** `dedupe_key` unique sparse index on tasks (`state.py:318`); `_flag_not_set` prevents re-fire; bulk_write continues on duplicate errors.

**Production schedule:** **NOT in repo.** `backend/vercel.json` contains only `installCommand`. `docs/DELIVERY_READINESS.md:24` documents expected external crons: `process-slas` every minute, `nurturing-review` at `30 3 * * *` UTC.

### 3.2 Flags and state hygiene

**`sla_flags.new`:** `pool_chain_exhausted_at_dt`, `last_pool_reassign_at_dt`, `alert_admin_2h_at_dt` (written); legacy `reassign_30m_at_dt`, `reassign_1h_at_dt` cleared on Contacted only (`lead_service.py:610-614`) — never written by engine.

**`sla_flags.rnr`:** `reminder_{1,2,3}_at_dt`, `escalate_{24h,48h,15d}_at_dt`; entire object **unset** on RNR re-entry (`lead_service.py:597-603`).

**`sla_flags.contacted`:** `48h_at_dt`, `72h_at_dt`; cancelled when outcome logged (`lead_service.py:543-549`).

**`sla_flags.nurturing`:** `temperature_warm_at_dt`, `{hot,warm}_followup_{N}_at_dt`, `{hot,warm}_last_task_created_at_dt`, `{hot,warm}_cycle`, `admin_review_14d_at_dt`.

**`sla_flags.interested`:** `7d_at_dt`.

**`sla_flags.visit_scheduled`:** `missing_date_at_dt`, `pre_24h_at_dt`, `post_24h_at_dt`; `pre_24h` unset on visit reschedule (`lead_service.py:678-680`).

**`sla_flags.visit_completed`:** `3d_at_dt`.

**`sla_flags.sv_followup_1`:** `3d_at_dt`; legacy `7d_at_dt` read-only guard (`sla_engine.py:920`).

**`sla_flags.sv_followup_2`:** `admin_7d_at_dt`; legacy `admin_20d_at_dt` read-only guard (`sla_engine.py:959`).

**`sla_flags.reengaged`:** `12h_at_dt`, `24h_at_dt`, `48h_at_dt`, `gone_cold_48h_at_dt`; unset on re-entry (`lead_service.py:655-657`).

**`sla_flags.negotiation`:** `followup_48h_at_dt`, `stalled_7d_at_dt`, `admin_15d_at_dt`.

**`sla_flags.gone_cold`:** `reevaluate_30d_at_dt`; unset on re-entry (`lead_service.py:621-623`).

**`sla_flags.future_prospect`:** `checkin_90d_{cycle}_at_dt`, `manager_review_{cycle}_at_dt`.

**Written but never read:** none critical (legacy keys are read-only guards).

**Read but never written:** `reassign_30m_at_dt`, `reassign_1h_at_dt` (cleared only).

**On reassignment:** New 1h timer uses `assigned_at_dt` / activity since assign — pool history tracked in `pool_assignment_history`; RNR timers reset only on RNR **re-entry**, not on assignee change.

### 3.3 Timezone and time arithmetic

- IST: `ZoneInfo("Asia/Kolkata")` (`business_time.py:12`)
- Business window: 10:00–17:30, 27000 sec/day (`business_time.py:13-17`)
- `business_seconds_elapsed`: day iteration, skip Sunday (`business_time.py:99-123`)
- Stored timestamps: mix of `*_dt` timezone-aware and legacy string fields; comparisons coerce via `coerce_datetime`
- Task due: `ist_wall_to_utc_dt(due_date, "09:00")` default (`sla_engine.py:190-191`)
- Naive datetime: `_ensure_utc` adds UTC if missing (`business_time.py:20-23`)

### 3.4 Concurrency and data integrity

- Round-robin: `count_open_new_leads()` per candidate — race possible on simultaneous intake (`assignment_router.py:50-65`)
- SLA task insert: dedupe_key unique index prevents double task
- Lead mutations: bulk `$set` on flags — concurrent status change + cron could interleave; no versioning
- Log Attempt: not built — no double-tap protection

### 3.5 Data model

**SLA-relevant lead fields** (`lead_schemas.py`, runtime):

`lead_status`, `assigned_*`, `pool_key`, `pool_routing`, `pool_assignment_history`, `sla_paused`, `sla_activated_at_dt`, `sla_flags`, stage timestamps (`rnr_entered_at_dt`, `contacted_at_dt`, `nurture_entered_at_dt`, `interested_entered_at_dt`, `visit_completed_at_dt`, `sv_followup_*_entered_at_dt`, `gone_cold_entered_at_dt`, `negotiation_entered_at_dt`, `future_prospect_entered_at_dt`, `reengaged_at_dt`), `next_action_date`, `temperature`, `logged_outcome*`, `lost_reason`, `visit_date_dt`, `fp_cycle_count`, `context_updates`.

**Sprint gaps:** no `rnr_attempt_events`, `rnr_rep_cycle_count`, `rnr_global_count`.

**Indexes:** `lead_status`+`updated_at_dt`, `lead_status`+`temperature`+`updated_at_dt`, `lead_status`+`visit_date_dt` (`state.py:299-306`); **no** index on `sla_flags.*` or `rnr_entered_at_dt` — SLA scans may use status+updated_at with post-filter.

### 3.6 Notifications

**Escalation resolution:** First admin user by `id` sort; manager loaded but RNR/New/Contacted/Negotiation/Re-engaged/FP use `escalation_target="admin"` (`sla_engine.py:460-476`).

**Notification creation on SLA task:** `notification_type: "escalation"` if `escalation_target` set; else `"action_required"` (`sla_engine.py:325`).

**Channels:** In-app (WebSocket publish); Brevo email for nurturing 14d batch and SV Follow-up 2 7d admin alert.

**Null recipient:** Task skipped if no `assigned_user_id` (`sla_engine.py:317-319`); admin notif skipped if no admin user (`sla_engine.py:257-259`).

### 3.7 Frontend

- Status dropdown: all `UI_LEAD_STATUSES` (`leadStatus.js:3-23`)
- Escalation Queue: notifications API, not dedicated EQ entity (`EscalationQueuePage.js:33-37`)
- Sales Dashboard metrics from analytics API (`SalesDashboardPage.js`)
- `site_visit_count` shown in Data DNA grid but not AS4 scorecard filters

### 3.8 Dead and risky code

| Item | Location | Risk |
|------|----------|------|
| `_process_rule_sv_followup` | `sla_engine.py:1003-1011` | Dead — not in `process_all_slas` |
| `reminder_scheduler()` | `state.py:761-771` | Unwired asyncio loop |
| `has_meaningful_contact_since` | `lead_sla_utils.py:102-118` | Never called |
| Stale doc vs `vercel.json` | `DELIVERY_READINESS.md` | Ops misconfiguration |
| `Follow Up 1/2` reminder rules | `reminders.py:118` | Legacy statuses not in UI |
| Global SLA task cancel | `lead_service.py:581-589` | Breaks parallel timers |

---

## 8. Undocumented behaviour

| Behaviour | Actual value | File:line | Spec note |
|-----------|--------------|-----------|-----------|
| VC Nudge filter | `nudge_pending` until assignee acts | `nudge_pending.py`, `b777694` | Not in SOP |
| Follow Up Today ∩ Missed Follow-ups = ∅ | Mutual exclusion | `lead_follow_up.py`, `139df0d` | Not in SOP |
| Reserve-16 co-primary Gowtham RR | `[anusha@, gowtham@]` | `project_assignment_pools.py:31` | Spec: Anusha only |
| RNR 24h/48h admin escalations | Same copy as 15d ladder | `sla_engine.py:603-604` | Spec describes sprint not time ladder |
| Re-engaged auto Gone Cold at 48h | Status mutation | `sla_engine.py:1060` | Spec RE2 removed this |
| 24h auto-Warm | Still runs | `sla_engine.py:680` | Spec NU2 removed this |
| `general_manager` EQ access | shariff role | `roles.py:15` | Spec EQ1: Admin + Manager only |
| MCUBE inbound → call timeline | Adds call activity | `mcube/timeline.py` | Extends G3 activity set |
| Imported leads `sla_paused` | SLA frozen until first rep status change | `lead_service.py:591-594` | Import hold |
| Multi-project `project_ids[]` | Aug 2026 addition | `746f430` | PP8 extension |
| Reminder cron separate from SLA | `db.reminders` + optional WA | `reminders.py:132+` | Parallel reminder system |
| SV pre-24h task title | `"Send WA Reminder to Client"` | `sla_engine.py:810` | Spec SV4 says agent task not customer WA |

---

## 9. Build gap analysis — RNR sprint system (R2–R7)

### Reusable today

| Asset | Location | Use for sprint |
|-------|----------|----------------|
| RNR reminder tasks (3 × 4h BUS) | `sla_engine.py:569-600` | Keep or relabel as pre-sprint reminders |
| 15d admin task | `sla_engine.py:605` | Maps to R8 (parallel track) |
| `reassign_new_lead_in_pool` | `assignment_router.py:271` | Sprint 1 transfer at count=6 |
| `pool_assignment_history` | `assignment_router.py:342-357` | Audit trail per rep |
| `context_updates` timeline | lead document | Pattern for attempt events |
| Escalation notification pipeline | `sla_engine.py:325`, `notifications.py:130` | Sprint 2 → EQ |
| `_load_escalation_targets` manager | `sla_engine.py:466-475` | Sprint 1 manager notify |

### Must add

| Component | Schema | API | UI | Cron | Size |
|-----------|--------|-----|-----|------|------|
| Attempt events array | `rnr_attempt_events[{rep_id, at_dt, source}]` | `POST /leads/{id}/rnr-attempt` | Log Attempt button on RNR leads | — | **L** |
| Per-rep cycle counter | `rnr_rep_attempts`, `rnr_global_attempts` | atomic `$inc` | Show 1–6 to rep; 1–18 admin/manager | — | **M** |
| Sprint 1 transfer | — | call `reassign_new_lead_in_pool` at rep_count=6 | — | rule in `_process_rule_rnr` or event-driven | **M** |
| Sprint 2 EQ | `escalation_reason` on notif | whitelist filter | EQ reason column | threshold at global=12 | **M** |
| Sprint 3 Admin popup | — | summary endpoint | modal with Gone Cold / FP / Unqualified actions | at global=18 | **L** |
| R9 30d auto Gone Cold | flag `sla_flags.rnr.auto_gone_cold_30d_at_dt` | — | — | parallel rule | **M** |
| EQ column wiring | — | extend `/escalations` payload | RNR attempts, days in status, last note | — | **S** |
| Scoped task cancel | — | — | — | replace global cancel | **L** |

### Integration risks

1. **`lead_service.py:581-589`** cancels all pending SLA on any status change — must scope before R8/R9 ∥ attempt ladder.
2. **Manual +1** without call validation — reps could tap 6× to transfer; spec needs tie to call log or MCUBE.
3. **RNR re-entry** resets all `sla_flags.rnr` and `rnr_entered_at_dt` — sprint counters need explicit reset policy.
4. **Krishna/Mira Sprint 3** (PP7) needs admin-only assignment UI — not started.

---

## 10. Contradictions and risks

| # | Issue | Assessment |
|---|-------|------------|
| 1 | **R8/R9 parallel vs attempt ladder** | Cannot run genuinely in parallel until global SLA task cancellation is scoped; status sub-transitions would cancel sibling timers |
| 2 | **Manual counter gaming** | No idempotency, no link to call/WA proof — 6 rapid taps could trigger Sprint 1 unless bounded (e.g. 1 attempt per hour, or MCUBE/call required) |
| 3 | **Sprint counter reset on RNR exit** | Today: full `sla_flags.rnr` unset + new `rnr_entered_at_dt` (`lead_service.py:597-603`); spec silent on whether global count persists across RNR returns |
| 4 | **Sunday business hours** | Pool reassign + RNR reminders paused Sunday; leads created Sunday won't get 1h BUS reassign until Monday — may reassign into empty office if spec moves to Mon–Sun |
| 5 | **EQ5 vs implementation** | Current EQ shows **all** escalations including RNR 24h/48h — superset of EQ4 whitelist; client will see noise |
| 6 | **Contacted outcomes** | 4 options in code vs 6 in spec — neutral downgrade (NU8) cannot work until C2 complete |
| 7 | **SV4 vs pre-24h task** | Task literally says send WA to client — contradicts spec "NOT automated customer WhatsApp" |
| 8 | **Manager role** | Spec: EQ only; code: rep switcher + Site Visits + bulk ops — role conflates manager with team lead |
| 9 | **External cron SPOF** | No in-repo schedule; missed cron = silent SLA failure; lock skip returns 200 with `skipped` |
| 10 | **First-match admin** | Multiple admins seeded; only lowest `id` receives escalations — may not match ops expectation |

---

*End of Round 3 audit. All claims traced to current working tree as of 2026-09-14.*
