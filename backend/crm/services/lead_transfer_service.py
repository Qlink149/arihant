"""Shared lead assignment / transfer path used by single transfer and bulk-update."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import HTTPException

from crm.core.platform_ops import assert_assignee_allowed
from crm.core.state import db, iso_utc_now, resolve_user_id_by_full_name, utc_now
from crm.services.lead_events import log_lead_event
from crm.services.notification_service import create_notification


async def assign_lead_ownership(
    *,
    lead: dict,
    to_rep: str,
    to_user_id: Optional[str] = None,
    current_user: dict,
    notes: Optional[str] = None,
    expected_from_user_id: Optional[str] = None,
) -> str:
    """Assign a lead to a user: transfer record + ownership update + notification.

    Returns transfer_id. Raises HTTPException on validation / ownership conflict.
    """
    await assert_assignee_allowed(to_rep)

    from_rep = lead.get("assigned_to") or lead.get("presales_agent") or current_user["full_name"]
    transfer_id = str(uuid.uuid4())
    now_dt = utc_now()
    now_iso = iso_utc_now()

    from_user_id = await resolve_user_id_by_full_name(from_rep)
    resolved_to_user_id = to_user_id or await resolve_user_id_by_full_name(to_rep)
    if not resolved_to_user_id:
        raise HTTPException(status_code=400, detail="to_user_id is required (no matching user for to_rep)")

    target_user = await db.users.find_one(
        {"id": resolved_to_user_id}, {"_id": 0, "email": 1, "full_name": 1}
    )
    if target_user:
        await assert_assignee_allowed(target_user.get("full_name"))
        await assert_assignee_allowed(target_user.get("email"))

    lead_id = lead["id"]
    transfer_doc: Dict[str, Any] = {
        "id": transfer_id,
        "lead_id": lead_id,
        "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}",
        "from_rep": from_rep,
        "from_name": from_rep,
        "from_user_id": from_user_id,
        "to_rep": to_rep,
        "to_name": to_rep,
        "to_user_id": resolved_to_user_id,
        "notes": notes,
        "lead_temperature": lead.get("temperature") or "—",
        "project": lead.get("project", ""),
        "transferred_at": now_iso,
        "transferred_at_dt": now_dt,
        "transferred_by": current_user["full_name"],
        "transferred_by_user_id": current_user.get("id"),
    }
    await db.lead_transfers.insert_one(transfer_doc)

    lead_filter: Dict[str, Any] = {"id": lead_id}
    if expected_from_user_id:
        lead_filter["assigned_user_id"] = expected_from_user_id

    res = await db.leads.update_one(
        lead_filter,
        {
            "$set": {
                "assigned_to": to_rep,
                "assigned_to_name": to_rep,
                "assigned_user_id": resolved_to_user_id,
                "presales_agent": to_rep,
                "updated_at": now_iso,
                "updated_at_dt": now_dt,
            },
            "$push": {
                "context_updates": {
                    "type": "transfer",
                    "timestamp": now_iso,
                    "timestamp_dt": now_dt,
                    "description": f"Transferred from {from_rep} to {to_rep}"
                    + (f". Notes: {notes}" if notes else ""),
                    "agent": current_user["full_name"],
                    "actor_user_id": current_user.get("id"),
                    "actor_name": current_user.get("full_name"),
                }
            },
        },
    )
    if res.matched_count == 0:
        await db.lead_transfers.delete_one({"id": transfer_id})
        raise HTTPException(
            status_code=409,
            detail="Lead ownership changed. Refresh and retry the transfer.",
        )

    lead_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
    transfer_message = (
        f"{lead_name} assigned by {current_user['full_name']}"
        + (f". Notes: {notes}" if notes else "")
    )
    await create_notification(
        recipient_user_id=resolved_to_user_id,
        recipient_name=to_rep,
        title="Lead Assigned to You",
        message=transfer_message,
        notification_type="lead_transferred",
        lead_id=lead_id,
        lead_name=lead_name,
        severity="high",
        urgency="action_needed",
    )

    await log_lead_event(
        "transfer_created",
        lead_id=lead_id,
        actor_user_id=current_user.get("id"),
        actor_name=current_user.get("full_name"),
        payload={"transfer_id": transfer_id, "to_rep": to_rep, "from_rep": from_rep},
    )

    return transfer_id
