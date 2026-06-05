---
name: CRM Pipeline Audit
overview: Client-confirmed implementation decisions mapped to audit IDs (✅ implement now, ⚠️ pending/hold). This supersedes the initial audit report for execution.
todos:
  - id: audit-report-delivered
    content: Audit report complete — archived below
    status: completed
  - id: client-decision-log
    content: Client Q&A decision log reflected in plan
    status: completed
  - id: pending-items-blockers
    content: Track ⚠️ pending decisions that block future work
    status: completed
isProject: false
---

# CRM Pipeline — Client Q&A Decision Log (Execution Plan)

Every item from the audit is answered here in the same order and numbering. **STATUS** shows whether to implement now or hold. **IMPLEMENTATION** points to the exact backend/frontend areas to change.

### Implement now (highest priority order)

- **CRITICAL (production broken / core spec violations)**:
  - **C2**: Configure external cron + document `CRON_SECRET` (`backend/vercel.json`, `backend/env.example`, `backend/crm/api/v1/endpoints/cron.py`)
  - **1a**: New lead 30m must auto-reassign (mutate `assigned_to` fields in MongoDB; no “please reassign” task-only)
  - **7e**: Gone Cold re-entry resets 30-day clock (clear/reset SLA flag on each transition into Gone Cold)
  - **4c**: Nurturing cadence must be recurring (Hot every 2d, Warm every 4d; scheduled from task CREATED)
  - **5b/5c**: Visit Scheduled WA reminder must auto-send via Gupshup + reschedule cancels old task/flag and re-queues
  - **1e**: Cancel New 2h admin alert task only when status transitions to `Contacted`

- **HIGH (core workflow correctness)**:
  - **X4/9c**: Global ghost-job cleanup on every stage change (`lead_service.update_lead()`): cancel pending `source="sla"` tasks
  - **6c**: Replace Visit Completed 7d auto-move to Nurturing+Warm with new stage `SV Completed – Follow Up` (3-day rule pending)
  - **X5**: Log all SLA actions into `lead_events` (task created + lead mutations)
  - **9a**: Add `lost_reason` mandatory dropdown for Junk/Dropped/Closed Lost (API+UI enforcement)
  - **2a**: Add `rnr_entered_at_dt` and use it for all RNR timers
  - **3a/3d**: Add `contacted_at_dt` and use it for all Contacted timers
  - **6a**: Add `visit_completed_at_dt` and use it for all Visit Completed timers
  - **10a/10b/10c**: Add `Re-engaged` stage and inbound trigger (WhatsApp first), preserve prior flags/history
  - **7c**: SLA-created Gone Cold 30-day task must also create a notification document
  - **8a/8c/8d**: Future Prospect entry datetime + `fp_cycle_count` + manager review task at cycle 3

### Pending (do not implement until answered)

- **1b**: Define “active agent” for reassignment eligibility
- **1c**: Whether to implement true pause/resume with stored remaining time after-hours
- **4e+**: What to do after 2 weeks in Nurturing (beyond “stop creating cadence tasks”)
- **6d**: Whether task completion should reset Visit Completed timers
- **SV Completed – Follow Up (3-day action)**: what fires at day 3 in this new stage

---

## Archived: initial “as-is” audit report (reference only)

The remainder of this document is the original line-by-line audit of current code behavior, retained as a reference during implementation.

---

## STAGE 1 — NEW LEAD

### 1a. Does the 30-min SLA auto-reassign?
- **STATUS: NOT IMPLEMENTED (spec says reassign; code only creates a task)**
- **CODE:** `sla_engine.py:225-249`, `_process_rule_new()`
- **ACTUAL BEHAVIOUR:** Creates a MongoDB task document with `description="Reassign Lead"` and `dedupe_key="sla:new:30m:{lead_id}"`, assigned to the current owner. `assigned_to` on the lead is never changed. No DB write to the lead's assignee field occurs.
- **GAP/RISK:** Any lead with no actioning for 30 min silently accumulates a "Reassign Lead" task. If the assignee ignores it, nothing else happens until the 2h alert. Manual reassignment requires a human to act on the task.

### 1b. Algorithm for selecting new assignee
- **STATUS: NOT IMPLEMENTED at 30-min trigger (only via manual `/auto-assign` call)**
- **CODE:** `assignment_service.py:21-97`
- **ACTUAL BEHAVIOUR:** `auto_assign_lead()` picks the agent (`presales_agent` distinct values) with fewest active leads (excluding statuses: Advance Paid, Closed, Booked, Dropped, Unqualified). Falls back to `managers[0]` if counts are all tied. Returns `{"assigned_to": None}` if no eligible agents exist.
- **GAP/RISK:** This function is never called by the SLA engine. It is an API endpoint (`POST /leads/auto-assign`) that must be called manually.

### 1c. Business-hours check: timer pause/resume?
- **STATUS: PARTIAL — gate exists but no pause/resume**
- **CODE:** `sla_engine.py:63-68` (`is_business_hours_ist`), `sla_engine.py:217-219`
- **ACTUAL BEHAVIOUR:** `is_business_hours_ist()` checks `10:00 ≤ IST_time ≤ 17:30`. The entire `_process_rule_new()` returns early if outside these hours. There is NO stored "remaining time", no pausing, no resuming. If a lead arrives at 11pm, the 30-min timer based on `created_at_dt` keeps accumulating. When the cron runs the next morning at 10am, the lead is already many hours old and immediately fires. A lead arriving at 5:20pm will have the 30m check evaluated at the next cron run; if the next run is 10am the next day, it fires instantly.
- **GAP/RISK:** There is no day-of-week check (no weekends handling). No national holiday support. Business hours are hardcoded inline (not configurable in DB or config file).

