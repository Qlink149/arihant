# Production seed checklist (`seed_db_v2.py`)

Use this before writing to the main production MongoDB.

1. **Staging / disposable database** — Run the full seed against a non-production `DB_NAME` (or separate cluster) first.
2. **Dry run** — `python backend/seed_db_v2.py --dry-run` and inspect the printed sample lead (context_updates, project, status, DNA fields).
3. **CSV inputs** — Confirm `Contacts.csv` is present; optional files (Notes, Calls, FreshSales organized) are the versions you expect.
4. **Flags** — Default: no synthetic “Imported via seed_db_v2” timeline row. Use `--include-seed-marker` only for debugging.
5. **Upsert vs drop** — Prefer `--upsert` for incremental re-runs on production; use drop only when intentionally resetting dev/staging.
6. **Post-seed validation** — Log into the app and verify: main dashboard project distribution, sales dashboard totals vs Mongo counts, Virtual Customer list, Digital Twin timeline, notifications.
7. **Backup** — Take a Mongo backup or snapshot before the first production import.
