"""Shared SLA task/notification creation outside the bulk SLA engine run."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from crm.core.state import db, iso_utc_now, utc_now
from crm.services.lead_events import log_lead_event
from crm.services.notification_service import create_notification
from crm.utils.helpers import coerce_datetime


async def _name_map() -> dict:
    users = await db.users.find({}, {"_id": 0, "id": 1, "full_name": 1}).to_list(500)
    return {u["full_name"]: u["id"] for u in users if u.get("full_name") and u.get("id")}


async def create_sla_task_for_lead(
    lead: dict,
    *,
    description: str,
    dedupe_key: str,
    sla_rule: str,
    sla_threshold: str,
    priority: str = "medium",
    escalation_target: Optional[str] = None,
    stage: str = "",
) -> Optional[str]:
    """Insert task + notification + audit event. Returns task_id or None."""
    if lead.get("sla_paused"):
        return None
    now_dt = utc_now()
    now_iso = iso_utc_now()
    name_to_user_id = await _name_map()

    from crm.services.sla_engine import build_task_doc

    escalation_user = None
    if escalation_target:
        role = escalation_target
        escalation_user = await db.users.find_one(
            {"role": {"$regex": rf"^\s*{role}\s*$", "$options": "i"}},
            {"_id": 0, "id": 1, "full_name": 1},
        )

    task = build_task_doc(
        lead=lead,
        description=description,
        dedupe_key=dedupe_key,
        now_dt=now_dt,
        now_iso=now_iso,
        name_to_user_id=name_to_user_id,
        escalation_user=escalation_user,
        priority=priority,
        sla_rule=sla_rule,
        sla_threshold=sla_threshold,
    )
    if not task:
        return None

    try:
        await db.tasks.insert_one(task)
    except Exception:
        existing = await db.tasks.find_one({"dedupe_key": dedupe_key}, {"_id": 0, "id": 1})
        if existing:
            return existing.get("id")
        raise

    uid = task.get("assigned_user_id")
    if uid:
        await create_notification(
            recipient_user_id=uid,
            recipient_name=task.get("assigned_to", ""),
            title=f"SLA: {description[:50]}",
            message=f"Task for {task.get('lead_name', '')}",
            notification_type="action_required",
            lead_id=lead["id"],
            lead_name=task.get("lead_name", ""),
            task_id=task["id"],
            stage=stage or sla_rule,
            sla_threshold=sla_threshold,
            severity="high" if priority == "high" else "medium",
            dedupe_key=f"notif:{dedupe_key}",
        )

    await log_lead_event(
        "sla_action",
        lead_id=lead["id"],
        actor_name="SLA Engine",
        payload={
            "action": "task_created",
            "sla_rule": sla_rule,
            "sla_threshold": sla_threshold,
            "task_id": task["id"],
            "dedupe_key": dedupe_key,
        },
    )
    return task["id"]


async def assign_lead_to_admin(lead_id: str, reason: str = "sla_escalation") -> bool:
    admin = await db.users.find_one(
        {"role": {"$regex": r"^\s*admin\s*$", "$options": "i"}},
        {"_id": 0, "id": 1, "full_name": 1},
        sort=[("id", 1)],
    )
    if not admin or not admin.get("id"):
        return False
    now_dt = utc_now()
    now_iso = iso_utc_now()
    admin_name = admin.get("full_name") or ""
    await db.leads.update_one(
        {"id": lead_id},
        {
            "$set": {
                "assigned_to": admin_name,
                "assigned_to_name": admin_name,
                "assigned_user_id": admin["id"],
                "presales_agent": admin_name,
                "follow_up_delayed": True,
                "updated_at": now_iso,
                "updated_at_dt": now_dt,
            }
        },
    )
    # Keep open follow-up work with the new owner (otherwise RNR reminders stay on the rep).
    await db.tasks.update_many(
        {
            "lead_id": lead_id,
            "status": {"$nin": ["completed", "cancelled", "done"]},
        },
        {
            "$set": {
                "assigned_to": admin_name,
                "assigned_user_id": admin["id"],
                "updated_at": now_iso,
                "updated_at_dt": now_dt,
            }
        },
    )
    await log_lead_event(
        "sla_action",
        lead_id=lead_id,
        actor_name="SLA Engine",
        payload={"action": "reassign_admin", "reason": reason, "admin_id": admin["id"]},
    )
    return True


