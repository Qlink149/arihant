# Delivery readiness — Arihant CRM

## Deployment

**Always deploy from the `backend/` directory.** The authoritative Vercel config is `backend/vercel.json` (includes `process-slas` and `nurturing-review` crons). The root `vercel.json` was removed to prevent misconfiguration.

User provisioning (no public signup):
- First admin: `python scripts/create_admin.py` (`ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NAME`)
- Reps/managers: `python scripts/create_user.py` (`USER_EMAIL`, `USER_PASSWORD`, `USER_NAME`, `USER_ROLE=rep`)
- Or logged-in admin: `POST /api/auth/admin/create-user`
- Do **not** set `ALLOW_PUBLIC_REGISTRATION=true` in production (`POST /auth/register` is disabled by default).

## Dashboard UX (this sprint)

- Main dashboard stat tiles navigate to **Virtual Customer** with matching org-wide filters.
- **All Projects** and **date** filters (7/15/30 days, custom range) refresh analytics counts.
- Drill-down passes `project`, `days`, `created_from`/`created_to`, plus tile-specific filters (`dormant`, `vip`, `metric=qualified_leads`, Nurturing + Hot).

## SLA pipeline (Q1–Q9)

Implemented in code. **Production requires:**

1. `CRON_SECRET` in Vercel/backend env.
2. Vercel crons: `process-slas` (every minute) and `nurturing-review` (`30 3 * * *` UTC).
3. Optional: Brevo keys in Settings or env (`BREVO_*`, `DASHBOARD_URL`).

WhatsApp auto-send and inbound Re-engaged remain **disabled** by design.

## 15-minute smoke test

1. Login as admin → Dashboard: change **7 Days** and a **project** → counts update.
2. Click **Dormant**, **Total**, **VIP**, **Hot**, **Qualified** → Virtual Customer opens with chip/filters; total roughly matches tile.
3. `POST /api/v1/cron/process-slas` with `Authorization: Bearer <CRON_SECRET>` → 200.
4. Lead → **Visit Completed** → complete post-visit task with **outcome** required.
5. Notifications: **Overdue** badge on stale SLA items.

## Known gaps (client conversation)

| Area | Notes |
|------|--------|
| Dashboard scope | Analytics and lead list are **rep-scoped**; admin/manager see org-wide. My Dashboard stays personal for all roles. |
| Nurturing Hot = 0 | Often **data** (no leads with status Nurturing + temperature Hot). |
| Notifications dormant | Auto alerts use `updated_at` string; dashboard dormant uses `updated_at_dt` + terminal exclusions — counts may differ slightly. |
| SLA in prod | Without cron secret + schedules, SLAs do not run. |
| env templates | Use `backend/env.example` (README); `backend/.env.example` is a legacy duplicate. |
| Integration tests | Some pytest suites expect API on `localhost:8000`. |

## Env reference

Copy `backend/env.example` → `backend/.env` and `frontend/.env.example` → `frontend/.env`.

Key vars: `MONGO_URL`, `DB_NAME`, `SECRET_KEY`, `CRON_SECRET`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `BREVO_*`.
