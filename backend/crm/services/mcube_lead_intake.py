"""Create leads for unknown MCUBE inbound callers (assigned to Admin / Roshni)."""

from __future__ import annotations

import uuid
from typing import Optional

from pymongo.errors import DuplicateKeyError

from crm.core.state import db, iso_utc_now, logger, utc_now
from crm.services.notification_service import create_notification
from crm.services.nurture_temperature import apply_nurture_temperature_rules
from crm.services.whatsapp_service import ADMIN_WA_ASSIGNEE_NAME, resolve_admin_wa_assignee
from crm.utils.helpers import determine_lead_intent, is_vip_lead, normalize_phone


def _split_caller_name(caller_name: str, phone: str) -> tuple[str, str]:
    name = (caller_name or "").strip()
    if not name:
        last4 = (phone or "")[-4:] or "????"
        return f"Inbound {last4}", ""
    parts = name.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


async def create_mcube_unknown_lead(
    phone: str,
    caller_name: str = "",
    *,
    call_id: str = "",
    notify: bool = True,
) -> Optional[dict]:
    """
    Create a New lead for an unknown MCUBE inbound caller, assigned to Admin.
    Returns the lead dict, or None if phone invalid / create skipped.
    """
    normalized = normalize_phone(phone)
    if not normalized or len(normalized) != 10:
        logger.warning("MCUBE unknown lead skipped — invalid phone=%r normalized=%r", phone, normalized)
        return None

    existing = await db.leads.find_one({"normalized_phone": normalized}, {"_id": 0})
    if existing:
        return existing

    admin = await resolve_admin_wa_assignee()
    first_name, last_name = _split_caller_name(caller_name, normalized)
    lead_id = str(uuid.uuid4())
    now_dt = utc_now()
    now_iso = iso_utc_now()
    created_desc = "Lead created from MCUBE inbound call"
    assigned_desc = "Assigned to Admin from MCUBE inbound call"
    context_updates = [
        {
            "type": "created",
            "timestamp": now_iso,
            "timestamp_dt": now_dt,
            "description": created_desc,
            "agent": "MCUBE",
            "actor_user_id": "system-mcube",
            "actor_name": "MCUBE",
        }
    ]
    lead_dict = {
        "id": lead_id,
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone if str(phone).startswith("+") else normalized,
        "normalized_phone": normalized,
        "lead_status": "New",
        "lead_source": "MCUBE Inbound",
        "original_source": "MCUBE Inbound",
        "most_recent_source": "MCUBE Inbound",
        "site_visit_count": 0,
        "assigned_to": None,
        "assigned_to_name": None,
        "assigned_user_id": None,
        "presales_agent": None,
        "context_updates": context_updates,
        "created_at": now_iso,
        "created_at_dt": now_dt,
        "updated_at": now_iso,
        "updated_at_dt": now_dt,
        "mcube_origin_call_id": call_id or None,
    }
    if admin:
        admin_name = admin.get("full_name") or ADMIN_WA_ASSIGNEE_NAME
        lead_dict["assigned_to"] = admin_name
        lead_dict["assigned_to_name"] = admin_name
        lead_dict["assigned_user_id"] = admin["id"]
        lead_dict["presales_agent"] = admin_name
        lead_dict["assigned_at"] = now_iso
        lead_dict["assigned_at_dt"] = now_dt
        context_updates.append(
            {
                "type": "assigned",
                "timestamp": now_iso,
                "timestamp_dt": now_dt,
                "description": assigned_desc,
                "agent": "MCUBE",
                "actor_user_id": "system-mcube",
                "actor_name": "MCUBE",
            }
        )
    else:
        logger.warning("MCUBE unknown lead: Admin user not found; creating unassigned lead phone=%s", normalized)

    temp_patch = {"lead_status": "New"}
    apply_nurture_temperature_rules({}, temp_patch, is_create=True)
    lead_dict["temperature"] = temp_patch.get("temperature")
    lead_dict["intent"] = determine_lead_intent(lead_dict)
    lead_dict["vip"] = is_vip_lead(lead_dict)

    try:
        await db.leads.insert_one(lead_dict)
    except DuplicateKeyError:
        existing = await db.leads.find_one({"normalized_phone": normalized}, {"_id": 0})
        return existing

    if notify and admin and admin.get("id"):
        lead_name = f"{first_name} {last_name}".strip() or first_name
        try:
            await create_notification(
                recipient_user_id=admin["id"],
                recipient_name=admin.get("full_name") or ADMIN_WA_ASSIGNEE_NAME,
                title="New Lead Assigned",
                message=f"{lead_name} created from MCUBE inbound call",
                notification_type="new_lead_assigned",
                lead_id=lead_id,
                lead_name=lead_name,
                severity="high",
                urgency="action_needed",
                dedupe_key=f"mcube_unknown_create:{lead_id}",
            )
        except Exception as e:
            logger.warning("MCUBE unknown lead notify failed lead=%s: %s", lead_id, e)

    return lead_dict
