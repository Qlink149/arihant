#!/usr/bin/env python3
"""
purge_sla_data.py
=================
Remove ALL artefacts created by the SLA engine (tasks, notifications, audit
events) and reset SLA idempotency flags on leads.

Does NOT remove:
  - Manually created tasks (no source="sla" / sla_rule / SLA dedupe_key)
  - Reminder-cron data (db.reminders) — use --include-reminders to wipe those too
  - Lead status / assignee (unless --revert-lead-mutations)

What this script cleans:
  1. tasks          — source="sla", created_by="SLA Engine", sla_rule set, dedupe_key^="sla:"
  2. notifications  — type sla_task/sla_alert, title^="SLA:", dedupe_key^="sla:" / "notif:sla:",
                      or task_id pointing at an SLA task
  3. lead_events    — event_type="sla_action" AND actor_name="SLA Engine"
  4. failed_email_queue — template_name="sla_alert" (optional, always on)
  5. leads          — unsets sla_flags + SLA helper fields (keeps sla_paused untouched)
  6. cron_locks     — process_slas lock

Optional:
  --recompute-next-action   Re-sync next_action_date from remaining (non-SLA) tasks
  --revert-lead-mutations   Revert SLA-forced lead_status changes (use with care)

Usage
-----
  # Preview only (no writes)
  python backend/scripts/purge_sla_data.py --dry-run

  # Delete everything SLA-created + reset flags (recommended)
  python backend/scripts/purge_sla_data.py

  # Also fix follow-up / missed-follow-up tiles after task removal
  python backend/scripts/purge_sla_data.py --recompute-next-action

  # Recompute only (skip purge) — after SLA tasks already deleted
  python backend/scripts/purge_sla_data.py --recompute-only

  # Target a specific time window (ISO-8601 UTC)
  python backend/scripts/purge_sla_data.py --since 2026-06-17T00:00:00Z
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ.get("MONGO_URL", "")
DB_NAME = os.environ.get("DB_NAME", "")

SLA_CRON_LOCK_JOB = "process_slas"

LEAD_SLA_UNSET_FIELDS = {
    "sla_flags": "",
    "fp_cycle_count": "",
    "fp_last_checkin_task_created_at_dt": "",
    "sv_followup_delayed": "",
    "follow_up_delayed": "",
}


def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _ts_filter(since: datetime | None, until: datetime | None, field: str = "created_at_dt") -> dict:
    if not since and not until:
        return {}
    clause: dict = {}
    if since:
        clause["$gte"] = since
    if until:
        clause["$lte"] = until
    return {field: clause}


def _sla_task_filter(ts: dict) -> dict:
    """Mongo filter for tasks created by the SLA engine."""
    fingerprints = [
        {"source": "sla"},
        {"created_by": "SLA Engine"},
        {"sla_rule": {"$exists": True, "$nin": [None, ""]}},
        {"dedupe_key": {"$regex": r"^sla:", "$options": "i"}},
    ]
    base: dict = {"$or": fingerprints}
    if ts:
        return {"$and": [base, ts]}
    return base


def _sla_notification_filter(ts: dict, sla_task_ids: list[str]) -> dict:
    """Mongo filter for in-app notifications emitted by the SLA engine."""
    clauses: list[dict] = [
        {"type": {"$in": ["sla_task", "sla_alert"]}},
        {"title": {"$regex": r"^SLA:", "$options": "i"}},
        {"dedupe_key": {"$regex": r"^(notif:)?sla:", "$options": "i"}},
    ]
    if sla_task_ids:
        clauses.append({"task_id": {"$in": sla_task_ids}})
    base: dict = {"$or": clauses}
    if ts:
        return {"$and": [base, ts]}
    return base


def _banner(msg: str) -> None:
    print(f"\n{'=' * 60}\n  {msg}\n{'=' * 60}")


async def _collect_sla_task_ids(db, task_filter: dict) -> list[str]:
    ids: list[str] = []
    cursor = db.tasks.find(task_filter, {"_id": 0, "id": 1})
    async for doc in cursor:
        tid = doc.get("id")
        if tid:
            ids.append(tid)
    return ids


async def _recompute_all_next_action_dates(db, *, dry_run: bool) -> int:
    """Sync next_action_date from earliest pending task per lead (batched)."""
    from pymongo import UpdateOne

    due_by_lead: dict[str, str] = {}
    pipeline = [
        {"$match": {"status": "pending", "lead_id": {"$exists": True, "$nin": [None, ""]}}},
        {"$group": {"_id": "$lead_id", "due_date": {"$min": "$due_date"}}},
    ]
    async for row in db.tasks.aggregate(pipeline):
        lid = row.get("_id")
        due_raw = row.get("due_date")
        if lid and due_raw:
            due_by_lead[str(lid)] = str(due_raw).strip()[:10]

    ops: list[UpdateOne] = []
    count = 0
    cursor = db.leads.find({}, {"_id": 0, "id": 1, "next_action_date": 1})
    async for lead in cursor:
        lid = lead.get("id")
        if not lid:
            continue
        count += 1
        due = due_by_lead.get(lid)
        old = str(lead.get("next_action_date") or "").strip()[:10] or None
        if due:
            if old != due:
                ops.append(UpdateOne({"id": lid}, {"$set": {"next_action_date": due}}))
        elif lead.get("next_action_date"):
            ops.append(UpdateOne({"id": lid}, {"$unset": {"next_action_date": ""}}))

    if not dry_run and ops:
        batch_size = 500
        for i in range(0, len(ops), batch_size):
            await db.leads.bulk_write(ops[i : i + batch_size], ordered=False)

    print(f"                pending-task due dates found for {len(due_by_lead)} leads")
    print(f"                lead documents to update: {len(ops)}")
    return count


async def run(
    *,
    dry_run: bool,
    revert_mutations: bool,
    recompute_next_action: bool,
    recompute_only: bool,
    include_reminders: bool,
    since: datetime | None,
    until: datetime | None,
) -> None:
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL and DB_NAME must be set in backend/.env", file=sys.stderr)
        sys.exit(1)

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    mode = "DRY-RUN" if dry_run else "LIVE DELETE"
    title = "SLA Follow-up Recompute" if recompute_only else "SLA Engine Purge"
    _banner(f"{title}  [{mode}]  DB={DB_NAME}")

    if recompute_only:
        if not recompute_next_action:
            recompute_next_action = True
        lead_total = await db.leads.count_documents({})
        print(f"\n[next_action]   recomputing next_action_date for {lead_total} leads")
        if dry_run:
            print("                dry-run — would recompute from remaining pending tasks")
        else:
            updated = await _recompute_all_next_action_dates(db, dry_run=False)
            print(f"                recomputed {updated} leads")
        _banner("Summary")
        if dry_run:
            print("  DRY-RUN — no data was modified.")
        else:
            print("  next_action_date synced from remaining pending tasks.")
        client.close()
        return

    ts = _ts_filter(since, until)
    task_filter = _sla_task_filter(ts)

    # ── 1. TASKS ─────────────────────────────────────────────────────────────
    task_count = await db.tasks.count_documents(task_filter)
    print(f"\n[tasks]         found {task_count:>6} SLA-created tasks")
    sla_task_ids = await _collect_sla_task_ids(db, task_filter)
    if not dry_run and task_count:
        result = await db.tasks.delete_many(task_filter)
        print(f"                deleted {result.deleted_count}")

    # ── 2. NOTIFICATIONS ─────────────────────────────────────────────────────
    notif_filter = _sla_notification_filter(ts, sla_task_ids)
    notif_count = await db.notifications.count_documents(notif_filter)
    print(f"[notifications] found {notif_count:>6} SLA notifications")
    if not dry_run and notif_count:
        result = await db.notifications.delete_many(notif_filter)
        print(f"                deleted {result.deleted_count}")

    # ── 3. LEAD EVENTS ───────────────────────────────────────────────────────
    event_filter: dict = {
        "event_type": "sla_action",
        "actor_name": "SLA Engine",
        **ts,
    }
    event_count = await db.lead_events.count_documents(event_filter)
    print(f"[lead_events]   found {event_count:>6} SLA audit events")
    if not dry_run and event_count:
        result = await db.lead_events.delete_many(event_filter)
        print(f"                deleted {result.deleted_count}")

    # ── 4. FAILED SLA EMAILS ─────────────────────────────────────────────────
    email_filter = {"template_name": "sla_alert", **ts}
    email_count = await db.failed_email_queue.count_documents(email_filter)
    print(f"[failed_emails] found {email_count:>6} queued sla_alert emails")
    if not dry_run and email_count:
        result = await db.failed_email_queue.delete_many(email_filter)
        print(f"                deleted {result.deleted_count}")

    # ── 5. OPTIONAL: REMINDER CRON DATA (not SLA — off by default) ───────────
    if include_reminders:
        reminder_filter = {**ts} if ts else {}
        reminder_count = await db.reminders.count_documents(reminder_filter)
        print(f"[reminders]     found {reminder_count:>6} reminder-cron records (--include-reminders)")
        if not dry_run and reminder_count:
            result = await db.reminders.delete_many(reminder_filter)
            print(f"                deleted {result.deleted_count}")

    # ── 6. RESET SLA FLAGS ON LEADS ──────────────────────────────────────────
    leads_with_flags = await db.leads.count_documents(
        {
            "$or": [
                {"sla_flags": {"$exists": True}},
                {"fp_cycle_count": {"$exists": True}},
                {"fp_last_checkin_task_created_at_dt": {"$exists": True}},
                {"sv_followup_delayed": {"$exists": True}},
                {"follow_up_delayed": {"$exists": True}},
            ]
        }
    )
    print(f"[leads]         found {leads_with_flags:>6} leads with SLA flags/helpers")
    print("                (sla_paused / import_provenance are NOT changed)")

    if not dry_run and leads_with_flags:
        result = await db.leads.update_many(
            {
                "$or": [
                    {"sla_flags": {"$exists": True}},
                    {"fp_cycle_count": {"$exists": True}},
                    {"fp_last_checkin_task_created_at_dt": {"$exists": True}},
                    {"sv_followup_delayed": {"$exists": True}},
                    {"follow_up_delayed": {"$exists": True}},
                ]
            },
            {"$unset": LEAD_SLA_UNSET_FIELDS},
        )
        print(f"                SLA fields unset on {result.modified_count} leads")

    # ── 7. CRON LOCK ─────────────────────────────────────────────────────────
    lock_count = await db.cron_locks.count_documents({"job": SLA_CRON_LOCK_JOB})
    print(f"[cron_locks]    found {lock_count:>6} SLA cron lock(s)")
    if not dry_run and lock_count:
        result = await db.cron_locks.delete_many({"job": SLA_CRON_LOCK_JOB})
        print(f"                deleted {result.deleted_count}")

    # ── 8. OPTIONAL: REVERT LEAD-STATUS MUTATIONS ────────────────────────────
    if revert_mutations:
        _banner("Reverting SLA-driven lead-status mutations")

        mutation_filter: dict = {
            "event_type": "sla_action",
            "actor_name": "SLA Engine",
            "payload.action": "lead_mutation",
            **ts,
        }
        mutation_events = await db.lead_events.find(
            mutation_filter,
            {"lead_id": 1, "payload": 1, "_id": 0},
        ).to_list(length=None)

        print(f"  Found {len(mutation_events)} SLA lead-mutation events")

        affected: dict[str, list[dict]] = {}
        for ev in mutation_events:
            lid = ev.get("lead_id")
            if lid:
                affected.setdefault(lid, []).append(ev.get("payload", {}).get("set_fields", {}))

        print(f"  Affects {len(affected)} unique leads")

        status_mutations = {
            "Nurturing",
            "SV Completed \u2013 Follow Up",
            "SV Completed – Follow Up",
            "Gone Cold",
        }

        reverted = 0
        skipped = 0
        for lead_id, payloads in affected.items():
            sla_set_status = next(
                (p["lead_status"] for p in payloads if p.get("lead_status") in status_mutations),
                None,
            )
            if not sla_set_status:
                skipped += 1
                continue

            lead = await db.leads.find_one({"id": lead_id}, {"lead_status": 1, "_id": 0})
            if not lead:
                skipped += 1
                continue

            current_status = lead.get("lead_status", "")
            if current_status not in status_mutations:
                print(f"  [SKIP] lead {lead_id}: status='{current_status}' (manually updated)")
                skipped += 1
                continue

            revert_to = "Visit Completed"
            if dry_run:
                print(f"  [DRY]  lead {lead_id}: '{current_status}' -> '{revert_to}'")
            else:
                await db.leads.update_one(
                    {"id": lead_id},
                    {
                        "$unset": {
                            **LEAD_SLA_UNSET_FIELDS,
                            "nurture_entered_at_dt": "",
                            "sv_followup_entered_at_dt": "",
                        },
                        "$set": {"lead_status": revert_to},
                    },
                )
                print(f"  [OK]   lead {lead_id}: '{current_status}' -> '{revert_to}'")
            reverted += 1

        print(f"\n  Reverted: {reverted}   Skipped (safe): {skipped}")

    # ── 9. OPTIONAL: RECOMPUTE FOLLOW-UP DATES ───────────────────────────────
    if recompute_next_action:
        lead_total = await db.leads.count_documents({})
        print(f"\n[next_action]   recomputing next_action_date for {lead_total} leads")
        if dry_run:
            print("                dry-run — would recompute from remaining pending tasks")
        else:
            updated = await _recompute_all_next_action_dates(db, dry_run=False)
            print(f"                recomputed {updated} leads")

    # ── SUMMARY ──────────────────────────────────────────────────────────────
    _banner("Summary")
    if dry_run:
        print("  DRY-RUN — no data was modified.")
        print("  Re-run without --dry-run to apply changes.")
    else:
        print("  SLA engine artefacts purged.")
        print("  Historical leads remain sla_paused until their next status change.")
        print("  Safe to keep the process-slas cron running.")

    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Purge all SLA-engine-generated tasks, notifications, events and reset lead flags.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview counts without writing to the database.",
    )
    parser.add_argument(
        "--recompute-next-action",
        action="store_true",
        help="After purge, sync each lead's next_action_date from remaining non-SLA tasks "
        "(fixes Follow-up Today / Missed Follow-up tiles).",
    )
    parser.add_argument(
        "--recompute-only",
        action="store_true",
        help="Skip purge; only recompute next_action_date for all leads.",
    )
    parser.add_argument(
        "--revert-lead-mutations",
        action="store_true",
        help="Revert lead_status changes forced by SLA (Gone Cold, Nurturing, etc.). Use with care.",
    )
    parser.add_argument(
        "--include-reminders",
        action="store_true",
        help="Also delete db.reminders records (from the reminders cron, NOT the SLA engine).",
    )
    parser.add_argument("--since", metavar="ISO8601", help="Only target records created at/after this UTC time.")
    parser.add_argument("--until", metavar="ISO8601", help="Only target records created at/before this UTC time.")
    args = parser.parse_args()

    since = _parse_iso(args.since) if args.since else None
    until = _parse_iso(args.until) if args.until else None

    asyncio.run(
        run(
            dry_run=args.dry_run,
            revert_mutations=args.revert_lead_mutations,
            recompute_next_action=args.recompute_next_action,
            recompute_only=args.recompute_only,
            include_reminders=args.include_reminders,
            since=since,
            until=until,
        )
    )


if __name__ == "__main__":
    main()