### 1d. Does the 2-hour cap start from creation or from 30-min reassignment?
- **STATUS: PARTIAL — both timers start from lead creation**
- **CODE:** `sla_engine.py:222-249` — both `cutoff_30m` and `cutoff_2h` computed from `now_dt`, then compared against `created_at_dt`
- **ACTUAL BEHAVIOUR:** The 2h cap starts from `created_at_dt` (lead creation). It is independent of the 30m event. The 30m reassignment does NOT reset the 2h clock.
- **GAP/RISK:** If reassignment at 30m is manual and takes 29 min, the admin alert fires only 1 min after the new assignee gets the lead. Expected behaviour (2h for new assignee to act) is not matched by the implementation.

### 1e. Is the 2-hour admin alert cancelled if the agent acts?
- **STATUS: NOT IMPLEMENTED — BUG**
- **CODE:** `sla_engine.py:225-249`
- **ACTUAL BEHAVIOUR:** The 2h alert is blocked ONLY by `_flag_not_set("sla_flags.new.alert_admin_2h_at_dt")` AND the lead still matching the "New" status filter. If the agent changes the lead status away from "New" (e.g., to "Contacted"), the lead no longer matches the filter and the alert never fires — this is the only implicit "cancellation." However, if the agent adds a note or takes any action WITHOUT changing the status, the 2h admin alert will still fire. There is no explicit cancellation.
- **GAP/RISK:** An agent who logs a call note at 1h55m but forgets to change status will still trigger an admin alert at 2h.

### 1f. How is the admin alert delivered? Which admin receives it?
- **STATUS: PARTIAL — in-app task + in-app notification only, fire-and-forget**
- **CODE:** `sla_engine.py:227` (`target="admin"`), `sla_engine.py:91-97`, `_load_escalation_targets()` lines `201-215`
- **ACTUAL BEHAVIOUR:** Creates a task routed to the first user with `role="admin"` in the `users` collection. Also creates an `notifications` document. No email or WhatsApp is sent directly from the SLA engine. Delivery is fire-and-forget (no confirmation). If the admin's `assigned_user_id` can't be resolved, the task is silently skipped (`_skipped_no_assignee` counter incremented).
- **GAP/RISK:** If multiple admin users exist, only the FIRST one returned by MongoDB is used. If no admin user exists, the alert is silently dropped.

---

## STAGE 2 — RNR

### 2a. What defines D0?
- **STATUS: PARTIAL — uses last update timestamp, not RNR entry date**
- **CODE:** `sla_engine.py:258-284`, `_process_rule_rnr()`
- **ACTUAL BEHAVIOUR:** D0 is `updated_at_dt` — the lead's last modification timestamp. There is no dedicated `rnr_entered_at_dt` field. Every note, task completion, or field edit resets this clock.
- **GAP/RISK:** If an agent logs a note on a RNR lead, D0 resets. Multiple notes can indefinitely reset the follow-up cadence.

### 2b. Calendar days or business days?
- **STATUS: PARTIAL — business-hours gated but wall-clock elapsed time**
- **CODE:** `sla_engine.py:251-253`
- **ACTUAL BEHAVIOUR:** The entire `_process_rule_rnr()` returns early if outside business hours (10:00–17:30 IST). However, elapsed time is wall-clock (`updated_at_dt` delta), not counted business hours. If D+1 falls on Saturday, the task fires Monday when cron runs during business hours — but the 24h comparison uses absolute elapsed time so "24h" means 24 wall-clock hours, not 1 business day.
- **GAP/RISK:** No explicit weekday check. A lead created Friday 4pm could have a 24h escalation fire on Saturday if the cron runs in business hours on Saturday (no day-of-week restriction in the code).

### 2c. Pre-created or scheduler? Which scheduler? Persisted?
- **STATUS: PARTIAL — HTTP cron, MongoDB-persisted flags, no task pre-creation**
- **CODE:** `cron.py:32-36`, `sla_engine.py:251-314`
- **ACTUAL BEHAVIOUR:** Tasks are NOT pre-created on RNR entry. They are created on-the-fly when the cron endpoint is called and the time threshold is exceeded. Scheduler: external HTTP cron calling `POST /api/v1/cron/process-slas`. The `vercel.json` has no cron configured — external tooling (GitHub Actions, Vercel Cron, etc.) must be set up separately. SLA flags stored in MongoDB survive server restarts; the cron is stateless.
- **GAP/RISK:** If no external cron is configured, no RNR tasks are ever created. Dead-letter queue: none. No retry on failure.

### 2d. Duplicate prevention on manual task creation?
- **STATUS: PARTIAL — SLA tasks are deduped; manual tasks are not cross-checked**
- **CODE:** `state.py:142` (unique sparse index on `tasks.dedupe_key`), `tasks.py:111-148`
- **ACTUAL BEHAVIOUR:** SLA tasks use `dedupe_key` (e.g., `sla:rnr:reminder:{id}:1`) + lead `sla_flags`. Manual tasks (`POST /leads/{id}/tasks`) have no `dedupe_key` and no check against existing SLA tasks. If an agent manually creates a "D+1 follow-up" task, the SLA engine will ALSO create an "RNR Reminder" task when the 4h bucket triggers.
- **GAP/RISK:** Agents will see duplicate follow-up tasks for the same lead on the same day.

