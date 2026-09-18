"""SLA-safe lead assignment from MCUBE inbound (never bumps updated_at_dt)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from crm.core.state import db, iso_utc_now, logger, utc_now
from crm.services.notification_service import create_notification


async def apply_mcube_inbound_assignment(
    lead_id: str,
    answering_agent: Dict[str, Any],
    *,
    call_id: str = "",
) -> bool:
    """
    Assign or reassign lead to the MCUBE agent who handled the call (empemail match).
    If the lead had a different owner, notify the previous owner in-app.
    SLA-safe: never touches updated_at / updated_at_dt.
    """
    assignee_id = (answering_agent or {}).get("id") or ""
    if not lead_id or not assignee_id:
        return False

    assignee_name = (
        (answering_agent.get("full_name") or answering_agent.get("email") or "").strip()
    )
    if not assignee_name:
        return False

    lead = await db.leads.find_one(
        {"id": lead_id},
        {
            "_id": 0,
            "id": 1,
            "assigned_user_id": 1,
            "assigned_to": 1,
            "assigned_to_name": 1,
            "first_name": 1,
            "last_name": 1,
        },
    )
    if not lead:
        return False

    prev_uid = (lead.get("assigned_user_id") or "").strip()
    if prev_uid == assignee_id:
        return False

    from_name = (lead.get("assigned_to") or lead.get("assigned_to_name") or "").strip() or "Unassigned"
    now_dt = utc_now()
    now_iso = iso_utc_now()
    had_owner = bool(prev_uid)
    entry_type = "transfer" if had_owner else "assigned"
    if had_owner:
        description = f"Transferred from {from_name} to {assignee_name} from MCUBE inbound call"
    else:
        empemail = (answering_agent.get("email") or "").strip()
        description = f"Assigned to {assignee_name} from MCUBE inbound call"
        if empemail:
            description = f"{description} ({empemail})"

    await db.leads.update_one(
        {"id": lead_id},
        {
            "$set": {
                "assigned_user_id": assignee_id,
                "assigned_to": assignee_name,
                "assigned_to_name": assignee_name,
                "presales_agent": assignee_name,
                "assigned_at": now_iso,
                "assigned_at_dt": now_dt,
            },
            "$push": {
                "context_updates": {
                    "type": entry_type,
                    "timestamp": now_iso,
                    "timestamp_dt": now_dt,
                    "description": description,
                    "agent": "MCUBE",
                    "actor_user_id": assignee_id,
                    "actor_name": assignee_name,
                }
            },
        },
    )

    lead_name = f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip() or "Lead"

    if had_owner and prev_uid:
        try:
            await create_notification(
                recipient_user_id=prev_uid,
                recipient_name=from_name,
                title="Lead reassigned",
                message=f"{lead_name} reassigned to {assignee_name} after MCUBE inbound call",
                notification_type="lead_transferred",
                lead_id=lead_id,
                lead_name=lead_name,
                severity="medium",
                urgency="info",
                dedupe_key=f"mcube:prev_owner:{lead_id}:{call_id or assignee_id}",
            )
        except Exception as e:
            logger.warning("MCUBE previous-owner notify failed lead=%s: %s", lead_id, e)

    return True


async def assign_mcube_agent_to_lead(
    lead_id: str,
    user: Dict[str, Any],
    *,
    reason: str = "",
    notify: bool = True,
    call_id: str = "",
) -> bool:
    """Backward-compatible wrapper."""
    return await apply_mcube_inbound_assignment(lead_id, user, call_id=call_id)
