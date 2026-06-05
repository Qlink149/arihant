#!/usr/bin/env python3
"""
purge_sla_data.py
=================
Safely removes all data created by the SLA engine and resets SLA idempotency
flags on leads.  Run with --dry-run first to preview impact before deleting.

What this script cleans:
  1. tasks          — all documents where source="sla" (created_by="SLA Engine")
  2. notifications  — all documents where type in ["sla_task", "sla_alert"]
  3. lead_events    — all documents where event_type="sla_action" AND actor_name="SLA Engine"
  4. leads          — unsets the entire `sla_flags` sub-document (idempotency flags)
                      also unsets helper counters set by SLA:
                        fp_cycle_count, fp_last_checkin_task_created_at_dt,
                        sv_followup_delayed, follow_up_delayed
  5. cron_locks     — removes the SLA cron lock so the engine can re-acquire it cleanly

Optional (--revert-lead-mutations):
  Reads lead_events where action="lead_mutation" (SLA status changes such as
  Gone Cold, Nurturing, SV Completed – Follow Up) and tries to revert the
  lead_status back to "Visit Completed" for each affected lead.
  Use with caution — only safe if the cron was run during a handover/test window
  and agents haven't touched those leads manually since.

Usage
-----
  # Preview only (no writes)
  python scripts/purge_sla_data.py --dry-run

  # Delete SLA artefacts + reset flags (recommended first step)
  python scripts/purge_sla_data.py

  # Also revert SLA-driven lead-status mutations
  python scripts/purge_sla_data.py --revert-lead-mutations

  # Target a specific time window (ISO-8601, UTC)
  python scripts/purge_sla_data.py --since 2026-06-05T00:00:00Z --until 2026-06-05T23:59:59Z
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

# ── bootstrap env ────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ.get("MONGO_URL", "")
DB_NAME   = os.environ.get("DB_NAME", "")

# SLA-engine "fingerprints" — these never change unless you edit sla_engine.py
SLA_CRON_LOCK_JOB = "process_slas"

# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _ts_filter(since: datetime | None, until: datetime | None, field: str = "created_at_dt") -> dict:
    """Build a Mongo range filter on `field` if time bounds were supplied."""
    f: dict = {}
    if since or until:
        clause: dict = {}
        if since:
            clause["$gte"] = since
        if until:
            clause["$lte"] = until
        f[field] = clause
    return f


def _banner(msg: str) -> None:
    print(f"\n{'='*60}\n  {msg}\n{'='*60}")


# ── main logic ────────────────────────────────────────────────────────────────

async def run(
    dry_run: bool,
    revert_mutations: bool,
    since: datetime | None,
    until: datetime | None,
) -> None:
    if not MONGO_URL or not DB_NAME:
        print("❌  MONGO_URL and DB_NAME must be set in backend/.env", file=sys.stderr)
        sys.exit(1)

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    mode = "DRY-RUN" if dry_run else "LIVE DELETE"
    _banner(f"SLA Data Purge  [{mode}]  DB={DB_NAME}")

    ts = _ts_filter(since, until)

    # ── 1. TASKS ─────────────────────────────────────────────────────────────
    task_filter: dict = {
        "$or": [
            {"source": "sla"},
            {"created_by": "SLA Engine"},
        ],
        **ts,
    }
    task_count = await db.tasks.count_documents(task_filter)
    print(f"\n[tasks]         found {task_count:>6} SLA-created tasks")
    if not dry_run and task_count:
        result = await db.tasks.delete_many(task_filter)
        print(f"                deleted {result.deleted_count}")

    # ── 2. NOTIFICATIONS ─────────────────────────────────────────────────────
    notif_filter: dict = {
        "type": {"$in": ["sla_task", "sla_alert"]},
        **ts,
    }
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
    print(f"[lead_events]   found {event_count:>6} SLA events")
    if not dry_run and event_count:
        result = await db.lead_events.delete_many(event_filter)
        print(f"                deleted {result.deleted_count}")

    # ── 4. RESET SLA FLAGS ON LEADS ──────────────────────────────────────────
    # Count leads that have any sla_flags set
    leads_with_flags = await db.leads.count_documents({"sla_flags": {"$exists": True}})
    print(f"[leads]         found {leads_with_flags:>6} leads with sla_flags")

    if not dry_run and leads_with_flags:
        unset_payload = {
            "sla_flags": "",
            # SLA-managed counters / helper timestamps
            "fp_cycle_count": "",
            "fp_last_checkin_task_created_at_dt": "",
            "sv_followup_delayed": "",
            "follow_up_delayed": "",
        }
        result = await db.leads.update_many(
            {"sla_flags": {"$exists": True}},
            {"$unset": unset_payload},
        )
        print(f"                sla_flags unset on {result.modified_count} leads")

    # ── 5. CRON LOCK ─────────────────────────────────────────────────────────
    lock_count = await db.cron_locks.count_documents({"job": SLA_CRON_LOCK_JOB})
    print(f"[cron_locks]    found {lock_count:>6} SLA cron lock(s)")
    if not dry_run and lock_count:
        result = await db.cron_locks.delete_many({"job": SLA_CRON_LOCK_JOB})
        print(f"                deleted {result.deleted_count}")

    # ── 6. OPTIONAL: REVERT LEAD-STATUS MUTATIONS ────────────────────────────
    if revert_mutations:
        _banner("Reverting SLA-driven lead-status mutations")

        # Collect all SLA lead_mutation events (already in window if ts applied)
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

        # Group by lead_id — collect the statuses SLA forced
        affected: dict[str, list[dict]] = {}
        for ev in mutation_events:
            lid = ev.get("lead_id")
            if lid:
                affected.setdefault(lid, []).append(ev.get("payload", {}).get("set_fields", {}))

        print(f"  Affects {len(affected)} unique leads")

        STATUS_MUTATIONS = {
            "Nurturing",
            "SV Completed \u2013 Follow Up",
            "SV Completed – Follow Up",
            "Gone Cold",
        }

        reverted = 0
        skipped  = 0
        for lead_id, payloads in affected.items():
            # Only revert if the lead_status was mutated by SLA
            sla_set_status = next(
                (p["lead_status"] for p in payloads if p.get("lead_status") in STATUS_MUTATIONS),
                None,
            )
            if not sla_set_status:
                skipped += 1
                continue

            # Check the lead still has the SLA-mutated status (not manually changed since)
            lead = await db.leads.find_one({"id": lead_id}, {"lead_status": 1, "_id": 0})
            if not lead:
                skipped += 1
                continue

            current_status = lead.get("lead_status", "")
            if current_status not in STATUS_MUTATIONS:
                # Agent already changed it — don't touch
                print(f"  [SKIP] lead {lead_id}: status='{current_status}' (manually updated, not reverting)")
                skipped += 1
                continue

            # Determine revert target: always back to "Visit Completed"
            # because SLA mutations come from visit_completed / sv_followup rules
            revert_to = "Visit Completed"

            if dry_run:
                print(f"  [DRY]  lead {lead_id}: '{current_status}' -> '{revert_to}'")
            else:
                await db.leads.update_one(
                    {"id": lead_id},
                    {"$unset": {
                        "sla_flags": "",
                        "nurture_entered_at_dt": "",
                        "sv_followup_entered_at_dt": "",
                        "sv_followup_delayed": "",
                        "follow_up_delayed": "",
                    }, "$set": {"lead_status": revert_to}},
                )
                print(f"  [OK]   lead {lead_id}: '{current_status}' -> '{revert_to}'")
            reverted += 1

        print(f"\n  Reverted: {reverted}   Skipped (safe): {skipped}")

    # ── SUMMARY ──────────────────────────────────────────────────────────────
    _banner("Summary")
    if dry_run:
        print("  [!] DRY-RUN - no data was modified.")
        print("  Re-run without --dry-run to apply changes.")
    else:
        print("  [OK] SLA data purged successfully.")
        print("  The SLA engine is safe to re-run from a clean slate.")

    client.close()


# ── entrypoint ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Purge SLA-engine-generated tasks, notifications, events and reset lead flags.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview impact without writing to the database.",
    )
    parser.add_argument(
        "--revert-lead-mutations",
        action="store_true",
        help=(
            "Also revert lead-status changes made by SLA (e.g. Gone Cold, Nurturing). "
            "Only safe when agents haven't manually edited those leads since the test run."
        ),
    )
    parser.add_argument(
        "--since",
        metavar="ISO8601",
        help="Only target SLA data created at or after this UTC timestamp (e.g. 2026-06-05T00:00:00Z).",
    )
    parser.add_argument(
        "--until",
        metavar="ISO8601",
        help="Only target SLA data created at or before this UTC timestamp.",
    )
    args = parser.parse_args()

    since = _parse_iso(args.since) if args.since else None
    until = _parse_iso(args.until) if args.until else None

    asyncio.run(
        run(
            dry_run=args.dry_run,
            revert_mutations=args.revert_lead_mutations,
            since=since,
            until=until,
        )
    )


if __name__ == "__main__":
    main()
