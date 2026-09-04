"""Nudge-pending flag: set on admin/manager nudge, cleared when assignee acts."""
from __future__ import annotations

from typing import Any, Dict, Optional

from crm.core.state import db, iso_utc_now, utc_now


def actor_is_lead_assignee(lead: Dict[str, Any], actor: Optional[Dict[str, Any]]) -> bool:
    if not lead or not actor:
        return False
    actor_id = (actor.get("id") or "").strip()
    if not actor_id:
        return False
    assignee_id = (lead.get("assigned_user_id") or "").strip()
    return bool(assignee_id) and assignee_id == actor_id


async def clear_nudge_pending_if_assignee(
    lead_id: str,
    actor: Optional[Dict[str, Any]],
    *,
    lead: Optional[Dict[str, Any]] = None,
) -> bool:
    """Clear nudge_pending when the current assignee acts. Returns True if cleared."""
    if not lead_id or not actor:
        return False
    doc = lead
    if doc is None:
        doc = await db.leads.find_one(
            {"id": lead_id},
            {"_id": 0, "assigned_user_id": 1, "nudge_pending": 1},
        )
    if not doc or not doc.get("nudge_pending"):
        return False
    if not actor_is_lead_assignee(doc, actor):
        return False
    now_dt = utc_now()
    await db.leads.update_one(
        {"id": lead_id, "nudge_pending": True},
        {
            "$set": {
                "nudge_pending": False,
                "nudge_cleared_at": iso_utc_now(),
                "nudge_cleared_at_dt": now_dt,
                "updated_at": iso_utc_now(),
                "updated_at_dt": now_dt,
            }
        },
    )
    return True
