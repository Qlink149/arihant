#!/usr/bin/env python3
"""
cleanup_leads.py
================
Targeted lead cleanup for client handover.

Default targets (built-in):
  - Strip follow-ups: Raman S P, Chandhini (pending tasks + next_action_date)
  - Delete completely: rosh (phone 9677103646)

Usage
-----
  python backend/scripts/cleanup_leads.py --dry-run
  python backend/scripts/cleanup_leads.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ.get("MONGO_URL", "")
DB_NAME = os.environ.get("DB_NAME", "")

STRIP_FOLLOWUPS: list[dict[str, Any]] = [
    {"first_name": "Raman", "last_name": "S P"},
    {"first_name": "Chandhini"},
]

DELETE_COMPLETELY: list[dict[str, Any]] = [
    {"first_name": "rosh", "phone": "9677103646"},
]

LEAD_FOLLOWUP_UNSET = {
    "next_action_date": "",
    "nurture_task_required_since_dt": "",
    "nurture_task_required_task_id": "",
}


def _normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("91") and len(digits) > 10:
        digits = digits[2:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits[-10:] if len(digits) >= 10 else digits


def _name_query(spec: dict[str, Any]) -> dict[str, Any]:
    q: dict[str, Any] = {}
    if spec.get("first_name"):
        q["first_name"] = {"$regex": rf"^\s*{re.escape(spec['first_name'])}\s*$", "$options": "i"}
    if spec.get("last_name"):
        q["last_name"] = {"$regex": rf"^\s*{re.escape(spec['last_name'])}\s*$", "$options": "i"}
    if spec.get("phone"):
        norm = _normalize_phone(spec["phone"])
        if norm:
            q["$or"] = [
                {"phone": {"$regex": norm}},
                {"normalized_phone": norm},
            ]
    return q


async def _resolve_leads(db, spec: dict[str, Any], *, lead_id: Optional[str] = None) -> list[dict]:
    if lead_id:
        doc = await db.leads.find_one({"id": lead_id}, {"_id": 0})
        return [doc] if doc else []

    query = _name_query(spec)
    if not query:
        return []
    return await db.leads.find(query, {"_id": 0}).to_list(50)


async def _pending_task_count(db, lead_id: str) -> int:
    return await db.tasks.count_documents({"lead_id": lead_id, "status": "pending"})


async def _all_task_ids(db, lead_id: str) -> list[str]:
    ids: list[str] = []
    cursor = db.tasks.find({"lead_id": lead_id}, {"_id": 0, "id": 1})
    async for doc in cursor:
        tid = doc.get("id")
        if tid:
            ids.append(tid)
    return ids


def _format_lead(lead: dict, pending: int) -> str:
    name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
    return (
        f"  id={lead.get('id')}  name={name!r}  phone={lead.get('phone') or '—'}  "
        f"project={lead.get('project') or '—'}  pending_tasks={pending}  "
        f"next_action_date={lead.get('next_action_date') or '—'}"
    )


async def _resolve_targets(db, *, allow_ambiguous: bool) -> tuple[list[dict], list[dict]]:
    strip_leads: list[dict] = []
    delete_leads: list[dict] = []

    for spec in STRIP_FOLLOWUPS:
        matches = await _resolve_leads(db, spec)
        if len(matches) != 1:
            msg = f"STRIP target {spec}: expected 1 match, found {len(matches)}"
            if not allow_ambiguous:
                raise SystemExit(msg)
            print(f"WARNING: {msg}")
        strip_leads.extend(matches)

    for spec in DELETE_COMPLETELY:
        matches = await _resolve_leads(db, spec)
        if len(matches) != 1:
            msg = f"DELETE target {spec}: expected 1 match, found {len(matches)}"
            if not allow_ambiguous:
                raise SystemExit(msg)
            print(f"WARNING: {msg}")
        delete_leads.extend(matches)

    return strip_leads, delete_leads


async def _strip_followups(db, lead: dict, *, apply: bool) -> dict[str, int]:
    lead_id = lead["id"]
    counts = {
        "pending_tasks": 0,
        "notifications": 0,
        "reminders": 0,
        "lead_updated": 0,
    }

    pending_filter = {"lead_id": lead_id, "status": "pending"}
    counts["pending_tasks"] = await db.tasks.count_documents(pending_filter)

    pending_ids: list[str] = []
    async for t in db.tasks.find(pending_filter, {"_id": 0, "id": 1}):
        if t.get("id"):
            pending_ids.append(t["id"])

    notif_filter: dict[str, Any] = {"$or": [{"lead_id": lead_id}]}
    if pending_ids:
        notif_filter["$or"].append({"task_id": {"$in": pending_ids}})
    counts["notifications"] = await db.notifications.count_documents(notif_filter)
    counts["reminders"] = await db.reminders.count_documents({"lead_id": lead_id})

    if not apply:
        return counts

    if counts["pending_tasks"]:
        await db.tasks.delete_many(pending_filter)
    if counts["notifications"]:
        await db.notifications.delete_many(notif_filter)
    if counts["reminders"]:
        await db.reminders.delete_many({"lead_id": lead_id})

    unset = {k: v for k, v in LEAD_FOLLOWUP_UNSET.items() if lead.get(k)}
    if unset or lead.get("next_action_date"):
        await db.leads.update_one({"id": lead_id}, {"$unset": LEAD_FOLLOWUP_UNSET})
        counts["lead_updated"] = 1

    return counts


async def _delete_lead_cascade(db, lead: dict, *, apply: bool) -> dict[str, int]:
    lead_id = lead["id"]
    phone = lead.get("phone") or lead.get("normalized_phone") or ""
    norm = _normalize_phone(str(phone))

    task_ids = await _all_task_ids(db, lead_id)
    counts = {
        "tasks": len(task_ids),
        "notifications": 0,
        "lead_events": 0,
        "reminders": 0,
        "lead_transfers": 0,
        "whatsapp_messages": 0,
        "leads": 1,
    }

    notif_clauses: list[dict] = [{"lead_id": lead_id}]
    if task_ids:
        notif_clauses.append({"task_id": {"$in": task_ids}})
    notif_filter = {"$or": notif_clauses}

    counts["notifications"] = await db.notifications.count_documents(notif_filter)
    counts["lead_events"] = await db.lead_events.count_documents({"lead_id": lead_id})
    counts["reminders"] = await db.reminders.count_documents({"lead_id": lead_id})
    counts["lead_transfers"] = await db.lead_transfers.count_documents({"lead_id": lead_id})

    if norm:
        wa_filter = {
            "$or": [
                {"source": {"$regex": norm}},
                {"destination": {"$regex": norm}},
            ]
        }
        counts["whatsapp_messages"] = await db.whatsapp_messages.count_documents(wa_filter)

    if not apply:
        return counts

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
    if norm and counts["whatsapp_messages"]:
        await db.whatsapp_messages.delete_many(
            {
                "$or": [
                    {"source": {"$regex": norm}},
                    {"destination": {"$regex": norm}},
                ]
            }
        )
    await db.leads.delete_one({"id": lead_id})

    return counts


async def run(*, apply: bool) -> int:
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL and DB_NAME must be set in backend/.env", file=sys.stderr)
        return 1

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"\n{'=' * 60}\n  Targeted Lead Cleanup  [{mode}]  DB={DB_NAME}\n{'=' * 60}")

    strip_leads, delete_leads = await _resolve_targets(db, allow_ambiguous=False)

    print("\n--- Strip follow-ups (keep lead) ---")
    for lead in strip_leads:
        pending = await _pending_task_count(db, lead["id"])
        print(_format_lead(lead, pending))
        stats = await _strip_followups(db, lead, apply=apply)
        print(
            f"    -> pending_tasks={stats['pending_tasks']}  notifications={stats['notifications']}  "
            f"reminders={stats['reminders']}  lead_fields_cleared={stats['lead_updated'] or int(bool(lead.get('next_action_date')))}"
        )

    print("\n--- Delete lead completely ---")
    for lead in delete_leads:
        pending = await _pending_task_count(db, lead["id"])
        print(_format_lead(lead, pending))
        stats = await _delete_lead_cascade(db, lead, apply=apply)
        print(
            f"    -> tasks={stats['tasks']}  notifications={stats['notifications']}  "
            f"lead_events={stats['lead_events']}  reminders={stats['reminders']}  "
            f"transfers={stats['lead_transfers']}  whatsapp={stats['whatsapp_messages']}  leads=1"
        )

    print(f"\n{'=' * 60}")
    if apply:
        print("  Done — changes applied.")
    else:
        print("  DRY-RUN — no changes written. Re-run with --apply to execute.")
    print(f"{'=' * 60}\n")

    client.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Targeted lead cleanup for client handover")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to the database (default is dry-run preview).",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(apply=bool(args.apply))))


if __name__ == "__main__":
    main()
