"""Rep presence and SLA routing eligibility (ops read-only view)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from crm.core.platform_ops import get_blocked_assignee_values, is_blocked_assignee_name
from crm.core.state import coerce_datetime, db, utc_now
from crm.services.assignment_router import count_open_new_leads, is_active_for_routing
from crm.utils.business_time import (
    BUSINESS_END,
    BUSINESS_START,
    business_closes_ist,
    is_business_hours_ist,
    is_on_duty_today,
    next_business_open_ist,
)

IST = ZoneInfo("Asia/Kolkata")

# Roles shown on Active Status (ops visibility). Routing pool stays rep-only elsewhere.
_ACTIVE_STATUS_ROLES = r"^\s*(rep|admin)\s*$"


def compute_presence_status(activity: dict, now_dt: datetime) -> str:
    """online | offline — per IST calendar day (logged in / active today)."""
    if is_on_duty_today(activity or {}, now_dt):
        return "online"
    return "offline"


def routing_ineligible_reason(user: dict, activity: dict, *, now_dt: datetime) -> Optional[str]:
    """Mirror is_active_for_routing() checks; return reason code or None if eligible."""
    if not user.get("is_active", True):
        return "account_inactive"
    if not is_business_hours_ist(now_dt):
        return "outside_business_hours"
    if not is_on_duty_today(activity or {}, now_dt):
        return "not_on_duty_today"
    return None


def _fmt_ist_clock(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    return dt.astimezone(IST).strftime("%I:%M %p IST").lstrip("0")


def _fmt_ist_datetime(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    return dt.astimezone(IST).strftime("%a %d %b, %I:%M %p IST").replace(" 0", " ")


def sla_pause_summary(
    *,
    routing_eligible: bool,
    reason: Optional[str],
    manual_status: Optional[str] = None,
    now_dt: datetime,
) -> dict:
    """
    Human-readable SLA routing pause state for Active Status.
    Manual break/away does NOT pause SLA. Pause only for: inactive account,
    outside business hours, or not on duty today (IST).
    """
    within = is_business_hours_ist(now_dt)
    closes = business_closes_ist(now_dt)
    opens = next_business_open_ist(now_dt)
    hours_label = (
        f"Mon–Sat {BUSINESS_START.strftime('%H:%M')}–{BUSINESS_END.strftime('%H:%M')} IST"
    )

    if routing_eligible:
        return {
            "sla_paused": False,
            "sla_pause_when": "active",
            "sla_pause_label": "Not paused — eligible for SLA routing",
            "sla_pause_until": _fmt_ist_clock(closes),
            "sla_pause_detail": (
                f"On duty today. Auto-routing pauses for everyone after {_fmt_ist_clock(closes)} "
                f"({hours_label})."
            ),
            "business_hours_label": hours_label,
            "business_closes_at": closes.isoformat() if closes else None,
            "next_business_open_at": opens.isoformat() if opens else None,
            "within_business_hours": within,
        }

    if reason == "outside_business_hours":
        detail = (
            f"Outside working hours ({hours_label}). "
            f"SLA routing resumes {_fmt_ist_datetime(opens)}."
        )
        when = "outside_hours"
        label = "Paused — outside working hours"
        until = _fmt_ist_datetime(opens)
    elif reason == "not_on_duty_today":
        detail = (
            "No login or activity today (IST). User must log in today to be eligible "
            "for SLA auto-routing."
        )
        when = "not_on_duty_today"
        label = "Paused — not on duty today"
        until = None
    elif reason == "account_inactive":
        detail = "Account disabled — SLA routing paused until the account is reactivated."
        when = "account"
        label = "Paused — account disabled"
        until = None
    else:
        detail = "SLA routing not eligible."
        when = reason or "unknown"
        label = "Paused"
        until = None

    return {
        "sla_paused": True,
        "sla_pause_when": when,
        "sla_pause_label": label,
        "sla_pause_until": until,
        "sla_pause_detail": detail,
        "business_hours_label": hours_label,
        "business_closes_at": closes.isoformat() if closes else None,
        "next_business_open_at": opens.isoformat() if opens else None,
        "within_business_hours": within,
    }


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
        {"role": {"$regex": _ACTIVE_STATUS_ROLES, "$options": "i"}, "is_active": {"$ne": False}},
        {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1, "is_active": 1},
    ).sort("full_name", 1).to_list(200)

    activities = await db.user_activity.find({}, {"_id": 0}).to_list(500)
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
        pause = sla_pause_summary(
            routing_eligible=routing_eligible,
            reason=reason,
            manual_status=activity.get("manual_status"),
            now_dt=now_dt,
        )

        last_dt = (
            coerce_datetime(activity.get("last_login_dt"))
            or coerce_datetime(activity.get("last_login"))
            or coerce_datetime(activity.get("last_active_dt"))
            or coerce_datetime(activity.get("last_active"))
        )
        last_iso = last_dt.astimezone(timezone.utc).isoformat() if last_dt else None

        result.append(
            {
                "id": user.get("id"),
                "full_name": full_name,
                "email": user.get("email"),
                "role": (user.get("role") or "").strip().lower() or "rep",
                "presence": compute_presence_status(activity, now_dt),
                "manual_status": activity.get("manual_status"),
                "last_active_dt": last_iso,
                "minutes_since_active": _minutes_since(last_dt, now_dt),
                "routing_eligible": routing_eligible,
                "routing_ineligible_reason": reason,
                "open_new_leads": open_new,
                "within_business_hours": is_business_hours_ist(now_dt),
                "on_duty_today": is_on_duty_today(activity, now_dt),
                **pause,
            }
        )

    result.sort(key=lambda r: (0 if r.get("role") == "admin" else 1, (r.get("full_name") or "").lower()))
    return result
