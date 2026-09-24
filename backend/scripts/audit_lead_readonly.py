"""Read-only audit: single lead by id and/or phone (prod-safe)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env", override=True)

DEFAULT_LEAD_ID = "d1953137-4a76-5939-b634-037a1f02b8a0"
DEFAULT_PHONE = "9361734026"


def _type_label(value: Any) -> str:
    if value is None:
        return "null"
    return type(value).__name__


def _audit_context_updates(updates: Any) -> List[str]:
    issues: List[str] = []
    if not isinstance(updates, list):
        issues.append(f"context_updates is {_type_label(updates)}, expected list")
        return issues
    for i, entry in enumerate(updates):
        if not isinstance(entry, dict):
            issues.append(f"context_updates[{i}] is {_type_label(entry)}, expected dict")
            continue
        desc = entry.get("description")
        if desc is not None and not isinstance(desc, str):
            issues.append(
                f"context_updates[{i}].description is {_type_label(desc)} "
                f"(type={entry.get('type')!r})"
            )
        names = entry.get("mentioned_names")
        if names is not None and not isinstance(names, list):
            issues.append(
                f"context_updates[{i}].mentioned_names is {_type_label(names)} "
                f"(type={entry.get('type')!r})"
            )
        changes = entry.get("changes")
        if changes is not None and not isinstance(changes, list):
            issues.append(f"context_updates[{i}].changes is {_type_label(changes)}")
    return issues


async def _print_lead_summary(lead: Optional[Dict[str, Any]], *, label: str) -> None:
    if not lead:
        print(f"{label}: NOT FOUND")
        return

    print(f"{label}:")
    print(f"  id={lead.get('id')}")
    print(f"  name={lead.get('first_name')} {lead.get('last_name')}")
    print(f"  phone={lead.get('phone')} normalized={lead.get('normalized_phone')}")
    print(f"  project={lead.get('project')} projects={lead.get('projects')}")
    print(f"  status={lead.get('lead_status')}")
    print(f"  assigned_user_id={lead.get('assigned_user_id')}")
    print(f"  assigned_to_name={lead.get('assigned_to_name')}")
    print(f"  assigned_to={lead.get('assigned_to')}")
    print(f"  presales_agent={lead.get('presales_agent')}")
    print(f"  nudge_pending={lead.get('nudge_pending')}")
    print(f"  last_nudged_at_dt={lead.get('last_nudged_at_dt')}")

    issues = _audit_context_updates(lead.get("context_updates"))
    cu = lead.get("context_updates") or []
    print(f"  context_updates count={len(cu) if isinstance(cu, list) else 'invalid'}")
    if issues:
        print("  TIMELINE ISSUES:")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print("  timeline shape: OK")

    moves = lead.get("strategic_next_moves")
    if moves is not None and not isinstance(moves, list):
        print(f"  strategic_next_moves is {_type_label(moves)} (expected list)")


async def _print_nudge_notifications(db, lead_id: str) -> None:
    notifs = await db.notifications.find(
        {"lead_id": lead_id, "notification_type": "admin_nudge"},
        {
            "_id": 0,
            "id": 1,
            "recipient_user_id": 1,
            "recipient_name": 1,
            "title": 1,
            "created_at_dt": 1,
            "is_read": 1,
        },
    ).sort("created_at_dt", -1).limit(10).to_list(10)

    print(f"admin_nudge notifications for lead (last 10): {len(notifs)}")
    for n in notifs:
        print(
            f"  id={n.get('id')} recipient={n.get('recipient_user_id')} "
            f"name={n.get('recipient_name')} read={n.get('is_read')} "
            f"at={n.get('created_at_dt')}"
        )


async def _resolve_assignee(db, lead: Dict[str, Any]) -> None:
    from crm.core.state import resolve_user_id_by_full_name

    assignee_id = (lead.get("assigned_user_id") or "").strip()
    assignee_name = (
        lead.get("assigned_to_name") or lead.get("assigned_to") or lead.get("presales_agent") or ""
    ).strip()
    resolved = ""
    if not assignee_id and assignee_name:
        resolved = (await resolve_user_id_by_full_name(assignee_name) or "").strip()

    print("assignee resolution:")
    print(f"  assigned_user_id={assignee_id or '(empty)'}")
    print(f"  assignee_name={assignee_name or '(empty)'}")
    print(f"  resolve_user_id_by_full_name={resolved or '(not resolved)'}")
    if assignee_name and not assignee_id and not resolved:
        print("  WARNING: nudge would fail with 400 (no assignee to nudge)")


async def _test_lead_response(lead: Dict[str, Any]) -> None:
    from crm.models.schemas.lead_schemas import LeadResponse
    from crm.services.lead_service import normalize_lead_for_response

    try:
        normalized = normalize_lead_for_response(dict(lead))
        LeadResponse(**normalized)
        print("LeadResponse validation: OK")
    except Exception as exc:  # noqa: BLE001 — audit script
        print(f"LeadResponse validation: FAILED — {exc}")


async def run(lead_id: str, phone: str) -> None:
    from crm.core.state import db

    db_name = os.getenv("DB_NAME") or ""
    print(f"DB_NAME={db_name}")
    print("=== LEAD AUDIT (read-only) ===")

    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    await _print_lead_summary(lead, label=f"lead by id {lead_id}")

    if lead:
        await _resolve_assignee(db, lead)
        await _test_lead_response(lead)
        await _print_nudge_notifications(db, lead_id)

    phone_leads = await db.leads.find(
        {
            "$or": [
                {"normalized_phone": phone},
                {"phone": phone},
                {"phone": f"+91{phone}"},
                {"phone": f"91{phone}"},
            ]
        },
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "phone": 1, "normalized_phone": 1},
    ).to_list(20)
    print(f"leads matching phone {phone}: {len(phone_leads)}")
    for pl in phone_leads:
        print(
            f"  id={pl.get('id')} name={pl.get('first_name')} {pl.get('last_name')} "
            f"phone={pl.get('phone')}"
        )
        if pl.get("id") != lead_id:
            full = await db.leads.find_one({"id": pl["id"]}, {"_id": 0})
            if full:
                issues = _audit_context_updates(full.get("context_updates"))
                if issues:
                    print(f"    TIMELINE ISSUES on duplicate id={pl.get('id')}:")
                    for issue in issues[:5]:
                        print(f"      - {issue}")

    print("DONE read-only")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only lead audit")
    parser.add_argument("--lead-id", default=DEFAULT_LEAD_ID)
    parser.add_argument("--phone", default=DEFAULT_PHONE)
    args = parser.parse_args()
    asyncio.run(run(args.lead_id, args.phone))


if __name__ == "__main__":
    main()
