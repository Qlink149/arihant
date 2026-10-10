#!/usr/bin/env python3
"""
backfill_missing_site_visit_events.py
=====================================
Leads created straight into "Visit Completed" (walk-ins) never got an entry in the
append-only `site_visit_events` log, because only status CHANGES were logged - so
the Site Visits report undercounted. create_lead now logs them; this script adds the
ones created before that fix.

Which leads (all must hold):
  * created on/after the first logged visit (the log did not exist before that),
  * no event in `site_visit_events` at all,
  * AND either currently in "Visit Completed" (it is a completed visit right now), or
    in a later stage with an explicit "Status set to Visit Completed" note on the lead.
    A later-stage lead with no such evidence is NOT guessed at.

Event date: the lead's `visit_completed_at_dt` if present, else its creation time (the
visit was recorded when the lead was created). The event is tagged backfilled=True.

Safety: dry run by default (lists every lead and the date it would get); --apply writes
a JSON backup of the planned events first, inserts only these events (no lead is
modified), and is idempotent (re-running adds nothing).

Usage
-----
  python scripts/backfill_missing_site_visit_events.py            # preview
  python scripts/backfill_missing_site_visit_events.py --apply    # backup + insert
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT_DIR / "scripts" / "static_data"
sys.path.insert(0, str(ROOT_DIR))

from crm.services.lead_field_normalize import remap_projects_from_values  # noqa: E402

LATER_STAGES = ("SV Follow-up 1", "SV Follow-up 2", "Negotiation", "Closed Won", "Closed Lost", "Gone Cold")
EVIDENCE = "status set to visit completed"


def _aware(d):
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def has_evidence(lead: dict) -> bool:
    return any(EVIDENCE in str(c.get("description") or "").lower() for c in (lead.get("context_updates") or []))


def qualifies(lead: dict) -> bool:
    status = (lead.get("lead_status") or "").strip().lower()
    if status == "visit completed":
        return True
    return status in {s.lower() for s in LATER_STAGES} and has_evidence(lead)


def build_event(lead: dict) -> Dict[str, Any]:
    completed = _aware(lead.get("visit_completed_at_dt")) or _aware(lead.get("created_at_dt"))
    project, projects = remap_projects_from_values(lead.get("project"), lead.get("projects"))
    name = f"{(lead.get('first_name') or '').strip()} {(lead.get('last_name') or '').strip()}".strip()
    return {
        "id": str(uuid.uuid4()),
        "lead_id": lead["id"],
        "completed_at_dt": completed,
        "completed_at": completed.isoformat() if completed else None,
        "project": project or lead.get("project"),
        "projects": projects or [],
        "assigned_user_id": lead.get("assigned_user_id"),
        "assigned_to_name": lead.get("assigned_to_name") or lead.get("assigned_to"),
        "actor_user_id": None,
        "actor_name": "Backfill",
        "lead_name": name or "Lead",
        "phone": lead.get("phone"),
        "backfilled": True,
    }


async def plan_events(db: Any) -> List[Dict[str, Any]]:
    first = await db.site_visit_events.find_one({}, {"_id": 0, "completed_at_dt": 1}, sort=[("completed_at_dt", 1)])
    if not first:
        return []
    since = _aware(first["completed_at_dt"])
    with_events = {e["lead_id"] for e in await db.site_visit_events.find({}, {"_id": 0, "lead_id": 1}).to_list(None)}
    leads = await db.leads.find(
        {"created_at_dt": {"$gte": since}},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "phone": 1, "lead_status": 1, "project": 1, "projects": 1,
         "assigned_user_id": 1, "assigned_to_name": 1, "assigned_to": 1, "created_at_dt": 1, "visit_completed_at_dt": 1,
         "context_updates": 1},
    ).to_list(None)
    return [build_event(l) for l in leads if l["id"] not in with_events and qualifies(l)]


async def apply_events(db: Any, events: List[Dict[str, Any]], *, backup_dir: Path = BACKUP_DIR) -> Dict[str, Any]:
    result: Dict[str, Any] = {"inserted": 0, "backup_file": None}
    if not events:
        return result
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"site_visit_events_backfill_plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(events, indent=2, default=str), encoding="utf-8")
    if len(json.loads(path.read_text(encoding="utf-8"))) != len(events):
        raise RuntimeError("Backup verification failed - nothing inserted")
    result["backup_file"] = str(path)
    await db.site_visit_events.insert_many(events)
    result["inserted"] = len(events)
    return result


async def run(*, apply: bool) -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT_DIR / ".env")
    from crm.core.state import db

    print(f"Database: {db.name}")
    events = await plan_events(db)
    print(f"Visits missing from the log: {len(events)}")
    for e in sorted(events, key=lambda x: x["completed_at_dt"]):
        print(f"  {e['completed_at_dt'].astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC | {e['lead_name'][:24]:24} | {str(e['project'])[:24]}")
    if not apply:
        print("Dry run only - pass --apply to back up and insert.")
        return 0
    res = await apply_events(db, events)
    print(f"Backup: {res['backup_file']}")
    print(f"Inserted: {res['inserted']}")
    again = await plan_events(db)
    print(f"Remaining after apply: {len(again)}")
    return 0 if not again else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill site_visit_events for walk-ins created as Visit Completed")
    ap.add_argument("--apply", action="store_true", help="Back up and insert (default is preview).")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(apply=args.apply)))


if __name__ == "__main__":
    main()
