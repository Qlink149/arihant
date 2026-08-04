"""Active-agent routing (Q6): eligibility, waiting queue, Admin fallback."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from crm.core.state import db, iso_utc_now, utc_now
from crm.constants.lead_status import sla_paused_exclusion_clause
from crm.services.lead_events import log_lead_event
from crm.services.notification_service import create_notification
from crm.utils.business_time import is_business_hours_ist
from crm.utils.helpers import coerce_datetime

ROUTING_SETTINGS_KEY = "routing"


async def get_routing_settings() -> dict:
    doc = await db.app_settings.find_one({"key": ROUTING_SETTINGS_KEY}, {"_id": 0}) or {}
    return doc.get("value") or {}


def _new_lead_status_filter() -> dict:
    return {
        "$or": [
            {"lead_status": {"$regex": r"^\s*new\s*$", "$options": "i"}},
            {
                "$and": [
                    {"lead_status": {"$regex": r"^\s*open\s*$", "$options": "i"}},
                    {"original_fw_status": {"$regex": r"^\s*new\s*$", "$options": "i"}},
                ]
            },
        ]
    }


async def count_open_new_leads(user_id: str, full_name: str) -> int:
    """Active New leads for round-robin load (excludes SLA-paused imports)."""
    q = {
        **_new_lead_status_filter(),
        "sla_paused": sla_paused_exclusion_clause(),
        "$or": [
            {"assigned_user_id": user_id},
            {"assigned_to": full_name},
            {"presales_agent": full_name},
        ],
    }
    return await db.leads.count_documents(q)


async def is_active_for_routing(user: dict, now_dt: Optional[datetime] = None) -> bool:
    """Eligible for auto-assignment: active account, business hours, on duty today (IST)."""
    from crm.utils.business_time import is_on_duty_today

    now_dt = now_dt or utc_now()
    if not user.get("is_active", True):
        return False
    if not is_business_hours_ist(now_dt):
        return False

    activity = await db.user_activity.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
    return is_on_duty_today(activity, now_dt)


async def list_routing_eligible_agents(now_dt: Optional[datetime] = None) -> List[dict]:
    """Active reps sorted by fewest open New leads (round-robin pick = index 0)."""
    now_dt = now_dt or utc_now()
    users = await db.users.find(
        {
            "role": {"$regex": r"^\s*(rep|agent|sales|presales)\s*$", "$options": "i"},
            "is_active": {"$ne": False},
        },
        {"_id": 0, "id": 1, "full_name": 1, "role": 1},
    ).to_list(200)
    eligible = []
    for u in users:
        if await is_active_for_routing(u, now_dt):
            open_new = await count_open_new_leads(u["id"], u.get("full_name") or "")
            eligible.append({**u, "open_new_leads": open_new})
    eligible.sort(key=lambda x: x.get("open_new_leads", 0))
    return eligible


async def route_new_lead(lead_id: str) -> dict:
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        return {"ok": False, "reason": "not_found"}

    eligible = await list_routing_eligible_agents()
    now_dt = utc_now()
    now_iso = iso_utc_now()

    if not eligible:
        await db.leads.update_one(
            {"id": lead_id},
            {"$set": {"routing_state": "waiting", "updated_at": now_iso, "updated_at_dt": now_dt}},
        )
        await _notify_admin_waiting_queue(lead)
        return {"ok": True, "routing_state": "waiting"}

    agent = eligible[0]
    await _assign_lead(lead_id, agent["id"], agent.get("full_name") or "", reason="active_routing")
    return {"ok": True, "assigned_to": agent.get("full_name"), "assigned_user_id": agent["id"]}


async def reassign_new_lead(lead_id: str) -> dict:
    """1h SLA: round-robin to active agents; Admin only when none eligible."""
    eligible = await list_routing_eligible_agents()
    if eligible:
        agent = eligible[0]
        await _assign_lead(
            lead_id,
            agent["id"],
            agent.get("full_name") or "",
            reason="sla_1h_reroute",
        )
        await log_lead_event(
            "sla_action",
            lead_id=lead_id,
            actor_name="SLA Engine",
            payload={
                "action": "reassign_active_agent",
                "reason": "sla_1h_reroute",
                "assigned_user_id": agent["id"],
                "assigned_to": agent.get("full_name"),
            },
        )
        return {"ok": True, "assigned_to": agent.get("full_name"), "assigned_user_id": agent["id"]}

    admin = await db.users.find_one(
        {"role": {"$regex": r"^\s*admin\s*$", "$options": "i"}},
        {"_id": 0, "id": 1, "full_name": 1},
    )
    if not admin:
        return {"ok": False, "reason": "no_admin"}
    await _assign_lead(lead_id, admin["id"], admin.get("full_name") or "", reason="sla_1h_admin_fallback")
    await log_lead_event(
        "sla_action",
        lead_id=lead_id,
        actor_name="SLA Engine",
        payload={
            "action": "reassign_admin_fallback",
            "reason": "sla_1h_admin_fallback",
            "admin_id": admin["id"],
        },
    )
    return {"ok": True, "assigned_to": admin.get("full_name"), "fallback": "admin"}


async def reassign_new_lead_to_admin(lead_id: str) -> dict:
    """Backward-compatible alias."""
    return await reassign_new_lead(lead_id)


async def _assign_lead(lead_id: str, user_id: str, full_name: str, reason: str) -> None:
    now_dt = utc_now()
    now_iso = iso_utc_now()
    await db.leads.update_one(
        {"id": lead_id},
        {
            "$set": {
                "assigned_to": full_name,
                "assigned_to_name": full_name,
                "assigned_user_id": user_id,
                "presales_agent": full_name,
                "routing_state": "assigned",
                "updated_at": now_iso,
                "updated_at_dt": now_dt,
            },
            "$push": {
                "context_updates": {
                    "type": "assigned",
                    "timestamp": now_iso,
                    "timestamp_dt": now_dt,
                    "description": f"Routed to {full_name} ({reason})",
                    "agent": "System",
                }
            },
        },
    )
    await db.tasks.update_many(
        {
            "lead_id": lead_id,
            "status": {"$nin": ["completed", "cancelled", "done"]},
        },
        {
            "$set": {
                "assigned_to": full_name,
                "assigned_user_id": user_id,
                "updated_at": now_iso,
                "updated_at_dt": now_dt,
            }
        },
    )
    await create_notification(
        recipient_user_id=user_id,
        recipient_name=full_name,
        title="New Lead Assigned",
        message=f"Lead assigned via routing ({reason})",
        notification_type="action_required",
        lead_id=lead_id,
        dedupe_key=f"route:{lead_id}:{reason}",
    )


async def _notify_admin_waiting_queue(lead: dict) -> None:
    admin = await db.users.find_one(
        {"role": {"$regex": r"^\s*admin\s*$", "$options": "i"}},
        {"_id": 0, "id": 1, "full_name": 1},
    )
    if not admin:
        return
    today = utc_now().strftime("%Y-%m-%d")
    await create_notification(
        recipient_user_id=admin["id"],
        recipient_name=admin.get("full_name") or "",
        title="Leads waiting — no active agents",
        message=f"Lead {lead.get('first_name', '')} {lead.get('last_name', '')} queued for assignment",
        notification_type="system_warning",
        lead_id=lead.get("id", ""),
        dedupe_key=f"routing:waiting:{today}",
    )


async def process_waiting_queue(user_id: Optional[str] = None) -> int:
    """Assign FIFO waiting leads when an agent becomes eligible."""
    now_dt = utc_now()
    if user_id:
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user or not await is_active_for_routing(user, now_dt):
            return 0

    eligible = await list_routing_eligible_agents(now_dt)
    if not eligible:
        return 0

    waiting = (
        await db.leads.find(
            {"routing_state": "waiting", **_new_lead_status_filter()},
            {"_id": 0, "id": 1},
        )
        .sort("created_at_dt", 1)
        .to_list(50)
    )
    assigned = 0
    for lead in waiting:
        if not eligible:
            break
        agent = eligible[0]
        await _assign_lead(lead["id"], agent["id"], agent.get("full_name") or "", reason="waiting_queue")
        assigned += 1
        agent["open_new_leads"] = agent.get("open_new_leads", 0) + 1
        eligible.sort(key=lambda x: x.get("open_new_leads", 0))
    return assigned
