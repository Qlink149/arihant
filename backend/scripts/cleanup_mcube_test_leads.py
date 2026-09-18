#!/usr/bin/env python3
"""Remove MCUBE auto-created test inbound leads and their call rows."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# MCUBE team / Postman test numbers only
TEST_PHONES_10 = ("9916043625", "9489356932")


async def _delete_lead_cascade(db, lead: dict) -> dict[str, int]:
    lead_id = lead["id"]
    task_ids = [
        t["id"]
        for t in await db.tasks.find({"lead_id": lead_id}, {"_id": 0, "id": 1}).to_list(500)
        if t.get("id")
    ]
    notif_filter = {"$or": [{"lead_id": lead_id}] + ([{"task_id": {"$in": task_ids}}] if task_ids else [])}
    counts = {
        "tasks": await db.tasks.count_documents({"lead_id": lead_id}),
        "notifications": await db.notifications.count_documents(notif_filter),
        "lead_events": await db.lead_events.count_documents({"lead_id": lead_id}),
        "reminders": await db.reminders.count_documents({"lead_id": lead_id}),
        "lead_transfers": await db.lead_transfers.count_documents({"lead_id": lead_id}),
        "leads": 1,
    }
    if counts["tasks"]:
        await db.tasks.delete_many({"lead_id": lead_id})
    if counts["notifications"]:
        await db.notifications.delete_many(notif_filter)
    if counts["lead_events"]:
        await db.lead_events.delete_many({"lead_id": lead_id})
    if counts["reminders"]:
        await db.reminders.delete_many({"lead_id": lead_id})
    if counts["lead_transfers"]:
        await db.lead_transfers.delete_many({"lead_id": lead_id})
    await db.leads.delete_one({"id": lead_id})
    return counts


async def run(*, apply: bool) -> int:
    mongo_url = os.environ.get("MONGO_URL", "")
    db_name = os.environ.get("DB_NAME", "")
    if not mongo_url or not db_name:
        print("MONGO_URL and DB_NAME required", file=sys.stderr)
        return 1

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    leads = await db.leads.find(
        {
            "normalized_phone": {"$in": list(TEST_PHONES_10)},
            "lead_source": "MCUBE Inbound",
        },
        {"_id": 0},
    ).to_list(20)

    report = {"mode": "apply" if apply else "dry_run", "leads": [], "calls": []}
    for lead in leads:
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        phone = lead.get("normalized_phone")
        entry = {
            "id": lead.get("id"),
            "name": name,
            "phone": phone,
            "lead_status": lead.get("lead_status"),
        }
        call_count = await db.calls.count_documents({"customer_number": phone})
        entry["calls_for_phone"] = call_count
        if apply:
            entry["deleted"] = await _delete_lead_cascade(db, lead)
            if call_count:
                res = await db.calls.delete_many({"customer_number": phone})
                entry["calls_deleted"] = res.deleted_count
        report["leads"].append(entry)

    if not leads:
        report["warning"] = "No MCUBE Inbound test leads matched — nothing to do."

    print(json.dumps(report, indent=2, default=str))
    client.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete MCUBE test inbound leads")
    parser.add_argument("--apply", action="store_true", help="Execute deletes (default dry-run)")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(apply=bool(args.apply))))


if __name__ == "__main__":
    main()
