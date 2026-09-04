# Change Tracker Verification Report (#2–#54)

**Date:** 2026-09-04 (IST)  
**Scope:** Client change-tracker rows 2–54  
**Environments:** Production Mongo `arihant_crm` (read-only) · Disposable `arihant_crm_e2e` (writes + Playwright)  
**Playwright:** `frontend/e2e/safety.spec.js`, `tracker-02-25.spec.js`, `tracker-26-36.spec.js`, `tracker-37-45.spec.js`, `tracker-46-54.spec.js`

## Summary

| Verdict | Count | Notes |
|---------|------:|-------|
| **Done** | ~47 | Implemented and verified; product decisions locked 2026-09-04 |
| **Done with notes** | ~3 | #12/#13 (client wording), #17 sources, #45 AI live audit |
| **Partial** | 0 | — |
| **Remaining / skipped** | 3 | #14 open; #47/#52 skipped by request |

Product decisions locked (no further code change): **#5, #12/#13, #19, #21, #38** accepted as shipped. Test-harness only in this verification pass.

### Playwright result (this pass)

- Tracker **02–25:** 16/16 passed (individually and in full suite run)
- Tracker **26–36 / 37–45 / 46–54:** 18/18 passed in dedicated run
- Full suite including safety: see latest `npm run test:e2e` / Playwright list output

### Production read-only snapshot

- Shariff: `shariff@arihants.co.in` → role **`general_manager`**
- `aurum analytica` leads: **491** (no longer collapsed into management ref at scale)
- `management*` sources: **26**
- `channel partner` source value exists (**2244** leads) — label only, not an integration
- Status `Dormant`: **0**; `Gone Cold` present in distinct statuses
- GM users count: **1**

---

## Line-by-line

