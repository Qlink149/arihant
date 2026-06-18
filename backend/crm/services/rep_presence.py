"""Rep presence and SLA routing eligibility (ops read-only view)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from crm.core.platform_ops import get_blocked_assignee_values, is_blocked_assignee_name
from crm.core.state import coerce_datetime, db, utc_now
from crm.services.assignment_router import count_open_new_leads, is_active_for_routing
from crm.utils.business_time import is_business_hours_ist

_MANUAL_AWAY = frozenset({"unavailable", "on_break", "site_visit", "away"})


def compute_presence_status(activity: dict, now_dt: datetime) -> str:
    """online | idle | offline — same rules as GET /activity/team-status."""
    manual = activity.get("manual_status")
    if manual in _MANUAL_AWAY:
        return "offline"
    if manual == "available":
        return "online"

    last_dt = coerce_datetime(activity.get("last_active_dt")) or coerce_datetime(activity.get("last_active"))
    if not last_dt:
        return "offline"
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    minutes_ago = (now_dt - last_dt).total_seconds() / 60
    if minutes_ago <= 30:
        return "online"
    if minutes_ago <= 60:
        return "idle"
    return "offline"


def routing_ineligible_reason(user: dict, activity: dict, *, now_dt: datetime) -> Optional[str]:
    """Mirror is_active_for_routing() checks; return reason code or None if eligible."""
    if not user.get("is_active", True):
        return "account_inactive"
    if not is_business_hours_ist(now_dt):
        return "outside_business_hours"

    manual = (activity.get("manual_status") or "available").strip().lower()
    if manual in _MANUAL_AWAY:
        return "manual_on_break"

    last = coerce_datetime(activity.get("last_active_dt")) or coerce_datetime(activity.get("last_active"))
    if not last:
        return "no_recent_heartbeat"
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if (now_dt - last).total_seconds() > 60 * 60:
        return "no_recent_heartbeat"

    return None


def _minutes_since(last_dt: Optional[datetime], now_dt: datetime) -> Optional[int]:
    if not last_dt:
        return None
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    return int((now_dt - last_dt).total_seconds() / 60)


async def list_rep_presence_for_ops() -> List[dict]:
    now_dt = utc_now()
    blocked = await get_blocked_assignee_values()

    users = await db.users.find(
        {"role": {"$regex": r"^\s*rep\s*$", "$options": "i"}, "is_active": {"$ne": False}},
        {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1, "is_active": 1},
    ).sort("full_name", 1).to_list(100)

    activities = await db.user_activity.find({}, {"_id": 0}).to_list(200)
    activity_by_user = {a.get("user_id"): a for a in activities if a.get("user_id")}

    result: List[dict] = []
    for user in users:
        email = (user.get("email") or "").strip().lower()
        name = (user.get("full_name") or "").strip()
        if is_blocked_assignee_name(email, blocked) or is_blocked_assignee_name(name, blocked):
            continue

        activity = activity_by_user.get(user["id"], {})
        full_name = user.get("full_name") or ""
        open_new = await count_open_new_leads(user["id"], full_name)
        routing_eligible = await is_active_for_routing(user, now_dt)
        reason = routing_ineligible_reason(user, activity, now_dt=now_dt)

        last_dt = coerce_datetime(activity.get("last_active_dt")) or coerce_datetime(activity.get("last_active"))
        last_iso = last_dt.astimezone(timezone.utc).isoformat() if last_dt else None

        result.append(
            {
                "id": user.get("id"),
                "full_name": full_name,
                "email": user.get("email"),
                "presence": compute_presence_status(activity, now_dt),
                "manual_status": activity.get("manual_status"),
                "last_active_dt": last_iso,
                "minutes_since_active": _minutes_since(last_dt, now_dt),
                "routing_eligible": routing_eligible,
                "routing_ineligible_reason": reason,
                "open_new_leads": open_new,
                "within_business_hours": is_business_hours_ist(now_dt),
            }
        )

    return result
