#!/usr/bin/env python3
"""
cleanup_rnr_task_piles.py
=========================
Collapse duplicate pending RNR reminder piles created by the unbounded
SLA reminder ladder (reminder_1 … reminder_N).

For each lead with >1 open RNR reminder:
  - Keep the newest pending/in_progress reminder
  - Cancel the rest
  - Leave escalations (24h/48h/15d) alone
  - Recompute next_action_date from remaining pending tasks

Usage
-----
  python backend/scripts/cleanup_rnr_task_piles.py --dry-run
  python backend/scripts/cleanup_rnr_task_piles.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ.get("MONGO_URL", "")
DB_NAME = os.environ.get("DB_NAME", "")

_OPEN = ("pending", "in_progress")


def _now_pair():
    from datetime import datetime, timezone

    now_dt = datetime.now(timezone.utc)
    return now_dt, now_dt.isoformat()


async def _recompute_nad(db, lead_id: str) -> None:
    task = await db.tasks.find_one(
        {"lead_id": lead_id, "status": {"$in": list(_OPEN)}},
        {"_id": 0, "due_date": 1},
        sort=[("due_date", 1), ("due_at_dt", 1)],
    )
    now_dt, now_iso = _now_pair()
    if task and task.get("due_date"):
        due = str(task["due_date"]).strip()[:10]
        await db.leads.update_one(
            {"id": lead_id},
            {"$set": {"next_action_date": due, "updated_at": now_iso, "updated_at_dt": now_dt}},
        )
    else:
        await db.leads.update_one(
            {"id": lead_id},
            {"$unset": {"next_action_date": ""}, "$set": {"updated_at": now_iso, "updated_at_dt": now_dt}},
        )


async def run(*, apply: bool) -> int:
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL and DB_NAME must be set in backend/.env", file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    cursor = db.tasks.find(
        {
            "source": "sla",
            "sla_rule": "rnr",
            "status": {"$in": list(_OPEN)},
            "sla_threshold": {"$regex": r"^reminder_"},
            "lead_id": {"$exists": True, "$nin": [None, ""]},
        },
        {
            "_id": 0,
            "id": 1,
            "lead_id": 1,
            "dedupe_key": 1,
            "sla_threshold": 1,
            "created_at": 1,
            "created_at_dt": 1,
            "due_date": 1,
            "description": 1,
        },
    )

    by_lead: dict[str, list] = defaultdict(list)
    async for doc in cursor:
        by_lead[doc["lead_id"]].append(doc)

    piles = {lid: tasks for lid, tasks in by_lead.items() if len(tasks) > 1}
    print(f"Leads with open RNR reminders: {len(by_lead)}")
    print(f"Leads with piles (>1 open reminder): {len(piles)}")

    cancel_ids: list[str] = []
    keep_map: dict[str, str] = {}
    for lead_id, tasks in piles.items():
        tasks_sorted = sorted(
            tasks,
            key=lambda t: (
                str(t.get("created_at_dt") or t.get("created_at") or ""),
                t.get("id") or "",
            ),
            reverse=True,
        )
        keep = tasks_sorted[0]
        keep_map[lead_id] = keep["id"]
        for extra in tasks_sorted[1:]:
            cancel_ids.append(extra["id"])
        print(
            f"  lead={lead_id} open={len(tasks)} keep={keep.get('sla_threshold')} "
            f"cancel={len(tasks) - 1}"
        )

    print(f"Would cancel {len(cancel_ids)} duplicate RNR reminders")

    if not apply:
        print("Dry-run only — pass --apply to write.")
        client.close()
        return 0

    now_dt, now_iso = _now_pair()
    if cancel_ids:
        result = await db.tasks.update_many(
            {"id": {"$in": cancel_ids}},
            {"$set": {"status": "cancelled", "updated_at": now_iso, "updated_at_dt": now_dt}},
        )
        print(f"Cancelled {result.modified_count} tasks")

    for lead_id in piles:
        await _recompute_nad(db, lead_id)
    print(f"Recomputed next_action_date for {len(piles)} leads")

    client.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Collapse duplicate RNR reminder task piles")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview only")
    group.add_argument("--apply", action="store_true", help="Cancel duplicates and recompute NAD")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(apply=bool(args.apply))))


if __name__ == "__main__":
    main()
