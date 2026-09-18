"""
Backfill MCUBE calls → lead timeline + auto-create unknown leads.

Dry-run by default. Pass --apply to write.

Usage (from backend/ with PYTHONPATH=.):
  python scripts/backfill_mcube_timeline.py
  python scripts/backfill_mcube_timeline.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from crm.core.state import db
from crm.services.mcube.process import process_mcube_event_doc
from crm.services.mcube.timeline import record_call_on_lead
from crm.services.mcube_lead_intake import create_mcube_unknown_lead


async def _lead_has_timeline(lead_id: str, call_id: str) -> bool:
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0, "context_updates": 1})
    for upd in (lead or {}).get("context_updates") or []:
        if isinstance(upd, dict) and upd.get("mcube_call_id") == call_id:
            return True
    return False


async def run(apply: bool) -> None:
    db_name = os.environ.get("DB_NAME", "")
    print(f"DB={db_name} apply={apply}")

    # 1) Reprocess failed / pending events
    event_filter = {
        "$or": [
            {"processed": False},
            {"error": {"$regex": "duplicate key", "$options": "i"}},
        ]
    }
    events = await db.mcube_events.find(event_filter, {"_id": 0}).sort("received_at_dt", 1).to_list(500)
    print(f"events_to_reprocess={len(events)}")
    if apply:
        for ev in events:
            await db.mcube_events.update_one(
                {"id": ev["id"]},
                {"$set": {"processed": False, "error": None}},
            )
            ev["processed"] = False
            await process_mcube_event_doc(ev)

    # 2) Calls with lead_id + hangup recording but missing timeline
    calls_with_lead = await db.calls.find(
        {
            "lead_id": {"$exists": True, "$ne": None, "$ne": ""},
            "call_id": {"$exists": True, "$ne": None, "$ne": ""},
            "$or": [
                {"is_finalized": True},
                {"recording_url": {"$exists": True, "$ne": ""}},
            ],
        },
        {"_id": 0},
    ).to_list(500)
    timeline_fix = 0
    for call in calls_with_lead:
        call_id = call.get("call_id") or ""
        lead_id = call.get("lead_id") or ""
        if not call_id or not lead_id:
            continue
        if await _lead_has_timeline(lead_id, call_id):
            continue
        timeline_fix += 1
        print(f"timeline_backfill call_id={call_id[-12:]} lead_id={lead_id}")
        if apply:
            await record_call_on_lead(
                lead_id=lead_id,
                call=call,
                agent_name=call.get("assigned_to_name") or call.get("agent_name") or "",
                actor_user_id=call.get("assigned_user_id") or "",
            )
    print(f"timeline_backfill_candidates={timeline_fix}")

    # 3) Finalized unmatched calls → auto-create lead + timeline
    unmatched_calls = await db.calls.find(
        {
            "is_finalized": True,
            "$or": [
                {"lead_id": {"$exists": False}},
                {"lead_id": None},
                {"lead_id": ""},
            ],
            "lead_match_method": {"$in": ["unmatched", ""]},
            "customer_number_10": {"$exists": True, "$ne": ""},
        },
        {"_id": 0},
    ).to_list(500)
    auto_create = 0
    for call in unmatched_calls:
        phone = call.get("customer_number") or call.get("customer_number_10") or ""
        if not phone:
            continue
        auto_create += 1
        print(f"auto_create phone={call.get('customer_number_10')} call_id={(call.get('call_id') or '')[-12:]}")
        if apply:
            lead = await create_mcube_unknown_lead(
                phone,
                caller_name="",
                call_id=call.get("call_id") or "",
                notify=False,
            )
            if lead and lead.get("id"):
                await db.calls.update_one(
                    {"call_id": call.get("call_id")},
                    {"$set": {"lead_id": lead["id"], "lead_match_method": "mcube_auto_create_backfill"}},
                )
                if not await _lead_has_timeline(lead["id"], call.get("call_id") or ""):
                    await record_call_on_lead(
                        lead_id=lead["id"],
                        call={**call, "lead_id": lead["id"]},
                        agent_name=call.get("assigned_to_name") or call.get("agent_name") or "",
                        actor_user_id=call.get("assigned_user_id") or "",
                    )
    print(f"auto_create_candidates={auto_create}")

    # 4) Remove orphan null call_id row
    null_calls = await db.calls.count_documents({"$or": [{"call_id": None}, {"call_id": ""}]})
    print(f"null_call_id_rows={null_calls}")
    if apply and null_calls:
        result = await db.calls.delete_many({"$or": [{"call_id": None}, {"call_id": ""}]})
        print(f"deleted_null_call_id_rows={result.deleted_count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill MCUBE timelines and auto-leads")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    main()
