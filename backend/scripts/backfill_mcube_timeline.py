"""
Backfill MCUBE calls → lead timeline + auto-create unknown leads.

Dry-run by default. Pass --apply to write.

Usage (from backend/ with PYTHONPATH=.):
  python scripts/backfill_mcube_timeline.py
  python scripts/backfill_mcube_timeline.py --apply
  python scripts/backfill_mcube_timeline.py --fix-recordings --apply
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
from crm.services.mcube.recordings import normalize_mcube_recording_url
from crm.services.mcube.timeline import build_call_timeline_entry, record_call_on_lead
from crm.services.mcube_lead_intake import create_mcube_unknown_lead


async def _lead_has_timeline(lead_id: str, call_id: str) -> bool:
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0, "context_updates": 1})
    for upd in (lead or {}).get("context_updates") or []:
        if isinstance(upd, dict) and upd.get("mcube_call_id") == call_id:
            return True
    return False


async def _find_event_recording_url(call_id: str) -> tuple[str, str]:
    """Best full URL from mcube_events for a call_id."""
    events = await db.mcube_events.find(
        {"call_id": call_id},
        {"_id": 0, "raw_payload": 1},
    ).sort("received_at_dt", -1).to_list(20)
    for ev in events:
        raw = ev.get("raw_payload") or {}
        if not isinstance(raw, dict):
            continue
        filename = str(raw.get("filename") or "").strip()
        url, _ = normalize_mcube_recording_url(filename)
        if url:
            return url, filename
    return "", ""


def _is_bare_recording_value(value: str) -> bool:
    if not value:
        return False
    url, _ = normalize_mcube_recording_url(value)
    return not url


async def _fix_recordings(apply: bool) -> int:
    """Repair calls/timeline rows that stored bare filenames as recording_url."""
    calls = await db.calls.find(
        {
            "$or": [
                {"recording_url": {"$regex": r"^[^h]", "$options": "i"}},
                {"recording_url": {"$exists": True, "$ne": ""}, "recording_filename": {"$exists": False}},
            ]
        },
        {"_id": 0},
    ).to_list(500)
    fixed = 0
    for call in calls:
        call_id = call.get("call_id") or ""
        if not call_id:
            continue
        current = str(call.get("recording_url") or "").strip()
        if current and not _is_bare_recording_value(current):
            continue

        event_url, event_raw = await _find_event_recording_url(call_id)
        url, filename = normalize_mcube_recording_url(event_url or event_raw or current)
        if not url and not filename:
            continue

        fixed += 1
        print(
            f"fix_recording call_id={call_id[-12:]} "
            f"url={'yes' if url else 'no'} filename={filename or '-'}"
        )
        if not apply:
            continue

        await db.calls.update_one(
            {"call_id": call_id},
            {"$set": {"recording_url": url, "recording_filename": filename, "recording_available": bool(url or filename)}},
        )

        lead_id = call.get("lead_id") or ""
        if not lead_id:
            continue

        lead = await db.leads.find_one({"id": lead_id}, {"_id": 0, "context_updates": 1})
        if not lead:
            continue

        updates = []
        changed = False
        for upd in lead.get("context_updates") or []:
            if not isinstance(upd, dict):
                updates.append(upd)
                continue
            if upd.get("type") == "call" and upd.get("mcube_call_id") == call_id:
                new_entry = build_call_timeline_entry(
                    call={**call, "recording_url": url, "recording_filename": filename},
                    agent_name=upd.get("agent") or call.get("assigned_to_name") or "",
                    actor_user_id=upd.get("actor_user_id") or call.get("assigned_user_id") or "",
                    call_dt=upd.get("timestamp_dt") or call.get("end_time_dt") or call.get("start_time_dt"),
                )
                new_entry["timestamp"] = upd.get("timestamp") or new_entry.get("timestamp")
                new_entry["timestamp_dt"] = upd.get("timestamp_dt") or new_entry.get("timestamp_dt")
                updates.append(new_entry)
                changed = True
            else:
                updates.append(upd)

        if changed:
            await db.leads.update_one({"id": lead_id}, {"$set": {"context_updates": updates}})

    print(f"fix_recording_candidates={fixed}")
    return fixed


async def run(apply: bool, fix_recordings: bool) -> None:
    db_name = os.environ.get("DB_NAME", "")
    print(f"DB={db_name} apply={apply} fix_recordings={fix_recordings}")

    if fix_recordings:
        await _fix_recordings(apply)

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
                {"recording_filename": {"$exists": True, "$ne": ""}},
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
    parser.add_argument(
        "--fix-recordings",
        action="store_true",
        help="Repair bare filename recording_url values from mcube_events",
    )
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply, fix_recordings=args.fix_recordings))


if __name__ == "__main__":
    main()
