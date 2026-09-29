# Clara CRM Enhancement Tracker — Verification with Proof

**Date:** 2026-09-27 (IST)
**Source tracker:** `Clara CRM Enhancement Tracker.xlsx`, sheet "Phase 1", spreadsheet rows 2–58 (57 items)
**Code under test:** branch `main` at `ba056b1` plus uncommitted work (CSV export sort rewrite, Escalation Queue filter isolation, escalation legacy backfill + test)
**Method:** independent code reading (file:line), backend pytest, in-process live checker, Playwright browser suite on the disposable `arihant_crm_e2e` database, read-only aggregate counts on production `arihant_crm`, and screenshots from the local e2e stack.
**Row numbers below are the spreadsheet row numbers (#2 … #58)**, identical to the earlier report `CHANGE_TRACKER_VERIFICATION.md` and to the Playwright test titles.

---

## 1. Summary

| Verdict | Count | Rows |
|---|---:|---|
| **Done** | 32 | 2, 3, 6, 7, 9, 10, 11, 15, 16, 18, 20, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 34, 36, 37, 39, 41, 42, 44, 45, 48, 49, 50 |
| **Done with notes** (works, but differs from the literal wording; earlier accepted by product decision or documented here) | 10 | 4, 12, 13, 19, 35, 38, 40, 46, 53, 54 |
| **Partial** (a real piece of the ask is missing or broken) | 11 | 5, 8, 17, 21, 22, 33, 43, 51, 55, 56, 57 |
| **Not done** | 2 | 47 (Marketing / Meta import), 52 (Channel-partner integration beyond a source label) |
| **Not started, Phase 2 by the client's own note** | 1 | 58 (Related leads) |
| Blank / placeholder row | 1 | 14 ("Missed -") |

Two of the "Partial" rows are **live bugs** rather than scope gaps: **#8/#40** (a `manager` role can open the Escalation Queue page but the backend rejects the escalated filter with 403; no manager accounts exist in production today, so no live user is affected) and **#33** (a general manager sees the bulk-assign control but the backend returns 403).

### Automated evidence at a glance

| Check | Result |
|---|---|
| Backend `pytest tests` (719 collected) | **638 passed, 4 skipped, 11 failed, 66 errors**. All 66 errors and 8 of the 11 failures are legacy integration suites (`test_my_dashboard.py`, `test_new_features.py`, `test_gupshup_whatsapp.py`, `test_platform_ops.py`, `test_auth_refresh_and_campaigns.py`) that need `REACT_APP_BACKEND_URL` plus a hard-coded legacy login `roshini@arihant.com`, which does not exist on the e2e database. The remaining 3 failures (`test_routing_manual_status.py`) are clock-dependent: they patch `crm.utils.business_time.is_business_hours_ist`, but `assignment_router.py:23` imports that name directly, so the patch has no effect and the test uses the real clock. The run happened at 02:20 IST (outside business hours). **None of the 11 failures concern tracker rows; every tracker-mapped unit test passed** (see §3). |
| `scripts/verify_change_tracker_live.py` (in-process, 19 checks) | 17 PASS, 2 FAIL. Both failures are stale source-string checks written before the phase-3 SLA rewrite (`"3600" and "reassign_1h_at_dt"`; `patch_context` line moved to `tasks.py:280-282`). Behaviour is covered by current unit tests. |
| Playwright tracker suite on `arihant_crm_e2e` (41 tests) | **41 / 41 passed** (36 on the full run; 2 infrastructure flakes + 3 serial-skipped tests re-run and passed). See §4. |
| Production read-only snapshot | 30,159 leads; Aurum 491; Dormant 0; Shariff = general_manager; 0 manager users; All-Leads gap = 3,391 "Roshini"-named leads. See §5. |
| Screenshots (local e2e stack) | 11 PNGs in `docs/verification-screens/2026-09-27/`. See §6. |

---

## 2. Row-by-row verification

Legend — **Code:** where it is implemented. **Tests:** unit (`backend/tests/…`) and browser (`frontend/e2e/…` test title). **Live:** production read-only number where relevant.

| Row | Client ask (short) | Verdict | Code evidence | Tests | Live / notes |
|---|---|---|---|---|---|
| 2 | Edit notes/comments, no delete | **Done** | `PATCH /api/leads/{id}/context/{entry_index}` in `backend/crm/api/v1/endpoints/tasks.py:198`; pencil in `frontend/src/pages/DigitalTwinPage.js:1347-1360`; no delete endpoint exists | `test_edit_note_mongo_index.py`; e2e "#2 Edit note persists; no delete control" | — |
| 3 | WhatsApp in left menu | **Done** | `frontend/src/components/layout/DashboardLayout.js:99`; route `App.js:207` | e2e "#3 WhatsApp is in the left nav" | — |
| 4 | Alert when lead replies to automated WA message | **Done with notes** | `whatsapp_service.py:1729-1759` creates `whatsapp_reply` notification for the assignee on any inbound message (deduped per message) | e2e "#4 inbound WhatsApp reply notifies assignee" | Fires on *every* inbound reply, not only after an automated template. No unassigned-lead alert. |
| 5 | Auto transfer of RNR leads | **Partial (behind a flag)** | Phase-3 RNR ladder (72h pool re-assign, D7/D15 escalation) `sla_engine.py:762-832` runs only when `SLA_PHASE3_RULES_ENABLED` is true (`sla_feature_flags.py`, default **false**; not set in `.env`). Legacy path creates admin review tasks only | `test_sla_rnr_phase3.py`, `test_sla_rnr_escalate_query.py`; e2e "#5 RNR status does not auto-reassign ownership" | Sheet says "Implemented (effective for new leads from August)". In the deployed config **no ownership transfer happens**; earlier product decision (2026-09-04) was "tasks, not transfer". Client must confirm which behaviour they want; enabling the flag is a config change. |
| 6 | Leads stay in Missed Follow-ups after update | **Done** | `lead_follow_up.py:84` `clear_missed_follow_up_after_activity`, `:160-193` Follow Up Today / Missed mutually exclusive; called from `tasks.py:150,644`, `whatsapp_service.py:1817,2706` | `test_missed_follow_up_clear.py`, `test_lead_overview_unit.py`; e2e "#6 note clears Missed Follow-ups metric membership" | Commit 139df0d |
| 7 | Freeze "Back to Explorer" | **Done** | `DigitalTwinPage.js:898-908` `sticky top-12 z-30` | e2e "#7 Back to Explorer stays visible while scrolling" | — |
| 8 | Escalation Queue for Admin | **Partial (ACL bug)** | Route `/escalation-queue` renders `VirtualCustomerPage escalationLocked` (`App.js:208-216`); frontend guard admits admin/manager/general_manager (`App.js:100-117`); backend `assert_escalated_filter_allowed` (`escalation_queue.py:173-178`) uses `can_filter_escalated_leads` = **admin + general_manager only** (`roles.py:29-31`) → a `manager` gets HTTP 403. Whitelist of 13 SLA pairs `escalation_queue.py:15+`; legacy backfill `scripts/backfill_escalation_queue_legacy.py` (uncommitted) | `test_sla_escalation_queue_t10.py`, `test_escalation_legacy_backfill.py`; e2e "#8 Escalation queue reachable for admin", "#38 Escalations allowed for admin/manager/GM; denied for rep" | Prod users by role: admin 4, rep 7, general_manager 1, **manager 0** → bug is latent today. `frontend/src/pages/EscalationQueuePage.js` is dead code. |
| 9 | Updated At on every lead | **Done** | `lead_service.py:852-853` sets `updated_at` + `updated_at_dt`; VC column `LeadDataTable.jsx:92-93,362-365`; CSV export "Updated at" on by default `lead_export_service.py:66` | `test_lead_export.py`; e2e "#9 #10 #18 #19 #40 #41 #42 VC columns" | Prod: **0** leads missing `updated_at` or `updated_at_dt` (30,159 leads) |
| 10 | Contact number bold | **Done** | `LeadDataTable.jsx:251-257` `font-semibold` | e2e "#9 … VC columns" | — |
| 11 | Retain filter / scroll after call or update | **Done** | Filters live in URL (`VirtualCustomerPage.js:344-355`); scroll + rows-loaded + lead id saved in `vc_list_restore` (`:804-887,969-973`) | e2e "#11 filters survive Back to Explorer" | — |
| 12 | Status Distribution → Virtual Customer | **Done with notes** | Pie on org **Dashboard** `DashboardPage.js:284-296` drills to `/virtual-customer?statuses=…`; My Dashboard uses overview cards `LeadOverviewGrid.jsx:34-38` | e2e "#12 #13 org dashboard status chart + time filter drill to VC" | Widget is on Dashboard, not My Dashboard (accepted 2026-09-04) |
| 13 | Date/month filter on distribution | **Done with notes** | `DashboardPage.js:211-217,493-506`: 7/15/30 days, All, Custom range | same e2e | Presets + custom range; no single "month" picker |
| 14 | (blank row "Missed -") | n/a | — | — | Row has no request text |
| 15 | Saved Views apply all filters | **Done** | `lead_filter_views_service.py:22-50`; API `leads.py:178-203`; `leadFilters.js:347` `applyViewFiltersToState` | `test_lead_filter_views.py`, `test_lead_filter_views_owners_unit.py`, `leadFilters.test.js`; e2e "#15 saved view keeps sales owner + status" | — |
| 16 | Edit VIP tag | **Done** | `LeadProfileHeader.jsx:520-546`; manual override `lead_service.py:884-891` | e2e "#16 VIP tag is editable" | — |
| 17 | Source counts wrong (Aurum Analytica, Management Ref) | **Partial (data repaired, not enforced)** | Canonical picklist `lead_picklists.py:132,163`; repair scripts `scripts/fix_lead_source_rep_worked.py`, `extract_csv_data.py:80-88` | none | Prod today: `aurum analytica` **491**, `management*` **26** (values "management reference", "management referral"), **7,903 leads with empty source**, `channel partner` 2,289. Aurum is fixed; the "4,000+ Management Ref" claim is not reproducible in data. No rule prevents new variants. |
| 18 | Phone column next to Name | **Done** | `LeadDataTable.jsx:59` column order | e2e "#9 … VC columns" | — |
| 19 | Sales Owner column last | **Done with notes** | `LeadDataTable.jsx:59`: after Recent note, before Created/Updated/Actions | same | Accepted 2026-09-04 (Created/Updated were added later for #40/#41) |
| 20 | AI knows RNR = Ringing No Response | **Done** | Prompt grounding `ai_service.py:215` | `test_ai_service.py` | Prompt-only; model can still err |
| 21 | WA ack only for "New", not manual/walk-in | **Partial** | `lead_service.py:310-316` sends ack when status is New; intake always New (`lead_intake_service.py:786-800`) | `test_lead_intake_unit.py` | Manually created leads with status New **still receive the ack**. Product decision 2026-09-04 was "all New leads". Client must confirm. |
| 22 | Per-project brochure buttons | **Partial** | 4 buttons Mélange, Reserve 16, Krsna, Vivriti: `WhatsAppInboxPage.js:1125-1145`, `DigitalTwinPage.js:1745-1765`; PDF map `core/state.py:151-159`; API `whatsapp.py:75` | e2e "#22 per-project brochure buttons (mocked WATI)"; `test_whatsapp_send_pricing.py` | **No Vipassana button/PDF** although Vipassana is a live project name |
| 23 | RNR Queue shows only RNR | **Done** | `sales_dashboard_filters.py:27-45` `rnr_metric_clause` (current status RNR, excludes closed/Junk/Unqualified); `dashboardDrillDown.js:76` | `test_rnr_metric_clause_unit.py`; e2e "#23 RNR queue drill-down uses current RNR only" | — |
| 24 | Unqualified card on My Dashboard | **Done** | `lead_overview_service.py:36,310-314`; `LeadOverviewCard.jsx:15`; `MyDashboardPage.js:746` | e2e "#24 Unqualified card exists on My Dashboard" | — |
| 25 | Task time saved wrong (11:00 → 5:30 PM) | **Done** | `helpers.py:18` `ist_wall_to_utc_dt` used in `tasks.py:326,432,557`, `sla_engine.py:217`; 12 PM fix commit 599de55 | `test_ist_wall_to_utc_unit.py`; e2e "#25 task 11:00 IST stores 05:30 UTC"; live checker "IST 11:00 -> UTC 05:30" PASS | Tasks created before the fix were not backfilled |
| 26 | WA replied tag/colour | **Done** | flag `whatsapp_service.py:1575,1716`; badge `LeadDataTable.jsx:237-245`; inbox chip `WhatsAppInboxPage.js:935-938` | e2e "#27 #26 #34 WA inbound → Admin lead, Replied chip, recent note" | Prod: **289** leads flagged `whatsapp_replied` |
| 27 | Unknown WATI senders → New leads | **Done** | `whatsapp_service.py:1510` `create_whatsapp_unknown_lead`, called from webhook `:1698`; backfill `scripts/backfill_wa_unknown_leads.py` | `test_wa_unknown_lead_unit.py`; same e2e | Prod: 1,721 leads with a WhatsApp/WATI source |
| 28 | Multi-select Project | **Done** | `lead_project_fields.py` (`projects[]`); `DataDnaGrid.jsx:391-410`; migration `scripts/migrate_lead_projects_to_arrays.py` | `test_lead_project_fields_unit.py`; e2e "#28 multi-project filter matches projects[]" | — |
| 29 | Freeze header / scroll bar | **Done** | VC sticky filter bar `VirtualCustomerPage.js:1199-1204`, sticky table header `LeadDataTable.jsx:394-454`; WhatsApp pane-scroll layout `WhatsAppInboxPage.js:778,809,873` | e2e "#29 VC filter bar is sticky" | — |
| 30 | WATI dashboard under My Dashboard | **Done** | `my_dashboard.py:211` `GET /my-dashboard/whatsapp`; tab `MyDashboardPage.js:233-243,1213-1303` | `test_my_dashboard_whatsapp_unit.py`; e2e "#30 My Dashboard WhatsApp tab" | Tab inside My Dashboard, not a separate page |
| 31 | Timeline: Meta Instant Form resubmission via Zapier shows project | **Done** | `lead_intake_service.py:569-571,661`; `zapier_leads_service.py:247` | `test_zapier_leads_unit.py`; e2e "#31 Zapier Meta timeline shows project" | — |
| 32 | Nudge button → "Nudge by Admin" | **Done** | `POST /leads/{id}/nudge` `leads.py:737-797`; `nudge_pending.py`; UI `LeadRowActions.jsx`, `VirtualCustomerPage.js:898-905` | `test_nudge_unit.py`, `test_nudge_pending_unit.py`; e2e "#32 nudge from Digital Twin + VC nudge filter until assignee acts" | Managers/GM can also nudge; title still says "by Admin" |
| 33 | Bulk select + assign | **Partial (ACL bug)** | `POST /leads/bulk-update` `leads.py:653-700` allows **admin, manager**; UI enables for admin/manager/**general_manager** (`VirtualCustomerPage.js:898-901`) → GM sees the control and gets 403 | `test_bulk_update_unit.py`; e2e "#33 bulk select + bulk status" | Shariff (GM) is affected |
| 34 | WA RHS "recent note" under Assignee | **Done** | `WhatsAppInboxPage.js:1313,1325-1330` | e2e "#27 #26 #34 …" | — |
| 35 | Edit template before send | **Done with notes** | `WhatsAppInboxPage.js:578-631,1080-1120`: variables editable, body read-only | e2e "#35 template params edited before send (mocked WATI)" | WhatsApp only allows pre-approved template bodies |
| 36 | Click lead from notification bell | **Done** | `DashboardLayout.js:646-647`; `NotificationsPage.js:127` | e2e "#36 notification panel click navigates to lead" | — |
| 37 | "View all alerts" works | **Done** | `DashboardLayout.js:682-685` → `/notifications` (`App.js:206`) | e2e "#37 View All shows read + unread history" | — |
| 38 | Escalation queue in VC format; Admin + Shariff | **Done with notes** | Reuses VC table with escalation columns (`LeadDataTable.jsx:544`); ACL by role, Shariff is `general_manager` | e2e "#38 Escalations allowed for admin/manager/GM; denied for rep" | Prod: Shariff role = `general_manager`, active. See #8 for the manager 403. |
| 39 | Notes on other agents' leads + notify assignee | **Done** | `tasks.py:86-91,168` (general note needs view access only); `note_notify.py:55-91` "New note on your lead" | `test_note_notify_unit.py`; e2e "#39 #44 cross-assignee note + mention notify" | — |
| 40 | Created date column | **Done with notes** | `LeadDataTable.jsx:88-89,353-356` | e2e "#9 … VC columns" | — |
| 41 | Created + Updated with time | **Done** | `LeadDataTable.jsx:79-94` `formatDateTimeIST` | same | — |
| 42 | Project name bold (dark mode) | **Done** | `LeadDataTable.jsx:325` `font-semibold text-crm-fg` | e2e asserts weight ≥ 600 | — |
| 43 | Remove Dormant; Gone Cold resurfaces after 30 days | **Partial** | Dormant filter ignored `lead_list_query.py:128-129`, `leadFilters.js:210`; Gone Cold 30-day rule `sla_engine.py:1596-1627` creates a task | e2e "#43 dormant chip not shown from legacy URL" | Prod: **Dormant = 0**, Gone Cold = 1,634. **Gap:** `lead_follow_up.py:146-157` excludes Gone Cold from Follow-up Today, so the 30-day task never surfaces the lead there; `dormant_leads` analytics remnants remain in `lead_analytics_queries.py:283-295`. |
| 44 | Tag/@mention another agent | **Done** | `note_notify.py:18-102` (`lead_note_mention`); `NoteTextareaWithMentions.jsx`, `NoteMentionPicker.jsx` | `test_note_notify_unit.py`; e2e "#39b inline @mention…", "#44 create-lead Additional Notes inline @mention + notify" | — |
| 45 | AI Summary accuracy | **Done** | `ai_service.py:219-228,329-338` feeds full timeline + CRM hints; model `openai/gpt-oss-120b`; staleness/regen `ai_lead_regen.py:89-135` | `test_ai_service.py`, `test_ai_lead_regen_stale.py`; live audit `AI_SUMMARY_ACCURACY_AUDIT.md` 14/15 pass | Cached prod summaries stay stale until regenerated |
| 46 | Today's Leads = last 24 h | **Done with notes** | `lead_overview_service.py:106-139` rolling 24 h clamped to now | `test_lead_overview_unit.py:248,269`; e2e "#46/#48 Today's Leads tile shows rolling 24h + re-enquiry copy" | Prod: **0** leads with future `created_at_dt`. Rolling 24 h, not business-hours based. |
| 47 | Marketing dashboard data / Meta import | **Not done** | `marketing.py:26-104` manual spend CRUD only; `MarketingDashboardPage.js` is an "Add spend" form; no Meta Insights call anywhere | — | Marked "skipped, out of scope" on 2026-09-04. Needs a client decision. |
| 48 | Re-enquiry leads in Today's bucket | **Done** | `lead_overview_service.py:136-139` (`re_enquired_at` in IST day), set in `lead_intake_service.py:587` | `test_lead_overview_unit.py:282`, `test_lead_list_query.py:58`; same e2e | — |
| 49 | Lead Overview: Email + Lost Reason | **Done** | `DataDnaGrid.jsx:140-141,206-207` | `test_lost_reason_unit.py`; e2e "#49 DataDna Lead Overview shows Email + Lost Reason fields" | — |
| 50 | Received list excludes leads I re-assigned | **Done** | `transfer_queries.py:61-83` still-owned filters used in `transfers.py:28-36`, `my_dashboard.py:103-140`, `lead_overview_service.py:351-362` | `test_transfers_still_owned_unit.py`, `test_transfer_queries_unit.py`; e2e "#50 Received transfers only shows leads still assigned to me" | — |
| 51 | Location interested multi-select | **Partial** | VC **filter** is multi-select (`VirtualCustomerPage.js:1250-1258`, `lead_search.py:260,286`) | e2e "#51 Location interested filter label + exact match" | The lead's own Location field is still a single value (`DataDnaGrid.jsx:86-92,552`) |
| 52 | Channel-partner integration | **Not done (generic intake only)** | API-key intake `lead_intake.py:38` + `docs/lead-intake-api.md`; Webflow/Zapier webhooks | `test_lead_intake_unit.py`, `test_webflow_leads_unit.py` | "channel partner" exists only as a source value (2,289 leads). No partner entity, form, or attribution. Marked "skipped" 2026-09-04. |
| 53 | Permanent Site Visit log | **Done with notes** | Append-only `site_visit_events.py:28-56` written on Visit Completed (`lead_service.py:934-935`); backfill `scripts/backfill_site_visit_events.py`; page `SiteVisitsPage.js` | `test_site_visit_events_unit.py`, `test_visit_completed_event_integration_unit.py`; e2e "#53/#54 Site visit completion is logged and reported by project" | Prod: **113** events; project values are un-normalised ("Vivriti", "OMR - Vivriti", "OMR - Vivriti; ECR - Reserve 16", `None`…) so per-project totals split. Report shows totals only, no per-lead list; admin/manager only (GM excluded). |
| 54 | Site Visit report filters | **Done with notes** | `site_visit_events.py:59-155` week/month/quarter/custom + owner; `analytics.py:608-639` | same | Groups by primary project only |
| 55 | "All Leads" 16,787 vs VC 13,384 | **Partial — root cause found** | Tile uses `rep_lead_filter` (`dashboard_scope.py:21-28`: `assigned_user_id` **or** name fields); VC Sales Owner filter uses names only (`lead_search.py:205-212`) | `test_lead_list_query.py` (tile drill-down path only) | Prod today: tile-style count for Admin **16,807**, VC "Admin" name filter **13,416**, difference **3,391** = leads whose `assigned_user_id` is the Admin account but `assigned_to`/`assigned_to_name` = **"Roshini"** (2,508 New, 264 Unqualified, 210 Junk, 130 Contacted…). Fix is either a data backfill of the name fields or making the VC owner filter match on user id. **Not fixed.** |
| 56 | Follow-up Today empty at login | **Partial / not reproducible** | `MyDashboardPage.js:283-301` loads overview first; list loads via search effect `:346-356` | none targeted | No commit or test addresses this symptom; could not reproduce on e2e stack. Needs a live repro. |
| 57 | Count of missed pick-ups per agent | **Partial** | Call attempt totals `call_stats.py:11-32`, RNR attempts per agent `:52-82`; shown `DigitalTwinPage.js:1049-1054,1208-1211`; MCUBE missed inbound only notifies (`mcube/process.py:158-218`) | `test_lead_call_attempt_count.py` | Prod: 1,799 leads have call-attempt timeline entries. No "missed pickup" counter per agent. |
| 58 | Related / linked leads (Phase 2) | **Not started** | No `related_leads`/`linked_*` fields anywhere; only `merge_leads` (`lead_service.py:1225`) | — | Prod: 0 leads with such fields. Client labelled this Phase 2. |

---

## 3. Backend test evidence (unit / integration)

Command (from `backend/`): `python -m pytest -q -p no:cacheprovider tests`
Result line: `11 failed, 638 passed, 4 skipped, 383 warnings, 66 errors in 34.87s`

Tracker-mapped suites, all **passed**:

| Rows | Test files |
|---|---|
| 2 | `test_edit_note_mongo_index.py` |
| 6 | `test_missed_follow_up_clear.py`, `test_lead_follow_up.py` |
| 8, 38, 40 | `test_sla_escalation_queue_t10.py`, `test_escalation_legacy_backfill.py`, `test_sla_escalation_fanout.py`, `test_roles_unit.py` |
| 9 | `test_lead_export.py`, `test_list_lead_projection.py` |
| 15 | `test_lead_filter_views.py`, `test_lead_filter_views_owners_unit.py` |
| 21, 31, 52 | `test_lead_intake_unit.py`, `test_zapier_leads_unit.py`, `test_webflow_leads_unit.py` |
| 22 | `test_whatsapp_send_pricing.py`, `test_whatsapp_attachment_unit.py` |
| 23 | `test_rnr_metric_clause_unit.py`, `test_sla_rnr_*.py` |
| 24, 30, 46, 48 | `test_lead_overview_unit.py`, `test_my_dashboard_whatsapp_unit.py`, `test_dashboard_scope_unit.py` |
| 25 | `test_ist_wall_to_utc_unit.py`, `test_coerce_datetime_unit.py` |
| 27 | `test_wa_unknown_lead_unit.py`, `test_wati_message_content_unit.py`, `test_whatsapp_inbox_unit.py` |
| 28 | `test_lead_project_fields_unit.py` |
| 32 | `test_nudge_unit.py`, `test_nudge_pending_unit.py` |
| 33 | `test_bulk_update_unit.py` |
| 39, 44 | `test_note_notify_unit.py`, `test_notification_create.py`, `test_notifications_auto_scope.py` |
| 43 | `test_sla_reengaged_no_gone_cold.py`, `test_active_pipeline_filter.py` |
| 45 | `test_ai_service.py`, `test_ai_lead_regen_stale.py` |
| 49 | `test_lost_reason_unit.py` |
| 50 | `test_transfers_still_owned_unit.py`, `test_transfer_queries_unit.py` |
| 53, 54 | `test_site_visit_events_unit.py`, `test_site_visit_count.py`, `test_visit_completed_event_integration_unit.py` |
| 55 | `test_lead_list_query.py`, `test_lead_search_unit.py` |
| 57 | `test_lead_call_attempt_count.py`, `test_call_outcomes_phase3.py` |

Failures / errors, none tracker-related:

- 66 errors + 8 failures: legacy HTTP integration suites (`test_my_dashboard.py`, `test_new_features.py`, `test_gupshup_whatsapp.py`, `test_platform_ops.py`, `test_auth_refresh_and_campaigns.py`). They read `REACT_APP_BACKEND_URL` and log in as `roshini@arihant.com / arihant123`; those credentials do not exist on the e2e database (re-run with the API up: `1 failed, 10 passed, 34 skipped, 26 errors`, all credential `KeyError`s). They predate the tracker work.
- 3 failures in `test_routing_manual_status.py`: patch target mismatch (`from crm.utils.business_time import is_business_hours_ist` at `assignment_router.py:23`), so the tests depend on the wall clock and fail outside IST business hours. Test-hygiene issue, not a product defect.

`scripts/verify_change_tracker_live.py`: 17/19 PASS; the two FAILs ("sla reassign uses 3600", "patch_context does not always set recent_note") are string checks against code that the phase-3 rewrite legitimately moved (`sla_engine.py:572,615` still use 3600 s; recent-note sync now at `tasks.py:280-282`).

---

## 4. Playwright browser evidence (disposable e2e database)

Stack: local API on `127.0.0.1:8000` started strictly from `backend/.env.e2e` (`DB_NAME=arihant_crm_e2e`, Atlas test cluster `cluster0.zdfddmi`), Vite on `127.0.0.1:3000`, Chromium, WATI mocked in the browser, `WHATSAPP_PROVIDER=disabled`. Users seeded by `scripts/seed_e2e_users.py` (admin, rep, manager, GM = Shariff).

Full run `npx playwright test --reporter=list` (41 tests, 14.1 min): **36 passed, 2 failed, 3 skipped**.
- The 2 failures were infrastructure, not assertions: `#23` "TypeError: fetch failed … ECONNRESET" (local socket reset), `#51` "Test timeout of 120000ms exceeded" (page load stall). Both spec files run in `serial` mode, so the 3 tests after them (`#24`, `#25`, `#53/#54`) were skipped.
- Targeted reruns of exactly those 5 tests: **5 passed** (`#23` 7.8 s, `#51` 21.9 s, `#24` 9.4 s, `#25` 5.2 s, `#53/#54` 15.4 s).
- **Net: 41 / 41 tracker and safety tests passed** across the run plus reruns. Raw logs: scratchpad `playwright_run2.txt`, `playwright_retry.txt`, `playwright_retry2.txt`; HTML report `frontend/playwright-report/`.

| Spec | Tests (all passed) |
|---|---|
| `safety.spec.js` | config accepts local e2e; refuses production DB name; refuses live API host |
| `tracker-02-25.spec.js` | #3 WhatsApp in left nav · #2 Edit note persists, no delete · #4 inbound WA reply notifies assignee · #5 RNR does not auto-reassign ownership · #6 note clears Missed Follow-ups · #7 Back to Explorer sticky · #8 Escalation queue reachable for admin · #9 #10 #18 #19 #40 #41 #42 VC columns · #11 filters survive Back to Explorer · #12 #13 org dashboard status chart + time filter drill to VC · #15 saved view keeps sales owner + status · #16 VIP tag editable · #22 per-project brochure buttons (mocked WATI) · #23 RNR queue drill-down current RNR only · #24 Unqualified card · #25 task 11:00 IST stores 05:30 UTC |
| `tracker-26-36.spec.js` | #36 notification click navigates to lead · #27 #26 #34 WA inbound → Admin lead, Replied chip, recent note · #31 Zapier Meta timeline shows project · #28 multi-project filter · #32 nudge + VC nudge filter until assignee acts · #29 VC filter bar sticky · #30 My Dashboard WhatsApp tab · #33 bulk select + bulk status · #35 template params edited before send · WA inbox attach sends multipart |
| `tracker-37-45.spec.js` | #37 View All shows read + unread · #38 Escalations allowed for admin/manager/GM, denied for rep · #39 #44 cross-assignee note + mention notify · #39b inline @mention · #44 create-lead Additional Notes @mention · #43 dormant chip not shown from legacy URL |
| `tracker-46-54.spec.js` | #46/#48 Today's Leads rolling 24h + re-enquiry · #49 DataDna Email + Lost Reason · #50 Received transfers only still-assigned · #51 Location filter label + exact match · #53/#54 site visit logged and reported by project |
| `whatsapp-inbox-restore.spec.js` | returns to same thread after Open Lead Overview and back |

Note on #38: the e2e test logs the manager in and checks the **page** is reachable; it does not exercise the `escalated=true` list call, which is where the manager 403 (#8) occurs.

Cleanup: after the runs the e2e database holds 0 leads with `e2e_run_id`, 0 `E2E_*` names, 0 `lead_source=E2E`; only the 4 seeded users and 2 pre-existing sample leads remain.

---

## 5. Production read-only snapshot (aggregate counts only, 2026-09-27 02:19 IST)

Script: scratchpad `prod_snapshot_readonly.py` (pymongo, `count_documents`/`distinct`/`aggregate` only; no writes). Total leads: **30,159**.

```
# #17 sources
  aurum analytica: 491
  management* (any): 26   -> values: 'management reference', 'management referral'
  empty/null source: 7903
  channel partner: 2289
# #43 statuses
  Dormant: 0
  Gone Cold: 1634
# #8/#38/#40 roles
  users by role: admin 4, rep 7, general_manager 1, manager 0
  shariff@arihants.co.in: role=general_manager, is_active=True
# #9 / #46 timestamps
  leads missing updated_at_dt: 0 | missing updated_at: 0 | created_at_dt in future: 0
# #26 / #27 WhatsApp
  whatsapp_replied=true: 289 | leads with WhatsApp/WATI source: 1721
# #53 site visits
  site_visit_events: 113 | leads with site_visit_count>0: 289
  distinct event projects: None, 'Abhiramapuram - Krishna', 'ECR - Reserve 16', 'Krsna', 'Mélange',
    'OMR - Vivriti', 'OMR - Vivriti; ECR - Reserve 16', 'OMR - Vivriti; Saligramam Melange', ... 'Vivriti'
# #57 calls
  calls: 50 | mcube_events: 134 | leads with call-attempt timeline entries: 1799
# #55 All Leads scope (Admin account = roshni@arihantspaces.com)
  tile rep_lead_filter (id OR name): 16807 | VC sales_owner name filter "Admin": 13416 | assigned_user_id only: 16298
  assigned_user_id=Admin but name != Admin: 3391  -> all have assigned_to/assigned_to_name = 'Roshini'
    status split: New 2508, Unqualified 264, Junk 210, Contacted 130, Gone Cold 75, RNR 62, Visit Completed 42, SV Scheduled 37
# #58
  leads with related/linked fields: 0
```

---

## 6. Screenshots (local e2e stack, admin login)

Folder: `docs/verification-screens/2026-09-27/` (1440×900, taken by a Playwright script that created one tagged lead "E2E_… Lead", projects Vivriti + Reserve 16, then cleaned it up).

| File | Rows | What it shows |
|---|---|---|
| `10-18-19-40-41-42_virtual-customer-columns.png` | 10, 18, 19, 40, 41, 42 | VC table: Name → **Phone (bold)** → Status → Next follow-up → Active tasks → **Project (bold, "Vivriti; Reserve 16")** → Source → Recent note …; filter bar with Location / Project / Source / Status / Sales Owner / Date / VIP / Re Enquiry / Nudge / Views / Save view |
| `08-40_escalation-queue-admin.png` | 8, 40 | Escalation Queue as admin, VC-style table |
| `24-46-48_my-dashboard-unqualified-todays-leads.png` | 24, 46, 48 | My Dashboard overview cards incl. Unqualified and Today's Leads copy |
| `30_my-dashboard-whatsapp-tab.png` | 30 | WhatsApp tab tiles under My Dashboard |
| `36-37_notification-panel.png`, `37_notifications-view-all.png` | 36, 37 | Bell panel and the full Notifications page |
| `53-54_site-visits-report.png` | 53, 54 | Site Visits report with Week/Month/Quarter/Custom + Sales owner filters |
| `12-13_org-dashboard-status-distribution-filters.png` | 12, 13 | Org Dashboard status distribution with 7/15/30/All/Custom filter |
| `02-16-28-49_lead-profile-datadna.png` | 2, 16, 28, 49 | Lead profile: edit-note pencil, VIP toggle, multi-project chips, Email + Lost Reason fields |
| `22-35_whatsapp-dialog-brochure-buttons.png` | 22, 35 | WhatsApp dialog: brochure buttons **Mélange, Reserve 16, Krsna, Vivriti** (no Vipassana), template quick-fills |
| `03-27-29-34_whatsapp-inbox.png` | 3, 27, 29, 34 | WhatsApp inbox page reached from the left nav |

---

## 7. Open items needing a client or product decision

1. **#5 RNR auto-transfer** — code exists behind `SLA_PHASE3_RULES_ENABLED` (off). Decide: keep "admin tasks only" (current) or enable transfer.
2. **#8/#40 manager 403** — align `can_filter_escalated_leads` with `ESCALATION_ROLES` (or remove `manager` from the frontend guard). No manager accounts exist today.
3. **#33 GM bulk-assign 403** — either allow `general_manager` in `bulk_update_leads` or hide the control for GM.
4. **#21 WA ack for walk-ins** — add a "manual/walk-in" exclusion, or confirm "all New leads" stands.
5. **#22 Vipassana brochure** — needs the PDF + one entry in the brochure map and both button lists.
6. **#43 Gone Cold resurfacing** — the 30-day task exists but Follow-up Today excludes Gone Cold; decide where the reminder should appear.
7. **#51 Location on the lead** — filter is multi, field is single.
8. **#55 All Leads mismatch** — 3,391 leads with owner name "Roshini" under the Admin user id; backfill names or match by id in the VC owner filter.
9. **#47 Marketing / Meta import**, **#52 Channel-partner integration**, **#58 Related leads** — not built; scope decisions.
10. **#56 Follow-up Today empty at login** — not reproducible; needs a live repro (user, time, browser).
11. **#57 missed pick-up count** — define the metric (missed inbound per agent? RNR attempts?) before building.

## 8. Delta versus the 2026-09-04 report

- Escalation Queue was rewritten (phase 3): now a Virtual-Customer-style page with a 13-pair SLA whitelist and legacy backfill. The manager 403 mismatch is new.
- RNR SLA moved to a phase-3 ladder behind a feature flag; earlier report's "tasks only" decision still describes production.
- Rows 55–58 are new and were not previously assessed.
- Live counts: Aurum 491 (unchanged), Dormant 0 (unchanged), "All Leads" gap now explained with data (3,391 "Roshini"-named leads).

## 9. How to reproduce

```powershell
# Backend unit tests (no DB writes)
cd backend
python -m pytest -q -p no:cacheprovider tests
$env:PYTHONPATH='.'; python scripts/verify_change_tracker_live.py

# e2e stack (disposable DB only) — load .env.e2e with python-dotenv override, never via shell `source`
#   (the MONGO_URL contains '&', which a shell source truncates and silently falls back to backend/.env)
python -c "from dotenv import load_dotenv; load_dotenv('.env.e2e', override=True); import uvicorn; uvicorn.run('crm.main:app', host='127.0.0.1', port=8000)"
cd ../frontend; npx vite --host 127.0.0.1 --port 3000      # Vite must bind IPv4 for Playwright's 127.0.0.1 baseURL
npm run test:e2e:safety; npx playwright test --reporter=list

# Production read-only snapshot: see scratchpad prod_snapshot_readonly.py (counts only)
```

## 10. Incident note (verification run)

The first API start for e2e used a shell `source` of `.env.e2e`; the `&` in the Atlas URL truncated `MONGO_URL`, so the API fell back to the `.env` cluster with database name `arihant_crm_e2e`. Nothing could log in, so no test data was written. The start-up did create an **empty `arihant_crm_e2e` database on the production cluster** (`qlink-cluster.4bmep.mongodb.net`) containing only schema indexes, 6 default `alert_configs`, and 2 synthetic inbound `whatsapp_messages` from the webhook helper. The production `arihant_crm` database was not modified. Recommended cleanup (developer decision): drop database `arihant_crm_e2e` on that cluster. The launcher was replaced by a python-dotenv loader with a host assertion before the successful run.
