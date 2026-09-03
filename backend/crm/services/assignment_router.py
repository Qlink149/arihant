"""Project-pool inbound routing, waiting queue, and 1h pool fallback."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from crm.core.state import db, iso_utc_now, utc_now
from crm.constants.lead_status import sla_paused_exclusion_clause
from crm.services.lead_events import log_lead_event
from crm.services.notification_service import create_notification
from crm.services.project_assignment_pools import (
    ROSHNI_EMAIL,
    fallback_ordered_emails,
    get_pool,
    hop_uses_round_robin,
    next_hop_emails,
    normalize_email,
    pool_escalates,
    pool_key_for_lead,
)
from crm.utils.business_time import is_business_hours_ist

ROUTING_SETTINGS_KEY = "routing"


async def get_routing_settings() -> dict:
    doc = await db.app_settings.find_one({"key": ROUTING_SETTINGS_KEY}, {"_id": 0}) or {}
    return doc.get("value") or {}


def _new_lead_status_filter() -> dict:
    """New / blank status (create form used to leave status empty)."""
    return {
        "$or": [
            {"lead_status": {"$regex": r"^\s*new\s*$", "$options": "i"}},
            {"lead_status": {"$in": [None, ""]}},
            {"lead_status": {"$exists": False}},
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
        "$and": [
            _new_lead_status_filter(),
            {"sla_paused": sla_paused_exclusion_clause()},
            {
                "$or": [
                    {"assigned_user_id": user_id},
                    {"assigned_to": full_name},
                    {"presales_agent": full_name},
                ]
            },
        ]
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


def _is_admin_role(user: dict) -> bool:
    return bool(re.match(r"^\s*admin\s*$", str(user.get("role") or ""), re.I))


async def is_pool_member_eligible(user: dict, now_dt: Optional[datetime] = None) -> bool:
    """Pool eligibility: reps need duty + business hours; admins only need an active account."""
    from crm.core.platform_ops import is_blocked_assignee

    now_dt = now_dt or utc_now()
    if not user or not user.get("id"):
        return False
    if user.get("is_active", True) is False:
        return False
    if await is_blocked_assignee(user.get("email")) or await is_blocked_assignee(user.get("full_name")):
        return False
    if _is_admin_role(user):
        return True
    return await is_active_for_routing(user, now_dt)


async def list_routing_eligible_agents(now_dt: Optional[datetime] = None) -> List[dict]:
    """Active reps sorted by fewest open New leads (kept for ops/presence displays)."""
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


def _pool_emails(pool: dict) -> List[str]:
    seen = set()
    out: List[str] = []
    for email in list(pool.get("primary") or []) + fallback_ordered_emails(pool):
        key = normalize_email(email)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


async def resolve_users_by_emails(emails: Sequence[str]) -> Dict[str, dict]:
    wanted = [normalize_email(e) for e in emails if e]
    if not wanted:
        return {}
    clauses = [{"email": {"$regex": f"^{re.escape(e)}$", "$options": "i"}} for e in wanted]
    query = {"$or": clauses} if len(clauses) > 1 else clauses[0]
    users = await db.users.find(
        query,
        {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1, "is_active": 1},
    ).to_list(200)
    out: Dict[str, dict] = {}
    for u in users:
        key = normalize_email(u.get("email"))
        if key:
            out[key] = u
    return out


async def _eligible_users_in_order(
    emails: Sequence[str],
    users_by_email: Dict[str, dict],
    now_dt: datetime,
) -> List[dict]:
    out: List[dict] = []
    for email in emails:
        user = users_by_email.get(normalize_email(email))
        if not user:
            continue
        if await is_pool_member_eligible(user, now_dt):
            out.append(user)
    return out


async def _pick_from_candidates(
    emails: Sequence[str],
    users_by_email: Dict[str, dict],
    now_dt: datetime,
    *,
    use_rr: bool,
) -> Optional[dict]:
    eligible = await _eligible_users_in_order(emails, users_by_email, now_dt)
    if not eligible:
        return None
    if not use_rr:
        return eligible[0]
    scored = []
    for u in eligible:
        open_new = await count_open_new_leads(u["id"], u.get("full_name") or "")
        scored.append((open_new, u))
    scored.sort(key=lambda item: item[0])
    return scored[0][1]


def _history_emails_for_lead(lead: dict, users_by_email: Dict[str, dict]) -> List[str]:
    id_to_email = {u["id"]: normalize_email(u.get("email")) for u in users_by_email.values() if u.get("id")}
    history_ids = list(lead.get("pool_assignment_history") or [])
    emails: List[str] = []
    seen = set()
    for uid in history_ids:
        email = id_to_email.get(uid)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    current_id = lead.get("assigned_user_id")
    if current_id and current_id in id_to_email:
        email = id_to_email[current_id]
        if email not in seen:
            emails.append(email)
    return emails


async def _pick_pool_agent(lead: dict, *, initial: bool, now_dt: Optional[datetime] = None):
    now_dt = now_dt or utc_now()
    pool_key = pool_key_for_lead(lead)
    pool = get_pool(pool_key)
    users_by_email = await resolve_users_by_emails(_pool_emails(pool))
    history_emails = [] if initial else _history_emails_for_lead(lead, users_by_email)
    hop_emails = next_hop_emails(pool, history_emails, initial=initial)
    resolved_remaining = [e for e in hop_emails if e in users_by_email]
    agent = await _pick_from_candidates(
        hop_emails,
        users_by_email,
        now_dt,
        use_rr=hop_uses_round_robin(pool, initial=initial),
    )
    return {
        "pool_key": pool_key,
        "pool": pool,
        "agent": agent,
        "hop_emails": hop_emails,
        "resolved_remaining": resolved_remaining,
        "users_by_email": users_by_email,
    }


async def route_new_lead(lead_id: str) -> dict:
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        return {"ok": False, "reason": "not_found"}

    now_dt = utc_now()
    now_iso = iso_utc_now()
    picked = await _pick_pool_agent(lead, initial=True, now_dt=now_dt)
    pool_key = picked["pool_key"]
    agent = picked["agent"]

    if not agent:
        await db.leads.update_one(
            {"id": lead_id},
            {
                "$set": {
                    "routing_state": "waiting",
                    "pool_routing": True,
                    "pool_key": pool_key,
                    "updated_at": now_iso,
                    "updated_at_dt": now_dt,
                }
            },
        )
        await _notify_admin_waiting_queue(lead)
        return {"ok": True, "routing_state": "waiting", "pool_key": pool_key}

    await _assign_lead(
        lead_id,
        agent["id"],
        agent.get("full_name") or "",
        reason="active_routing",
        pool_key=pool_key,
        pool_routing=True,
    )
    return {
        "ok": True,
        "assigned_to": agent.get("full_name"),
        "assigned_user_id": agent["id"],
        "pool_key": pool_key,
    }


async def reassign_new_lead_in_pool(lead_id: str) -> dict:
    """1h SLA: next person in the lead's project pool. Does not use global RR."""
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        return {"ok": False, "reason": "not_found"}

    pool_key = lead.get("pool_key") or pool_key_for_lead(lead)
    if not pool_escalates(pool_key):
        return {"ok": False, "reason": "no_escalate", "exhausted": True}

    picked = await _pick_pool_agent(lead, initial=False)
    if not picked["hop_emails"] or not picked["resolved_remaining"]:
        return {"ok": False, "reason": "chain_exhausted", "exhausted": True}

    agent = picked["agent"]
    if not agent:
        return {"ok": False, "reason": "no_eligible", "exhausted": False}

    await _assign_lead(
        lead_id,
        agent["id"],
        agent.get("full_name") or "",
        reason="sla_1h_reroute",
        pool_key=pool_key,
        pool_routing=True,
    )
    await log_lead_event(
        "sla_action",
        lead_id=lead_id,
        actor_name="SLA Engine",
        payload={
            "action": "reassign_pool",
            "reason": "sla_1h_reroute",
            "pool_key": pool_key,
            "assigned_user_id": agent["id"],
            "assigned_to": agent.get("full_name"),
        },
    )
    return {
        "ok": True,
        "assigned_to": agent.get("full_name"),
        "assigned_user_id": agent["id"],
        "pool_key": pool_key,
    }


