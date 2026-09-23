"""Read-only RNR SLA health sample against whatever DB_NAME is configured.

Refuses if DB_NAME is not arihant_crm (prod sample) or arihant_crm_e2e.
Never writes.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
# Prefer explicit env; do not override if already set
load_dotenv(BACKEND / ".env", override=False)


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
    if lock and lock.get("expires_at"):
        exp = lock["expires_at"]
        if getattr(exp, "tzinfo", None) is None:
            exp = exp.replace(tzinfo=timezone.utc)
        print(f"LOCK_EXPIRED={exp < now} expires_at={exp.isoformat()}")

    rnr = await db.leads.count_documents(
        {"lead_status": "RNR", "sla_paused": {"$ne": True}}
    )
    r1 = await db.leads.count_documents(
        {
            "lead_status": "RNR",
            "sla_paused": {"$ne": True},
            "sla_flags.rnr.reminder_1_at_dt": {"$exists": True},
        }
    )
    r2 = await db.leads.count_documents(
        {
            "lead_status": "RNR",
            "sla_paused": {"$ne": True},
            "sla_flags.rnr.reminder_2_at_dt": {"$exists": True},
        }
    )
    r3 = await db.leads.count_documents(
        {
            "lead_status": "RNR",
            "sla_paused": {"$ne": True},
            "sla_flags.rnr.reminder_3_at_dt": {"$exists": True},
        }
    )
    any_flag = await db.leads.count_documents(
        {
            "lead_status": "RNR",
            "sla_paused": {"$ne": True},
            "$or": [
                {"sla_flags.rnr.reminder_1_at_dt": {"$exists": True}},
                {"sla_flags.rnr.reminder_2_at_dt": {"$exists": True}},
                {"sla_flags.rnr.reminder_3_at_dt": {"$exists": True}},
            ],
        }
    )
    open_rem = await db.tasks.count_documents(
        {
            "source": "sla",
            "sla_rule": "rnr",
            "sla_threshold": {"$regex": r"^reminder_"},
            "status": {"$in": ["pending", "in_progress"]},
        }
    )
    open_esc = await db.tasks.count_documents(
        {
            "source": "sla",
            "sla_rule": "rnr",
            "sla_threshold": {"$in": ["24h", "48h", "15d"]},
            "status": {"$in": ["pending", "in_progress"]},
        }
    )

    print(f"active_RNR_leads={rnr}")
    print(f"with_reminder_1={r1} reminder_2={r2} reminder_3={r3} any_reminder_flag={any_flag}")
    print(f"open_rnr_reminder_tasks={open_rem} open_rnr_escalation_tasks={open_esc}")

    # Spot-check: RNR leads with rnr_entered_at older than ~2 calendar days (safe proxy for 4+ biz hours)
    cutoff = now - timedelta(days=2)
    stale = (
        await db.leads.find(
            {
                "lead_status": "RNR",
                "sla_paused": {"$ne": True},
                "$or": [
                    {"rnr_entered_at_dt": {"$lte": cutoff}},
                    {
                        "rnr_entered_at_dt": {"$exists": False},
                        "updated_at_dt": {"$lte": cutoff},
                    },
                ],
            },
            {
                "_id": 0,
                "id": 1,
                "first_name": 1,
                "last_name": 1,
                "assigned_to_name": 1,
                "assigned_to": 1,
                "rnr_entered_at_dt": 1,
                "updated_at_dt": 1,
                "sla_flags.rnr": 1,
            },
        )
        .sort("updated_at_dt", 1)
        .limit(10)
        .to_list(10)
    )

    print(f"stale_RNR_sample_n={len(stale)}")
    for lead in stale:
        flags = ((lead.get("sla_flags") or {}).get("rnr") or {})
        rem_keys = [k for k in flags if k.startswith("reminder_")]
        tid = lead.get("id")
        open_t = await db.tasks.count_documents(
            {
                "lead_id": tid,
                "source": "sla",
                "sla_rule": "rnr",
                "sla_threshold": {"$regex": r"^reminder_"},
                "status": {"$in": ["pending", "in_progress"]},
            }
        )
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        print(
            f"  lead={tid} name={name!r} assignee={lead.get('assigned_to_name') or lead.get('assigned_to')} "
            f"rnr_entered={lead.get('rnr_entered_at_dt')} rem_flags={rem_keys or 'NONE'} open_rem_tasks={open_t}"
        )

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