### 2e. D+2 escalation: changes assigned_to or creates a task?
- **STATUS: CREATES A TASK ONLY — assigned_to is NOT changed (spec may require DB reassignment)**
- **CODE:** `sla_engine.py:286-314`, `build_task_doc()` lines `91-97`
- **ACTUAL BEHAVIOUR:** The 48h escalation creates a task routed to the manager user (`assigned_user_id = manager["id"]`). The lead's `assigned_to` / `assigned_user_id` fields are NOT changed.
- **GAP/RISK:** Functionally different from reassignment. The lead still shows the original rep as owner. The manager sees a task but does not "own" the lead.

### 2f. How is the Sales Manager determined?
- **CODE:** `sla_engine.py:206-214`
- **ACTUAL BEHAVIOUR:** `db.users.find_one({"role": "manager"})` — the FIRST user with role `manager`. Hardcoded to one manager globally. If no manager is configured, `escalation_user` is `None`, `build_task_doc()` returns `None`, and the task is silently skipped.
- **GAP/RISK:** No team hierarchy. No per-project or per-team manager lookup. One global manager for all leads.

### 2g. D+15 from what reference? Calendar or business days?
- **STATUS: PARTIAL — from last update, wall-clock, business-hours gated**
- **CODE:** `sla_engine.py:289` (`15 * 24` hours, comparing `updated_at_dt`), `sla_engine.py:251-253`
- **ACTUAL BEHAVIOUR:** 15 calendar days from `updated_at_dt` (last lead update). Business-hours gated (cron won't fire this outside 10am–5:30pm IST). Any lead update resets the 15d clock.

---

## STAGE 3 — CONTACTED

### 3a. What starts the 48h clock?
- **STATUS: PARTIAL — any lead update restarts clock, not specifically "first contact"**
- **CODE:** `sla_engine.py:321-326`
- **ACTUAL BEHAVIOUR:** `"updated_at_dt": {"$lt": cutoff}` where `cutoff = now - 48h`. The clock starts (and resets) on EVERY lead update — status change, note, task creation — because all of these write `updated_at_dt`. There is no `contacted_at_dt` field.
- **GAP/RISK:** Agent adding any note resets the 48h clock, potentially delaying the escalation indefinitely.

### 3b. Wall-clock or business-hours?
- **STATUS: WALL-CLOCK — no business-hours check for Contacted**
- **CODE:** `sla_engine.py:316-343` (no `is_business_hours_ist` call)
- **ACTUAL BEHAVIOUR:** 24/7 wall-clock. If contacted at 5pm Friday, the 48h alert would fire at 5pm Sunday if the cron runs then.
- **GAP/RISK:** Weekend escalation notifications may be operationally meaningless.

### 3c. 48-hr "Manager flag" — real notification or UI badge?
- **STATUS: PARTIAL — real in-app notification, not WhatsApp/email**
- **CODE:** `sla_engine.py:317-343` (task to manager), `tasks.py:182-200` (notification created on manual task add — SLA tasks do NOT create a notification document, only a task)
- **ACTUAL BEHAVIOUR:** SLA creates a task assigned to the manager. In-app notification is delivered via SSE (`GET /api/notifications/stream`) to the manager. No WhatsApp or email is sent by the SLA engine directly. SLA-created tasks do NOT create a `notifications` document (only `tasks.py:add_task()` does). Manager must open the CRM to see the task in their queue.
- **GAP/RISK:** If the manager is not logged in and SSE is not active, they miss the alert unless the reminder system (separate) is configured.

### 3d. 72-hr reference timestamp?
- **STATUS: SAME REFERENCE AS 48H — both from `updated_at_dt`**
- **CODE:** `sla_engine.py:317-320` (both thresholds in same loop, same `updated_at_dt`)
- **ACTUAL BEHAVIOUR:** Both 48h and 72h are measured from `updated_at_dt`. They share the same reference timestamp, NOT 72h from when the 48h reminder was sent.

### 3e. Pending jobs cancelled when agent logs outcome?
- **STATUS: NOT IMPLEMENTED — implicit only via status change**
- **CODE:** No cancellation logic anywhere in the codebase.
- **ACTUAL BEHAVIOUR:** If the agent changes the lead status away from "Contacted," the lead no longer matches `_RE_CONTACTED`, so no future SLA tasks are created. But pending tasks in the `tasks` collection remain as "pending" (orphaned). No timer is cancelled. If the agent only adds a note without changing status, `updated_at_dt` resets, restarting the 48h clock.
- **GAP/RISK:** Every status change leaves orphaned SLA tasks. See X4.

### 3f. What constitutes a valid "logged outcome"?
- **STATUS: NOT IMPLEMENTED — no structured "outcome" field**
- **CODE:** `tasks.py:18-21` (`ContextUpdateCreate` schema: just `note: str` and `update_type: str`)
- **ACTUAL BEHAVIOUR:** Any string in `note` with any `update_type` (general_note, call_note, whatsapp_update, email_update, meeting_note, site_visit_note) is accepted. There is no required outcome dropdown or enum. Free text fully satisfies the API.
- **GAP/RISK:** Agent can log "." as a note and "satisfy" the SLA clock reset with no meaningful outcome captured.

---

## STAGE 4 — NURTURING

### 4a. Hot/Warm mandatory? DB-level or API-level?
- **STATUS: IMPLEMENTED at API level only, NOT at DB level**
- **CODE:** `nurture_temperature.py:62-88`, raises HTTP 400 if entering Nurturing without a valid label
- **ACTUAL BEHAVIOUR:** Enforced in `apply_nurture_temperature_rules()` called from `lead_service.update_lead()`. Returns HTTP 400 for invalid/missing labels. NOT a MongoDB constraint — direct DB write bypasses this.
- **GAP/RISK:** A script or direct `mongosh` write can set `lead_status="Nurturing"` with `temperature=null`. The SLA engine will then auto-set Warm after 24h (the fallback).

### 4b. 24-hour default-to-Warm rule — DB write or in-memory?
- **STATUS: IMPLEMENTED — writes "Warm" to DB**
- **CODE:** `sla_engine.py:349-368`, `_queue_lead_mutation()` executes `$set: {temperature: "Warm"}` on the lead document
- **ACTUAL BEHAVIOUR:** After 24h without a temperature value, the SLA engine writes `temperature: "Warm"` directly to the lead document. The flag `sla_flags.nurturing.temperature_warm_at_dt` prevents re-fire.
- **GAP/RISK:** If a lead enters Nurturing without a temperature and the cron hasn't run in >24h, the missing label sits unresolved. No immediate fallback on status change.

### 4c. Hot/Warm cadence: calendar days? Pre-created or on-demand?
- **STATUS: PARTIAL — wall-clock calendar days, on-demand, single-fire only**
- **CODE:** `sla_engine.py:370-412` (Hot: `cutoff_2d`, Warm: `cutoff_4d`)
- **ACTUAL BEHAVIOUR:** Wall-clock calendar days (no business-hours check in `_process_rule_nurturing()`). Tasks are created on-demand by the cron. Only ONE Hot follow-up task and ONE Warm follow-up task are EVER created per lead (single-fire flags `hot_followup_at_dt`, `warm_followup_at_dt`).
- **GAP/RISK:** CRITICAL BUG — the "every 2 days / every 4 days" cadence is not implemented. Only one task is created per nurturing period. After the flag fires, no more tasks are created regardless of whether the previous task was completed.

### 4d. Label change from Hot to Warm mid-cadence — are pending tasks cancelled?
- **STATUS: NOT IMPLEMENTED**
- **CODE:** No label-change handler in `lead_service.py` or `sla_engine.py` that cancels pending tasks
- **ACTUAL BEHAVIOUR:** If a lead is Hot (with `hot_followup_at_dt` flag set) and is changed to Warm, no Hot tasks are cancelled. The SLA engine simply won't create more Hot tasks (temperature no longer matches). The Warm task will be created when `updated_at_dt < now - 4d` AND `warm_followup_at_dt` not set.
- **GAP/RISK:** Orphaned Hot tasks remain in the queue as "pending."

### 4e. Maximum duration or cycle limit?
- **STATUS: NOT IMPLEMENTED — single-fire flags prevent infinite loop but also prevent recurring cadence**
- **CODE:** `sla_engine.py:370-412` (single flag per label)
- **ACTUAL BEHAVIOUR:** Due to the single-fire flag design, at most ONE task per label is ever created for a lead in Nurturing. No explicit maximum, no cycle counter, no auto-escalation out of Nurturing.
- **GAP/RISK:** Two separate bugs: (1) no recurring cadence after the first task; (2) no escalation path if lead sits in Nurturing for months.

### 4f. Nurturing mandatory task — detailed verification

**Requirement: create a new task AFTER entering Nurturing before any general note can be added.**

- **STATUS: PARTIALLY IMPLEMENTED — backend enforced for general_note only; multiple gaps**

**What IS implemented:**
- `lead_service.py:273-283` — on transition INTO Nurturing: sets `nurture_task_required_since_dt = now_dt` and `nurture_task_required_task_id = None`
- `lead_service.py:281-283` — on transition OUT of Nurturing: clears both fields
- `tasks.py:60-71` (`add_context_update`) — if `update_type == "general_note"` and `required_since` is set and `required_task_id` is None: returns HTTP 409
- `tasks.py:150-163` (`add_task`) — atomically satisfies gate: sets `nurture_task_required_task_id = task_id` using conditional `update_one`
- Frontend: `DigitalTwinPage.js:232-235` reads `nurture_task_required_since_dt` and blocks the "Add Note" button with toast

**Edge Cases:**

| Edge Case | Status |
|-----------|--------|
| Lead moved out then back into Nurturing | IMPLEMENTED — `lead_service.py:276-283` clears and resets fields on each transition |
| Multiple users simultaneously | PARTIAL — atomic DB `update_one` with null check, but two tasks can be inserted; only the first satisfies the gate |
| Simultaneous task + note creation | SAFE — DB `update_one` for gate is atomic; note returns 409 until gate is cleared |
| Lead reassignment while gate active | NOT RESET — gate persists across reassignment; new assignee must still create the task |
| Imported/migrated leads entering Nurturing via CSV | **BUG** — `lead_service.py:347-467` CSV import does NOT set `nurture_task_required_since_dt` even if `lead_status="Nurturing"` |
| Non-general notes (call_note, whatsapp_update, etc.) | **BYPASS** — `tasks.py:62` only gates `update_type == "general_note"`. Call notes, WhatsApp updates, meeting notes all bypass the gate |
| Standalone task creation (`POST /tasks`) | **BYPASS** — `tasks.py:205-271` (`create_standalone_task`) never checks or satisfies the nurture gate |
| `MyDashboardPage` quick notes | **BYPASS** — bypasses Digital Twin UI; relies on API 409, which only fires for `general_note` type |

---

## STAGE 5 — VISIT SCHEDULED

### 5a. 24-hr WA reminder: from visit DATE at midnight or visit DATE+TIME?
- **STATUS: IMPLEMENTED with exact datetime precision**
- **CODE:** `sla_engine.py:439-463` — `visit_date_dt <= now_dt + timedelta(hours=24)`
- **ACTUAL BEHAVIOUR:** `visit_date_dt` is stored as a BSON datetime with time component. The check is exact: the reminder fires when `visit_date_dt ≤ now + 24h`. If visit is at 2pm Tuesday, reminder fires any time after 2pm Monday.

### 5b. Is WhatsApp actually sent via API, or manual task?
- **STATUS: MANUAL TASK ONLY — no automated WA send**
- **CODE:** `sla_engine.py:457` (`description="Send WA Reminder to Client"`); `whatsapp_service.py` has real Gupshup integration but is ONLY called by `POST /whatsapp/send` (agent-initiated)
- **ACTUAL BEHAVIOUR:** The SLA engine creates a task telling the agent to send a WA reminder. No automated message is dispatched. The Gupshup API integration in `whatsapp_service.py` is only agent-triggered.
- **GAP/RISK:** If the agent is busy or ignores the task, no reminder is sent to the client.

### 5c. Rescheduling: old job cancelled, new one created?
- **STATUS: NOT IMPLEMENTED — BUG**
- **CODE:** `sla_engine.py:443-463` — `_flag_not_set("sla_flags.visit_scheduled.pre_24h_at_dt")` is a one-time flag
- **ACTUAL BEHAVIOUR:** Once the `pre_24h_at_dt` flag is set (after the "Send WA Reminder" task is created), changing `visit_date_dt` does NOT clear the flag, create a new task, or cancel the old task. The old task stays pending for the original date.
- **GAP/RISK:** Rescheduled visits will NOT get a new WA reminder task. Silent failure.

### 5d. Visit date passes without agent marking "Visit Completed"?
- **STATUS: PARTIAL — creates a follow-up task, no auto-move**
- **CODE:** `sla_engine.py:466-490` — `post_24h` rule: fires if `now_dt > visit_date_dt + 24h` AND still "Site Visit Scheduled"
- **ACTUAL BEHAVIOUR:** Creates "Post-Visit Follow-up" task. Lead stays in "Site Visit Scheduled" indefinitely. No auto-move, no escalation beyond this single task.
- **GAP/RISK:** Lead can remain in "Site Visit Scheduled" for months with no automated escalation.

---

## STAGE 6 — VISIT COMPLETED

### 6a. 48h from agent marking complete or from original scheduled date?
- **STATUS: FROM AGENT MARKING (updated_at_dt)**
- **CODE:** `sla_engine.py:501-503` — `"updated_at_dt": {"$lt": cutoff}`
- **ACTUAL BEHAVIOUR:** Clock starts from when `updated_at_dt` was last set (i.e., when the agent marked the lead as "Visit Completed," or any subsequent update). Not from `visit_date_dt`.

### 6b. 72-hr manager flag — real notification or UI badge?
- **STATUS: IN-APP TASK TO MANAGER — no WA/email from SLA engine**
- **CODE:** `sla_engine.py:497-518` (`target="manager"` for 72h)
- **ACTUAL BEHAVIOUR:** Same as Contacted stage — task routed to manager user. In-app notification visible via SSE. No SLA-triggered email/WhatsApp.

### 6c. After 1 week — automatic or manual?
- **STATUS: AUTOMATIC — SLA writes Nurturing+Warm to DB directly**
- **CODE:** `sla_engine.py:520-531`
- **ACTUAL BEHAVIOUR:** `_queue_lead_mutation()` sets `{"lead_status": "Nurturing", "temperature": "Warm"}` on the lead document when `updated_at_dt < now - 7d`. No agent decision. ALL Visit Completed leads > 7d auto-become Nurturing/Warm. No "Gone Cold" path exists here.
- **GAP/RISK:** The spec says "Nurturing OR Gone Cold." The implementation hard-codes Nurturing+Warm for every lead. High-intent leads and dead leads get the same treatment.

### 6d. Completing post-visit task — does it reset all SLA timers?
- **STATUS: PARTIAL — resets updated_at_dt clock only**
- **CODE:** `tasks.py:340-354` — task completion writes `updated_at_dt` to the lead
- **ACTUAL BEHAVIOUR:** Completing the task pushes a `task_completed` context entry and updates `updated_at_dt`. This restarts the 48h and 72h SLA clocks. If 48h flag was already set, it won't re-fire. If flags weren't set yet, the `updated_at_dt` reset delays them.
- **GAP/RISK:** An agent marking a task complete without doing any real follow-up effectively resets the SLA window.

---

## STAGE 7 — GONE COLD

### 7a. "Disappears from queue" — how implemented?
- **STATUS: NOT IMPLEMENTED**
- **CODE:** No `visible` field, no `in_queue` flag, no filter exclusion in `lead_service.list_leads()` or any list endpoint
- **ACTUAL BEHAVIOUR:** Lead stays fully visible in all list views, search, filters. No queue management behavior exists. "Disappears from queue" is not implemented.

### 7b. Day-30 reappearance — scheduled job or filter?
- **STATUS: CRON TASK ONLY — no real "reappearance" mechanism**
- **CODE:** `sla_engine.py:555-575`
- **ACTUAL BEHAVIOUR:** On day 30, creates a "Re-evaluate - re-engage or close" task. The lead was never hidden, so it can't "reappear." The task is the only signal. If the cron is down on day 30, the task fires whenever the cron next runs.

### 7c. Notification to agent on "reappearance"?
- **STATUS: NOT IMPLEMENTED — only a task is created**
- **CODE:** `sla_engine.py:565-575` — task creation only, no notification document
- **ACTUAL BEHAVIOUR:** SLA tasks (unlike manual tasks via `tasks.py:add_task()`) do NOT create `notifications` documents. No push notification, no in-app alert beyond the task appearing in the agent's task list.

### 7d. Grace period, auto-move to Future Prospect/Junk?
- **STATUS: NOT IMPLEMENTED**
- **CODE:** No grace period timer, no auto-move logic anywhere for Gone Cold
- **ACTUAL BEHAVIOUR:** The cron creates one task at 30d. If the agent ignores it, the lead stays in "Gone Cold" forever. No subsequent escalation.

### 7e. Second-time Gone Cold — fresh 30-day clock?
- **STATUS: BUG — second entry does NOT trigger a new task**
- **CODE:** `sla_engine.py:558` — `_flag_not_set("sla_flags.gone_cold.reevaluate_30d_at_dt")`
- **ACTUAL BEHAVIOUR:** The `reevaluate_30d_at_dt` flag is a one-time write. If the lead re-enters Gone Cold (e.g., from Visit Completed → Gone Cold again), the flag is already set and no new 30d task will ever be created for this lead.
- **GAP/RISK:** Repeat Gone Cold entries are completely silenced after the first cycle.

---

## STAGE 8 — FUTURE PROSPECT

### 8a. 90 days from what reference?
- **STATUS: FROM LAST UPDATE (updated_at_dt)**
- **CODE:** `sla_engine.py:580` — `"updated_at_dt": {"$lt": cutoff}` where `cutoff = now - 90d`
- **ACTUAL BEHAVIOUR:** From last `updated_at_dt`. Any note/task/update resets the clock. No `future_prospect_entered_at` field.

### 8b. "Instant alert on matching inventory launch"?
- **STATUS: NOT IMPLEMENTED**
- **CODE:** No inventory model, no preference-matching logic, no budget/BHK/location matching against any property/project collection
- **ACTUAL BEHAVIOUR:** No such feature exists. The 90d rule only creates a generic "90-day check-in" task.

### 8c. 3-cycle counter — how stored?
- **STATUS: NOT IMPLEMENTED**
- **CODE:** No `future_prospect_cycle_count` or equivalent field in lead schema or DB
- **ACTUAL BEHAVIOUR:** The SLA flag `sla_flags.future_prospect.checkin_90d_at_dt` is set once. Only ONE check-in task is ever created per lead in Future Prospect. No cycle counting.

### 8d. Manager review after 3 cycles?
- **STATUS: NOT IMPLEMENTED**

---

## STAGE 9 — JUNK / UNQUALIFIED

### 9a. "Lost reason mandatory" — DB or API level?
- **STATUS: NOT IMPLEMENTED**
- **CODE:** `lead_schemas.py:45-64` (`LeadUpdatePatch`) — no `lost_reason` field exists at all
- **ACTUAL BEHAVIOUR:** No lost reason field exists in any schema. Not enforced at DB level, API level, or UI level.

### 9b. Is Junk reversible? Audit trail?
- **STATUS: REVERSIBLE (unintentionally) — basic audit trail only**
- **CODE:** `lead_service.py:325` — any `PUT /leads/{id}` can set any `lead_status` value
- **ACTUAL BEHAVIOUR:** Any lead can be moved to/from any status without restriction. Reopening a Junk lead is possible. Changes are logged in `context_updates` array as "Updated: lead_status" and in `lead_events` collection via `log_lead_event()`. No formal "reopen" workflow or reason required.

### 9c. Are all scheduled jobs cancelled when lead moves to Junk?
- **STATUS: NOT IMPLEMENTED — orphaned jobs remain**
- **CODE:** No cleanup logic in `lead_service.update_lead()` or anywhere in the codebase
- **ACTUAL BEHAVIOUR:** When a lead moves to Junk, ALL pending tasks in the `tasks` collection for that lead remain as "pending." SLA flags prevent re-firing of same thresholds, but existing pending tasks are never cancelled. If the SLA engine runs and the lead no longer matches the old status filter, no NEW tasks are created — but old ones remain.
- **GAP/RISK:** Agents see stale tasks for Junk leads in their queues.

---

## STAGE 10 — RE-ENGAGED

### 10a. What triggers Re-engaged status?
- **STATUS: NOT IMPLEMENTED**
- **CODE:** `whatsapp_service.py:396-409` — inbound WA message matched to lead by phone number logs a context update and updates `updated_at_dt`, but does NOT change `lead_status`
- **ACTUAL BEHAVIOUR:** There is no "Re-engaged" status in `UI_LEAD_STATUSES` (`lead_status.py:3-14`). No automatic status change occurs on inbound WhatsApp, inbound call, or form submission.

### 10b. Which stage does re-engagement land in?
- **STATUS: NOT IMPLEMENTED**

### 10c. Does re-engagement reset timers?
- **STATUS: NOT IMPLEMENTED — inbound WA only resets updated_at_dt**
- **CODE:** `whatsapp_service.py:406-409`
- **ACTUAL BEHAVIOUR:** Inbound WA message updates `updated_at_dt`, which resets the clock for whatever stage the lead is currently in. No formal re-engagement pipeline exists.

---

## CROSS-CUTTING SYSTEM CHECKS

### X1. Business hours engine
- **STATUS: PARTIAL — hardcoded, no holidays, no stored remaining time**
- **CODE:** `sla_engine.py:19` (`IST = ZoneInfo("Asia/Kolkata")`), `sla_engine.py:63-68`
- **ACTUAL BEHAVIOUR:** 10:00–17:30 IST, hardcoded inline constants. Only applied to New and RNR rules. No national holiday support. No "remaining duration" stored — the check is always `elapsed_time = now - reference_dt`. Timezone: Asia/Kolkata (correct for IST). Not configurable without code change.

### X2. Scheduler reliability
- **STATUS: FIRE-AND-FORGET HTTP CRON — no persistence of job queue, no DLQ**
- **CODE:** `cron.py:32-36`, `vercel.json` (no cron array)
- **ACTUAL BEHAVIOUR:** External caller must hit `POST /api/v1/cron/process-slas` with `Authorization: Bearer {CRON_SECRET}`. MongoDB flags survive restarts (idempotent). If cron fails or is misconfigured, no SLA tasks are created. No dead-letter queue, no retry, no monitoring.
- **GAP/RISK:** `CRON_SECRET` is not in `env.example`. The external cron scheduler is NOT configured in `vercel.json`. SLA may not be running in production at all.

### X3. Race condition on stage transitions
- **STATUS: LOW RISK — no locking, but design is mostly safe**
- **CODE:** `sla_engine.py:228-249` (query then bulk write), `tasks.py:150-163` (atomic conditional update)
- **ACTUAL BEHAVIOUR:** The SLA engine queries leads, then does a bulk write. There's a window between query and write where a status change could leave the flag written on a lead that's no longer in the relevant stage. This is benign (the task still exists but the lead moved on). The nurture gate uses atomic MongoDB `update_one` with a conditional filter, preventing double-satisfaction.
- **GAP/RISK:** Minor: a rare stale task can be created just before a status change. No dangerous double-execution.

### X4. Ghost job prevention — are all jobs from previous stage cancelled?
- **STATUS: NOT IMPLEMENTED — all stage transitions leave orphaned tasks**
- **CODE:** No cleanup logic in `lead_service.update_lead()`, `transfers.py`, or `sla_engine.py`
- **ACTUAL BEHAVIOUR:** Every stage transition leaves pending SLA tasks from the previous stage in the `tasks` collection. SLA flags prevent new tasks from being created for that stage, but existing "pending" tasks are never cancelled.

**Complete list of orphan-generating transitions:**
- New → any: "Reassign Lead" task stays pending
- New → any (if 2h elapsed): "Alert Admin" task stays pending
- RNR → any: "RNR Reminder," "Escalate to Sales Manager," "Escalate to Admin" tasks stay pending
- Contacted → any: "Agent Reminder + Manager Flag," "Admin Alert" tasks stay pending
- Nurturing → any: "Hot Lead Follow-up," "Warm Lead Follow-up" tasks stay pending
- Site Visit Scheduled → any: "Send WA Reminder," "Post-Visit Follow-up" tasks stay pending
- Visit Completed → any: "Push for booking," "Manager Flag" tasks stay pending
- Gone Cold → any: "Re-evaluate" task stays pending

### X5. Audit trail
- **STATUS: PARTIAL — `lead_events` exists but SLA actions not logged there**
- **CODE:** `lead_events.py:10-32`, `state.py:174-176` (indexes on `lead_events`)
- **ACTUAL BEHAVIOUR:** `lead_events` collection records: `note_added`, `task_created`, `task_updated`, `assignee_changed`, `transfer_created`. The SLA Engine writes tasks and flags but does NOT call `log_lead_event()`. Automated SLA actions (reassign task created, escalation task created, temperature set to Warm, lead auto-moved to Nurturing at 7d) are NOT recorded in `lead_events`.
- **GAP/RISK:** No audit trail for automated SLA actions. No way to know from the audit log that the SLA moved a lead to Nurturing+Warm.

### X6. Deduplication / idempotency
- **STATUS: IMPLEMENTED for SLA tasks; NOT implemented for manual webhooks**
- **CODE:** `state.py:142` (unique sparse index on `tasks.dedupe_key`), `sla_engine.py:608-610` (`BulkWriteError` handled gracefully)
- **ACTUAL BEHAVIOUR:** SLA task deduplication is solid: `dedupe_key` + SLA flags + MongoDB unique index. If cron fires twice in the same minute, the second run finds flags already set and creates no duplicate tasks. Manual task creation has no dedup. Inbound WA webhooks have no idempotency (duplicate webhook delivery creates duplicate context entries).

---

## PRIORITY BUG LIST

### CRITICAL

| # | Bug | Fix |
|---|-----|-----|
| C1 | **SLA 30m creates a task, not a reassignment.** Spec requires `assigned_to` change in DB. | Call `auto_assign_lead()` (or `transfer_lead()`) from `_process_rule_new()` instead of `_queue_task()` at the 30m threshold. |
| C2 | **No external cron configured.** `vercel.json` has no cron. `CRON_SECRET` not in `env.example`. All SLA rules are silently inactive in production. | Add cron job to `vercel.json` or CI, document `CRON_SECRET` in `env.example`. |
| C3 | **Nurturing cadence is single-fire, not recurring.** Hot/Warm tasks are created once per lead lifetime. | Remove single-flag design; use a rolling `last_followup_at_dt` flag reset on task creation, or use a counter-based key like `sla:nurturing:hot:{id}:{cycle}`. |
| C4 | **Visit reschedule does not generate a new WA reminder task.** Old pre_24h flag blocks new reminder creation. | On `visit_date_dt` change, clear `sla_flags.visit_scheduled.pre_24h_at_dt` in `update_lead()`. |
| C5 | **2h admin alert fires even if agent actioned the lead (only status change stops it).** Note additions are invisible to the alert. | The 2h query should also check `updated_at_dt < created_at_dt + 2h`, i.e., alert only if `updated_at_dt ≈ created_at_dt` (no action taken). |
| C6 | **Re-entering Gone Cold a second time fires no task** (flag already set). | Reset `sla_flags.gone_cold.reevaluate_30d_at_dt` when lead transitions INTO Gone Cold (in `update_lead()`). |

### HIGH

| # | Bug | Fix |
|---|-----|-----|
| H1 | **No ghost-job cleanup.** Every stage transition leaves orphaned pending SLA tasks. | On stage transition in `update_lead()`, `$set: {status: "cancelled"}` on all tasks where `lead_id = X` and `source = "sla"` and `status = "pending"`. |
| H2 | **Visit Completed 7d auto-moves ALL leads to Nurturing+Warm.** No "Gone Cold" path. | Add `interest_level` or agent choice; auto-move to Nurturing only if `interest_level` is set, else create a decision task. |
| H3 | **D+2 RNR escalation creates task for manager but does not change `assigned_to`.** | After creating the escalation task, also update the lead's `assigned_to` to the manager user in the bulk write. |
| H4 | **Nurturing mandatory task bypassed by non-general note types** (call_note, whatsapp_update, etc.) and by `POST /tasks` (standalone). | Extend the 409 gate to all `update_type` values (or at least all that log substantive interaction), and add gate check to `create_standalone_task`. |
| H5 | **SLA actions not in audit log.** Automated SLA writes are invisible in `lead_events`. | Call `log_lead_event("sla_action", ...)` inside `_queue_task()` and `_queue_lead_mutation()`. |
| H6 | **Lost reason not implemented.** Junk/Unqualified leads have no mandatory classification. | Add `lost_reason: Optional[str]` to `LeadUpdatePatch`; enforce NOT NULL when `lead_status` matches closed/junk patterns in `apply_nurture_temperature_rules`-style validator. |

### MEDIUM

| # | Bug | Fix |
|---|-----|-----|
| M1 | **D0 for RNR resets on every lead update.** No explicit `rnr_entered_at_dt` field. | Add `rnr_entered_at_dt` set when `lead_status` transitions to RNR; use it (not `updated_at_dt`) for RNR elapsed time. |
| M2 | **No business-hours-aware timer for Contacted/Visit Completed stages** (fires on weekends). | Add `is_business_hours_ist()` gate to `_process_rule_contacted()` and `_process_rule_visit_completed()`. |
| M3 | **CSV import skips nurture gate.** Leads imported with Nurturing status don't set `nurture_task_required_since_dt`. | In `import_csv()`, if `lead_status == "Nurturing"` set `nurture_task_required_since_dt` and `nurture_task_required_task_id = None`. |
| M4 | **No "Re-engaged" stage.** Inbound WA message doesn't change lead status. | Add "Re-engaged" to `UI_LEAD_STATUSES`; in `process_webhook()` handle inbound match → status change logic. |
| M5 | **Gone Cold "queue disappearance" not implemented.** | Add `in_queue: bool` field; set `False` on Gone Cold transition; filter in `list_leads()` default query. |
| M6 | **Future Prospect: no inventory matching, no 3-cycle counter.** | Add `fp_cycle_count` field; increment on each 90d task creation; add matching logic against `projects` collection. |
| M7 | **Business hours are hardcoded.** No admin-configurable window. | Add `business_hours` document to MongoDB; load in `SLAEngineService.__init__()`; fall back to 10:00–17:30 IST. |
| M8 | **No national holiday support in business-hours check.** | Add `holidays` collection or config; check before firing New/RNR rules. |
| M9 | **Admin escalation always goes to first admin user** — no round-robin or per-project routing. | Support multiple admins; add routing logic based on lead project. |
| M10 | **Inbound WhatsApp webhook has no idempotency.** Duplicate delivery creates duplicate context entries. | Add `dedupe_key` to `context_updates` entries based on `gupshup_message_id`. |