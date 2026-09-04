#!/usr/bin/env python3
"""
backfill_site_visit_events.py
=============================
One-time backfill of append-only `site_visit_events` for #53/#54.

Source A: leads with visit_completed_at_dt and no events yet → one event at that stamp.
Source B: context_updates status diffs into "Visit Completed" → extra events for multi-visit.

Does NOT count task completions ("Call For Site Visit") or free-text site_visit notes.

Usage (from backend/):
  python scripts/backfill_site_visit_events.py --dry-run
  python scripts/backfill_site_visit_events.py --apply          # arihant_crm_e2e only
  python scripts/backfill_site_visit_events.py --apply --prod   # production arihant_crm
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv
from pymongo import MongoClient

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env", override=True)


def _as_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _lead_name(lead: Dict[str, Any]) -> str:
    name = f"{(lead.get('first_name') or '').strip()} {(lead.get('last_name') or '').strip()}".strip()
    return name or (lead.get("name") or "Lead")


def _projects(lead: Dict[str, Any]) -> List[str]:
    raw = lead.get("projects")
    if isinstance(raw, list) and raw:
        return [str(p).strip() for p in raw if str(p).strip()]
    project = (lead.get("project") or "").strip()
    return [project] if project else []


def _event_key(lead_id: str, completed_at_dt: datetime) -> Tuple[str, str]:
    # Second resolution is enough for idempotency
    return (lead_id, completed_at_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))


def _is_visit_completed_to(change: Dict[str, Any]) -> bool:
    if not isinstance(change, dict):
        return False
    if (change.get("field") or "").strip().lower() != "lead_status":
        return False
    to_val = str(change.get("to") or "").strip().lower()
    return to_val == "visit completed"


def extract_timeline_completions(lead: Dict[str, Any]) -> List[datetime]:
    out: List[datetime] = []
    for entry in lead.get("context_updates") or []:
        if not isinstance(entry, dict):
            continue
        if not any(_is_visit_completed_to(c) for c in (entry.get("changes") or []) if isinstance(c, dict)):
            continue
        ts = _as_dt(entry.get("timestamp_dt") or entry.get("timestamp"))
        if ts:
            out.append(ts)
    return out


def build_event_doc(lead: Dict[str, Any], completed_at_dt: datetime) -> Dict[str, Any]:
    projects = _projects(lead)
    lead_id = lead.get("id")
    return {
        "id": str(uuid.uuid4()),
        "lead_id": lead_id,
        "completed_at_dt": completed_at_dt,
        "completed_at": completed_at_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project": (lead.get("project") or (projects[0] if projects else None)),
        "projects": projects,
        "assigned_user_id": lead.get("assigned_user_id"),
        "assigned_to_name": lead.get("assigned_to_name") or lead.get("assigned_to"),
        "actor_user_id": None,
        "actor_name": "backfill",
        "lead_name": _lead_name(lead),
        "phone": lead.get("phone"),
        "backfill": True,
    }


def assert_db_allowed(*, prod: bool) -> str:
    db_name = (os.environ.get("DB_NAME") or "").strip()
    mongo = (os.environ.get("MONGO_URL") or "").strip()
    if not db_name or not mongo:
        raise SystemExit("REFUSE: MONGO_URL and DB_NAME must be set")
    if db_name == "arihant_crm":
        if not prod:
            raise SystemExit(
                "REFUSE: DB_NAME=arihant_crm requires explicit --prod "
                "(or use arihant_crm_e2e without --prod)"
            )
    elif db_name == "arihant_crm_e2e":
        if prod:
            raise SystemExit("REFUSE: --prod with DB_NAME=arihant_crm_e2e makes no sense")
    else:
        raise SystemExit(
            f"REFUSE: unexpected DB_NAME={db_name!r}; "
            "allowed: arihant_crm (--prod) or arihant_crm_e2e"
        )
    return db_name


def run(*, apply: bool, prod: bool) -> int:
    db_name = assert_db_allowed(prod=prod)
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[db_name]
    leads = db.leads
    events = db.site_visit_events

    existing_keys: Set[Tuple[str, str]] = set()
    leads_with_any_event: Set[str] = set()
    for doc in events.find({}, {"lead_id": 1, "completed_at_dt": 1}):
        lid = doc.get("lead_id")
        if not lid:
            continue
        leads_with_any_event.add(lid)
        dt = _as_dt(doc.get("completed_at_dt"))
        if dt:
            existing_keys.add(_event_key(lid, dt))

    candidates: List[Dict[str, Any]] = []
    source_b = 0
    source_a = 0
    scanned = 0

    query = {
        "$or": [
            {"visit_completed_at_dt": {"$exists": True, "$ne": None}},
            {"lead_status": {"$regex": "^visit completed$", "$options": "i"}},
            {"context_updates.changes.to": {"$regex": "^visit completed$", "$options": "i"}},
        ]
    }
    projection = {
        "id": 1,
        "first_name": 1,
        "last_name": 1,
        "name": 1,
        "phone": 1,
        "project": 1,
        "projects": 1,
        "assigned_user_id": 1,
        "assigned_to": 1,
        "assigned_to_name": 1,
        "visit_completed_at_dt": 1,
        "context_updates": 1,
        "lead_status": 1,
    }

    for lead in leads.find(query, projection):
        scanned += 1
        lead_id = lead.get("id")
        if not lead_id:
            continue

        timeline_dts = extract_timeline_completions(lead)
        for ts in timeline_dts:
            key = _event_key(lead_id, ts)
            if key in existing_keys:
                continue
            existing_keys.add(key)
            candidates.append(build_event_doc(lead, ts))
            source_b += 1

        # Source A: first-stamp field only when this lead still has zero events (existing or queued)
        if lead_id not in leads_with_any_event and not timeline_dts:
            stamp = _as_dt(lead.get("visit_completed_at_dt"))
            if stamp:
                key = _event_key(lead_id, stamp)
                if key not in existing_keys:
                    existing_keys.add(key)
                    candidates.append(build_event_doc(lead, stamp))
                    source_a += 1
                    leads_with_any_event.add(lead_id)
        elif lead_id not in leads_with_any_event and timeline_dts:
            # Timeline covered it; mark as having events once inserted
            leads_with_any_event.add(lead_id)

    # Second pass Source A for leads that had visit_completed_at_dt but timeline missed
    # and still no event after Source B candidates for that lead
    pending_by_lead: Set[str] = {c["lead_id"] for c in candidates}
    for lead in leads.find(
        {"visit_completed_at_dt": {"$exists": True, "$ne": None}},
        projection,
    ):
        lead_id = lead.get("id")
        if not lead_id:
            continue
        if lead_id in leads_with_any_event or lead_id in pending_by_lead:
            continue
        stamp = _as_dt(lead.get("visit_completed_at_dt"))
        if not stamp:
            continue
        key = _event_key(lead_id, stamp)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        candidates.append(build_event_doc(lead, stamp))
        source_a += 1
        pending_by_lead.add(lead_id)

    print(f"Database: {db_name}")
    print(f"Existing events: {events.count_documents({})}")
    print(f"Leads scanned (union query): {scanned}")
    print(f"Candidates to insert: {len(candidates)} (source_A={source_a}, source_B={source_b})")
    print(f"Mode: {'APPLY' if apply else 'DRY-RUN'}")

    # Always ensure indexes so period filters work on Atlas (range without index can return 0).
    def _ensure_index(keys, **kwargs):
        try:
            events.create_index(keys, **kwargs)
        except Exception as exc:  # noqa: BLE001 — name conflicts / already exists are fine
            print(f"  index note ({kwargs.get('name') or keys}): {exc}")

    _ensure_index([("completed_at_dt", 1)], name="site_visit_events_completed_at_dt")
    _ensure_index([("lead_id", 1), ("completed_at_dt", 1)], name="site_visit_events_lead_completed")
    _ensure_index([("assigned_user_id", 1), ("completed_at_dt", 1)], name="site_visit_events_owner_completed")
    _ensure_index([("id", 1)], unique=True, name="site_visit_events_id_uq")
    print("Indexes ensured.")

    if not apply:
        for sample in candidates[:5]:
            print(
                f"  sample lead={sample['lead_id']} "
                f"at={sample['completed_at_dt']} project={sample.get('project')!r}"
            )
        if len(candidates) > 5:
            print(f"  … {len(candidates) - 5} more")
        return 0

    if not candidates:
        print("Nothing to insert.")
        return 0

    result = events.insert_many(candidates, ordered=False)
    print(f"Inserted: {len(result.inserted_ids)}")
    print(f"Events now: {events.count_documents({})}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill site_visit_events from historical Visit Completed data")
    parser.add_argument("--dry-run", action="store_true", help="Report only (default if --apply omitted)")
    parser.add_argument("--apply", action="store_true", help="Insert events")
    parser.add_argument(
        "--prod",
        action="store_true",
        help="Required when DB_NAME=arihant_crm",
    )
    args = parser.parse_args()
    apply = bool(args.apply)
    if args.dry_run:
        apply = False
    raise SystemExit(run(apply=apply, prod=bool(args.prod)))


if __name__ == "__main__":
    main()
