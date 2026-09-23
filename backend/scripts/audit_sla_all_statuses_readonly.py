"""Read-only multi-status SLA health sample.

Uses backend/.env (prod) or whatever DB_NAME is already set.
Refuses unexpected DB names. Never writes.

Usage (from backend/):
  python scripts/audit_sla_all_statuses_readonly.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND / ".env", override=False)

# Status -> (expected sla_rule keys, lead_status match)
STATUS_SPECS = [
    ("New", "New", ["new"]),
    ("RNR", "RNR", ["rnr"]),
    ("Contacted", "Contacted", ["contacted"]),
    ("Nurturing", "Nurturing", ["nurturing"]),
    ("Interested", "Interested", ["interested"]),
    ("Site Visit Scheduled", "Site Visit Scheduled", ["visit_scheduled"]),
    ("Visit Completed", "Visit Completed", ["visit_completed"]),
    ("SV Follow-up 1", "SV Follow-up 1", ["sv_followup_1"]),
    ("SV Follow-up 2", "SV Follow-up 2", ["sv_followup_2"]),
    ("Negotiation", "Negotiation", ["negotiation"]),
    ("Gone Cold", "Gone Cold", ["gone_cold"]),
    ("Future Prospect", "Future Prospect", ["future_prospect"]),
    ("Re-engaged", "Re-engaged", ["reengaged"]),
]


async def main() -> None:
    db_name = os.environ.get("DB_NAME", "")
    if db_name not in ("arihant_crm", "arihant_crm_e2e"):
        print(f"REFUSE: unexpected DB_NAME={db_name!r}")
        sys.exit(2)

    from motor.motor_asyncio import AsyncIOMotorClient

    uri = os.environ.get("MONGO_URL") or os.environ.get("MONGODB_URI")
    if not uri:
        print("REFUSE: no MONGO_URL")
        sys.exit(2)

    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    now = datetime.now(timezone.utc)
    print(f"DB_NAME={db_name} NOW_UTC={now.isoformat()}")

    lock = await db.cron_locks.find_one({"job": "process_slas"}, {"_id": 0})
    print(f"CRON_LOCK={lock}")

    # Open SLA tasks by rule
    pipeline = [
        {
            "$match": {
                "source": "sla",
                "status": {"$in": ["pending", "in_progress"]},
            }
        },
        {"$group": {"_id": {"rule": "$sla_rule", "th": "$sla_threshold"}, "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]
    print("=== OPEN SLA TASKS BY RULE/THRESHOLD ===")
    async for row in db.tasks.aggregate(pipeline):
        print(f"  {row['_id']['rule']}/{row['_id'].get('th')}: {row['n']}")

    print("=== PER STATUS ===")
    for label, status, rules in STATUS_SPECS:
        active = await db.leads.count_documents(
            {"lead_status": status, "sla_paused": {"$ne": True}}
        )
        paused = await db.leads.count_documents(
            {"lead_status": status, "sla_paused": True}
        )
        open_tasks = await db.tasks.count_documents(
            {
                "source": "sla",
                "sla_rule": {"$in": rules},
                "status": {"$in": ["pending", "in_progress"]},
            }
        )
        # Leads with any sla_flags for this rule family
        flag_path = f"sla_flags.{rules[0]}"
        with_flags = await db.leads.count_documents(
            {
                "lead_status": status,
                "sla_paused": {"$ne": True},
                flag_path: {"$exists": True},
            }
        )
        print(
            f"{label}: active={active} paused={paused} open_sla_tasks={open_tasks} "
            f"leads_with_{rules[0]}_flags={with_flags}"
        )

        # Spot-check up to 3 oldest active leads in this status
        cutoff = now - timedelta(days=3)
        cursor = (
            db.leads.find(
                {
                    "lead_status": status,
                    "sla_paused": {"$ne": True},
                    "updated_at_dt": {"$lte": cutoff},
                },
                {
                    "_id": 0,
                    "id": 1,
                    "first_name": 1,
                    "last_name": 1,
                    "assigned_to_name": 1,
                    "assigned_to": 1,
                    "updated_at_dt": 1,
                    "temperature": 1,
                    "sla_flags": 1,
                },
            )
            .sort("updated_at_dt", 1)
            .limit(3)
        )
        async for lead in cursor:
            lid = lead.get("id")
            flags = (lead.get("sla_flags") or {}).get(rules[0]) or {}
            flag_keys = list(flags.keys())[:8] if flags else []
            ot = await db.tasks.count_documents(
                {
                    "lead_id": lid,
                    "source": "sla",
                    "sla_rule": {"$in": rules},
                    "status": {"$in": ["pending", "in_progress"]},
                }
            )
            name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
            print(
                f"  spot {lid} {name!r} updated={lead.get('updated_at_dt')} "
                f"temp={lead.get('temperature')} flags={flag_keys or 'NONE'} open_tasks={ot}"
            )

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
