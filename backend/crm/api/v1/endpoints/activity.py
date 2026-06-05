from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from crm.core.platform_ops import get_blocked_assignee_values, is_blocked_assignee_name
from crm.core.state import coerce_datetime, db, get_current_user, iso_utc_now, utc_now
from crm.services.assignment_router import is_active_for_routing, process_waiting_queue
from crm.utils.business_time import is_business_hours_ist


router = APIRouter()


@router.post("/activity/heartbeat")
async def record_heartbeat(current_user: dict = Depends(get_current_user)):
    now_dt = utc_now()
    now_iso = iso_utc_now()
    doc = await db.user_activity.find_one({"user_id": current_user["id"]}, {"_id": 0}) or {}
    manual = doc.get("manual_status") or "available"
    await db.user_activity.update_one(
        {"user_id": current_user["id"]},
        {
            "$set": {
                "user_id": current_user["id"],
                "full_name": current_user["full_name"],
                "last_active": now_iso,
                "last_active_dt": now_dt,
                "manual_status": manual,
            }
        },
        upsert=True,
    )
    assigned = await process_waiting_queue(current_user["id"])
    routing_eligible = await is_active_for_routing(current_user, now_dt)
    return {
        "status": "ok",
        "routing_eligible": routing_eligible,
        "within_business_hours": is_business_hours_ist(now_dt),
        "waiting_queue_assigned": assigned,
    }


@router.put("/activity/status")
async def set_manual_status(status: str, user_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    target_id = user_id or current_user["id"]
    allowed = {"available", "unavailable", "on_break", "site_visit", "away"}
    if status not in allowed:
        raise HTTPException(400, f"Status must be one of: {', '.join(sorted(allowed))}")
    now_dt = utc_now()
    now_iso = iso_utc_now()
    await db.user_activity.update_one(
        {"user_id": target_id},
        {"$set": {"manual_status": status, "updated_at": now_iso, "updated_at_dt": now_dt}},
        upsert=True,
    )
    return {"message": f"Status set to {status}"}


@router.get("/activity/team-status")
async def get_team_status(current_user: dict = Depends(get_current_user)):
    activities = await db.user_activity.find({}, {"_id": 0}).to_list(50)
    now = utc_now()

    agents = await db.leads.distinct("presales_agent")
    agents = [a for a in agents if a and a.strip()]
    blocked = await get_blocked_assignee_values()

    result = []
    activity_map = {a["full_name"]: a for a in activities}

    for agent in agents:
        if is_blocked_assignee_name(agent, blocked):
            continue
        activity = activity_map.get(agent, {})
        manual = activity.get("manual_status")

        if manual in {"unavailable", "on_break", "site_visit", "away"}:
            status_val = "offline"
        elif manual == "available":
            status_val = "online"
        else:
            last_active = activity.get("last_active")
            last_active_dt = activity.get("last_active_dt")
            last_dt = coerce_datetime(last_active_dt) or coerce_datetime(last_active)
            if not last_dt:
                status_val = "offline"
            else:
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                minutes_ago = (now - last_dt).total_seconds() / 60
                if minutes_ago <= 30:
                    status_val = "online"
                elif minutes_ago <= 60:
                    status_val = "idle"
                else:
                    status_val = "offline"

        active_count = await db.leads.count_documents(
            {"assigned_to": agent, "lead_status": {"$nin": ["Advance Paid", "Closed", "Booked", "Dropped", "Unqualified"]}}
        )

        result.append(
            {
                "name": agent,
                "status": status_val,
                "manual_status": activity.get("manual_status"),
                "last_active": activity.get("last_active", ""),
                "active_leads": active_count,
            }
        )

    return result