async def reassign_new_lead(lead_id: str) -> dict:
    """Backward-compatible alias for the 1h pool reassign path."""
    return await reassign_new_lead_in_pool(lead_id)


async def reassign_new_lead_to_admin(lead_id: str) -> dict:
    """Backward-compatible alias."""
    return await reassign_new_lead_in_pool(lead_id)


async def _assign_lead(
    lead_id: str,
    user_id: str,
    full_name: str,
    reason: str,
    *,
    pool_key: Optional[str] = None,
    pool_routing: bool = False,
) -> None:
    now_dt = utc_now()
    now_iso = iso_utc_now()
    existing = await db.leads.find_one(
        {"id": lead_id},
        {"_id": 0, "pool_assignment_history": 1, "pool_key": 1},
    ) or {}
    history = list(existing.get("pool_assignment_history") or [])
    if user_id and user_id not in history:
        history.append(user_id)
    resolved_pool_key = pool_key or existing.get("pool_key")

    set_fields = {
        "assigned_to": full_name,
        "assigned_to_name": full_name,
        "assigned_user_id": user_id,
        "presales_agent": full_name,
        "routing_state": "assigned",
        "assigned_at": now_iso,
        "assigned_at_dt": now_dt,
        "updated_at": now_iso,
        "updated_at_dt": now_dt,
        "pool_assignment_history": history,
    }
    if pool_routing:
        set_fields["pool_routing"] = True
    if resolved_pool_key:
        set_fields["pool_key"] = resolved_pool_key

    await db.leads.update_one(
        {"id": lead_id},
        {
            "$set": set_fields,
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
        dedupe_key=f"route:{lead_id}:{reason}:{user_id}",
    )


async def _notify_admin_waiting_queue(lead: dict) -> None:
    admin = await db.users.find_one(
        {"email": {"$regex": f"^{re.escape(ROSHNI_EMAIL)}$", "$options": "i"}},
        {"_id": 0, "id": 1, "full_name": 1},
    )
    if not admin:
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
    """Assign FIFO waiting leads from each lead's project pool when someone is eligible.

    `user_id` is accepted for heartbeat callers. The queue is drained for any
    waiting lead whose own pool has an eligible member — not only that user.
    """
    now_dt = utc_now()
    waiting = (
        await db.leads.find(
            {"routing_state": "waiting", **_new_lead_status_filter()},
            {
                "_id": 0,
                "id": 1,
                "project": 1,
                "project_id": 1,
                "pool_key": 1,
                "pool_assignment_history": 1,
                "assigned_user_id": 1,
                "first_name": 1,
                "last_name": 1,
            },
        )
        .sort("created_at_dt", 1)
        .to_list(50)
    )
    assigned = 0
    for lead in waiting:
        picked = await _pick_pool_agent(lead, initial=True, now_dt=now_dt)
        agent = picked["agent"]
        if not agent:
            continue
        await _assign_lead(
            lead["id"],
            agent["id"],
            agent.get("full_name") or "",
            reason="waiting_queue",
            pool_key=picked["pool_key"],
            pool_routing=True,
        )
        assigned += 1
    return assigned