| # | Client ask (short) | Verdict | Evidence | Remaining / notes |
|---|--------------------|---------|----------|-------------------|
| 2 | Edit notes (no delete) | **Done** | PATCH context; Digital Twin edit pencil; e2e #2 | — |
| 3 | WhatsApp left nav | **Done** | `DashboardLayout` + `/whatsapp`; e2e #3 | — |
| 4 | Notify on WA reply | **Done** | webhook → `whatsapp_reply`; e2e #4 | Notifies any inbound reply, not only “after auto template” |
| 5 | Auto transfer RNR leads | **Done** | SLA creates **admin tasks**, not ownership move; e2e #5 asserts owner stays | Accepted: escalation tasks (not auto-reassign) is the intended design |
| 6 | Missed Follow-ups clear after update | **Done** | `clear_missed_follow_up_after_activity`; e2e #6 | — |
| 7 | Freeze Back to Explorer | **Done** | sticky bar; e2e #7 | — |
| 8 | Escalation Queue (Admin) | **Done** | Also manager + GM; e2e #8 / #38 | Broader ACL than “Admin only” |
| 9 | Updated At timestamp | **Done** | VC Updated column + IST time; e2e #9… | — |
| 10 | Phone bold | **Done** | `font-semibold` on phone; e2e #9… | — |
| 11 | Retain filter/scroll after lead | **Done** | URL filters + `vc_list_restore`; e2e #11 (`agent` + `projects`) | Search URL key is `agent`, not `search` |
| 12 | My Dashboard status → VC | **Done** | Org **Dashboard** pie + My Dashboard overview cards drill to VC; e2e #12/#13 | Accepted; optional client note: pie lives on org Dashboard |
| 13 | Date/month filter on status distribution | **Done** | 7/15/30/all/custom; e2e #12/#13 | Accepted; optional client note: presets + custom range (not a single “month” control) |
| 14 | Follow-up date without task | **Skipped / open** | Product still in discussion | Do not implement until sales decides |
| 15 | Saved View filters | **Done** | filter-views API + VC bar; e2e #15 | — |
| 16 | Edit VIP tag | **Done** | `toggle-vip`; e2e #16 | — |
| 17 | Lead source mismatch counts | **Done with notes** | Prod: Aurum=491 distinct; picklists canonical | Historical empty/`management` variants remain; seed scripts can still collapse — monitor filters |
| 18 | Phone column next to name | **Done** | Name → Phone columns; e2e #9… | — |
| 19 | Sales Owner at end of table | **Done** | After Recent note, before Created/Updated/Actions | Accepted: Owner before Created/Updated (those columns added later for #40/#41) |
| 20 | AI RNR acronym | **Done** | Prompt grounding in `ai_service.py` | Prompt-only; LLM can still err |
| 21 | WA ack only for New; not walk-in/manual | **Done** | Ack fires when status is **New** (including manual/walk-in New) | Accepted: send ack for all New leads |
| 22 | Per-project brochure buttons | **Done** | 4 project buttons; mocked e2e #22 | — |
| 23 | RNR Queue = current RNR only | **Done** | `rnr_metric_clause`; e2e #23 | — |
| 24 | Unqualified card My Dashboard | **Done** | overview metric; e2e #24 | — |
| 25 | Task time IST (11:00→5:30 bug) | **Done** | `ist_wall_to_utc_dt`; e2e #25 stores 05:30 UTC | — |
| 26 | WA replied tag/color | **Done** | VC badge + inbox chip; e2e #26/#27/#34 | — |
| 27 | Unknown WATI → New lead | **Done** | webhook create; e2e combined | Local webhook only |
| 28 | Multi-select project | **Done** | DataDna + list filter; e2e #28 | — |
| 29 | Freeze VC header/filters | **Done** | sticky; e2e #29 | — |
| 30 | WA dashboard under My Dashboard | **Done** | tab + tiles; e2e #30 | — |
| 31 | Meta Zapier resub + project | **Done** | intake description; e2e #31 (fixture display) | Live Zapier POST not hit in e2e |
| 32 | Admin Nudge → notify | **Done** | `nudge_pending` flag + VC Nudge chip; clears on assignee act; e2e #32 | No historical backfill of old nudges |
| 33 | Bulk select / assign | **Done** | bulk status + assign in e2e #33 | Admin/manager only |
| 34 | WA RHS recent note | **Done** | under Assignee; e2e combined | — |
| 35 | Template edit before send | **Done** | mocked WATI; e2e #35 | — |
| 36 | Notification click → lead | **Done** | e2e #36 | — |
| 37 | View all alerts | **Done** | Notifications page history; e2e #37 | — |
| 38 | Escalation like VC + Admin/Shariff | **Done** | ACL admin/manager/GM; dedicated queue UI | Accepted: dedicated Escalation Queue (not a VC clone) |
| 39 | Cross-assignee notes + notify | **Done** | e2e #39/#44 | — |
| 40 | Created date column | **Done** | e2e #9… | — |
| 41 | Created/Updated with time | **Done** | IST datetime; e2e #9… | — |
| 42 | Project bold / visible | **Done** | `font-semibold`; e2e #9… | — |
| 43 | Remove Dormant | **Done** | dormant URL ignored; Gone Cold status; e2e #43 | Leftover label key `dormant` in `leadOverview.js` map (not a live tile) |
| 44 | @tag agents on notes | **Done** | mentions + picker; e2e #39/#44 | — |
| 45 | AI Summary accuracy | **Done with notes** | Live audit 15 prod leads on `openai/gpt-oss-120b`: **14 PASS / 1 WEAK / 0 FAIL** ([AI_SUMMARY_ACCURACY_AUDIT.md](./AI_SUMMARY_ACCURACY_AUDIT.md)) | Model migrated from retired `llama-3.3-70b-versatile`. WEAK: ***3907** (lost_reason wording soft). Prod UI still shows stale Aug caches until regen. |
| 46 | Today's Leads last 24h | **Done** | rolling 24h clamped to `<= now` (excludes future `created_at_dt`); Dashboard copy; e2e #46/#48 | Future-date audit: [FUTURE_CREATED_AT_AUDIT.md](./FUTURE_CREATED_AT_AUDIT.md) |
| 47 | Marketing dashboard data | **Skipped** | Manual spend page exists; no Meta import | Out of scope per you |
| 48 | Re-enquiry in Today's leads | **Done** | IST-day `re_enquired_at`; e2e + unit | — |
| 49 | DataDna Email + Lost Reason | **Done** | e2e #49 | — |
| 50 | Received = still assigned to me | **Done** | still-owned filter; e2e #50 API+UI | — |
| 51 | Location interested multi-select | **Done** | multi UI + **exact** match; e2e #51 | Exact match (not substring); multi via `locations[]` |
| 52 | Channel partner integration | **Skipped** | Source picklist only | Out of scope per you |
| 53 | Site visit events persist | **Done** | append-only events; e2e #53/#54 | — |
| 54 | Site visit report filters | **Done** | `/site-visits` admin/manager; e2e #53/#54 | GM has escalations but not this report (`OrgEditorRoute`) |

---

## Product decisions locked (2026-09-04)

| # | Decision |
|---|----------|
| **5** | Keep RNR → admin SLA **tasks** (no ownership auto-transfer). |
| **21** | Send WhatsApp ack for **all New** leads (including walk-in / manual). |
| **12 / #13** | Accept as shipped; send client a short clarity note (draft below). |
| **19** | Accept Sales Owner column position (before Created/Updated). |
| **38** | Accept dedicated Escalation Queue for Admin / manager / GM (Shariff). |

### Optional client message (#12 / #13)

> Lead Status Distribution is on the main **Dashboard** (org view). Clicking a status slice opens Virtual Customer filtered to that status. My Dashboard uses the lead-overview cards for the same drill-down. Time windows are **7 / 15 / 30 days, All time, or Custom range** (IST) — not a separate “pick a calendar month” control.

Still open / skipped: **#14** (follow-up without task — internal), **#47** Marketing, **#52** Channel partner. **#45** Done with notes (live prompt accurate; prod caches stale until regen — [AI_SUMMARY_ACCURACY_AUDIT.md](./AI_SUMMARY_ACCURACY_AUDIT.md)).

---

## Test artifacts

| Path | Role |
|------|------|
| [frontend/e2e/tracker-02-25.spec.js](../frontend/e2e/tracker-02-25.spec.js) | New coverage for early tracker rows |
| [frontend/e2e/tracker-26-36.spec.js](../frontend/e2e/tracker-26-36.spec.js) | Tightened #32 notify, #33 bulk assign |
| [frontend/e2e/tracker-46-54.spec.js](../frontend/e2e/tracker-46-54.spec.js) | Tightened #48 re-enquiry, #50 UI, #51 exact location |
| [backend/scripts/e2e_fixtures.py](../backend/scripts/e2e_fixtures.py) | ISO date strings coerced for `*_at` / `*_dt` patches |
| [backend/scripts/audit_ai_summary_accuracy.py](../backend/scripts/audit_ai_summary_accuracy.py) | #45 prod read-only live LLM accuracy audit |
| [backend/scripts/audit_future_created_at.py](../backend/scripts/audit_future_created_at.py) | Read-only future `created_at_dt` audit (Today's New Leads pollution) |
| [docs/FUTURE_CREATED_AT_AUDIT.md](./FUTURE_CREATED_AT_AUDIT.md) | Future-date findings + repair plan; Junk status policy for todays_leads |
| [docs/AI_SUMMARY_ACCURACY_AUDIT.md](./AI_SUMMARY_ACCURACY_AUDIT.md) | #45 live accuracy audit (`openai/gpt-oss-120b`, 14/15 PASS) |

## Cleanup

E2E specs call `cleanupRun` in `afterAll`. Prefer re-running Playwright (or `scripts/e2e_cleanup.py --run-id …`) if any `E2E_*` leads remain after an aborted run.
