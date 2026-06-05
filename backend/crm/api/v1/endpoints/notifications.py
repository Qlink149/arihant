from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from starlette.responses import StreamingResponse
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException

from crm.services.dashboard_scope import resolve_leads_base_filter
from crm.core.platform_ops import is_platform_operator
from crm.core.state import db, get_current_user, utc_now, iso_utc_now
from crm.services.notification_service import enrich_notification
from crm.services.notifications_stream import notifications_stream


router = APIRouter()

_MAX_DISMISSALS = 4000


class NotificationPreferences(BaseModel):
    notification_sound_enabled: bool = True


def _parse_lead_ts(val: Any, fallback: datetime) -> datetime:
    """Always return a timezone-aware UTC datetime to avoid naive vs aware comparison errors."""
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return fallback
    return fallback


def _recipient_filter(uid: str, name: str) -> Dict[str, Any]:
    return {
        "$or": [
            {"recipient_user_id": uid},
            {"assigned_to": name},
            {"recipient_name": name},
        ],
    }


async def _build_auto_notifications(current_user: dict) -> List[Dict[str, Any]]:
    auto_notifications: List[Dict[str, Any]] = []
    now_dt = utc_now()
    now_iso = iso_utc_now()

    rnr_cutoff = (now_dt - timedelta(hours=24)).isoformat()
    rnr_leads = await db.leads.find(
        {
            "$and": [
                {"updated_at": {"$lt": rnr_cutoff}},
                {
                    "$or": [
                        {"lead_status": {"$regex": "rnr", "$options": "i"}},
                        {"is_rnr": True},
                    ]
                },
            ]
        },
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "updated_at": 1, "assigned_to": 1},
    ).to_list(50)
    for lead in rnr_leads:
        updated_dt = _parse_lead_ts(lead.get("updated_at"), now_dt)
        hours_ago = int((now_dt - updated_dt).total_seconds() / 3600)
        auto_notifications.append(
            {
                "id": f"auto-rnr-{lead['id']}",
                "type": "rnr_followup",
                "title": "RNR Follow-up Needed",
                "message": f"{lead.get('first_name', '')} {lead.get('last_name', '')} hasn't been followed up — last attempt was {hours_ago}h ago",
                "lead_id": lead["id"],
                "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}",
                "severity": "high",
                "urgency": "urgent",
                "is_read": False,
                "is_auto": True,
                "created_at": now_iso,
                "created_at_dt": now_dt,
            }
        )

    dormant_cutoff = (now_dt - timedelta(days=7)).isoformat()
    dormant_leads = (
        await db.leads.find(
            {
                "updated_at": {"$lt": dormant_cutoff},
                "lead_status": {"$nin": ["Advance Paid", "Closed", "Booked", "Dropped", "Unqualified", "Won", "Lost"]},
            },
            {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "updated_at": 1},
        )
        .limit(30)
        .to_list(30)
    )
    for lead in dormant_leads:
        updated_dt = _parse_lead_ts(lead.get("updated_at"), now_dt)
        days_ago = int((now_dt - updated_dt).total_seconds() / 86400)
        auto_notifications.append(
            {
                "id": f"auto-dormant-{lead['id']}",
                "type": "dormant_lead",
                "title": "Dormant Lead",
                "message": f"{lead.get('first_name', '')} {lead.get('last_name', '')} has gone dormant — no activity for {days_ago} days",
                "lead_id": lead["id"],
                "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}",
                "severity": "medium",
                "urgency": "action_needed",
                "is_read": False,
                "is_auto": True,
                "created_at": now_iso,
                "created_at_dt": now_dt,
            }
        )

    uid = current_user["id"]
    name = current_user["full_name"]
    _, is_manager = await resolve_leads_base_filter(uid, name, current_user)
    overdue_query: Dict[str, Any] = {"status": "pending", "due_date": {"$lt": now_dt.strftime("%Y-%m-%d")}}
    if not is_manager and not is_platform_operator(current_user):
        overdue_query = {
            "$and": [
                overdue_query,
                {
                    "$or": [
                        {"assigned_user_id": uid},
                        {"assigned_to": name},
                        {"assigned_to_name": name},
                    ],
                },
            ]
        }
    overdue_tasks = await db.tasks.find(overdue_query, {"_id": 0}).to_list(50)
    for task in overdue_tasks:
        auto_notifications.append(
            {
                "id": f"auto-task-{task['id']}",
                "type": "task_overdue",
                "title": "Overdue Task",
                "message": f"Task '{task['description'][:50]}' was due on {task['due_date']}",
                "lead_id": task.get("lead_id", ""),
                "lead_name": task.get("description", "")[:30],
                "task_id": task["id"],
                "severity": "high",
                "urgency": "urgent",
                "is_read": False,
                "is_auto": True,
                "created_at": now_iso,
                "created_at_dt": now_dt,
            }
        )

    return auto_notifications


@router.get("/notifications")
async def get_notifications(
    current_user: dict = Depends(get_current_user),
    unread_only: bool = True,
):
    uid = current_user["id"]
    name = current_user["full_name"]
    recipient = _recipient_filter(uid, name)
    query: Dict[str, Any] = dict(recipient)
    if unread_only:
        query = {"$and": [recipient, {"is_read": False}]}

    now_dt = utc_now()
    stored = await db.notifications.find(query, {"_id": 0}).sort("fired_at_dt", -1).to_list(200)
    stored = [enrich_notification(n, now_dt) for n in stored]

    dismissed = set(current_user.get("notification_dismissals") or [])
    auto_notifications = [n for n in await _build_auto_notifications(current_user) if n.get("id") not in dismissed]
    for n in auto_notifications:
        n["is_overdue"] = False

    all_notifications = stored + auto_notifications

    def _sort_key(n: dict):
        """Return a timezone-aware datetime for sorting; normalize naive datetimes from MongoDB."""
        val = n.get("fired_at_dt") or n.get("created_at_dt") or n.get("created_at") or ""
        if isinstance(val, datetime):
            if val.tzinfo is None:
                val = val.replace(tzinfo=timezone.utc)
            return val
        # ISO string fallback — convert so datetimes and strings aren't mixed
        if isinstance(val, str) and val:
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
            except ValueError:
                pass
        return datetime.min.replace(tzinfo=timezone.utc)

    all_notifications.sort(key=_sort_key, reverse=True)
    return all_notifications[:100]


@router.get("/notifications/preferences")
async def get_notification_preferences(current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    uid = current_user["id"]
    user = await db.users.find_one({"id": uid}, {"_id": 0, "notification_sound_enabled": 1}) or {}
    return {"notification_sound_enabled": bool(user.get("notification_sound_enabled", True))}


@router.put("/notifications/preferences")
async def update_notification_preferences(
    body: NotificationPreferences, current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    uid = current_user["id"]
    await db.users.update_one({"id": uid}, {"$set": {"notification_sound_enabled": body.notification_sound_enabled}})
    return {"notification_sound_enabled": body.notification_sound_enabled}


@router.get("/notifications/stream")
async def notifications_sse(current_user: dict = Depends(get_current_user)):
    """Server-Sent Events stream of stored notification documents as they are created."""
    uid = current_user["id"]

    async def gen():
        async for chunk in notifications_stream.stream(uid):
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.put("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, current_user: dict = Depends(get_current_user)):
    if notification_id.startswith("auto-"):
        uid = current_user["id"]
        user = await db.users.find_one({"id": uid}, {"_id": 0, "notification_dismissals": 1}) or {}
        cur = list(user.get("notification_dismissals") or [])
        if notification_id not in cur:
            cur.append(notification_id)
            cur = cur[-_MAX_DISMISSALS:]
            await db.users.update_one({"id": uid}, {"$set": {"notification_dismissals": cur}})
        return {"message": "Notification marked as read"}
    uid = current_user["id"]
    name = current_user["full_name"]
    result = await db.notifications.update_one(
        {"id": notification_id, **_recipient_filter(uid, name)},
        {"$set": {"is_read": True}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"message": "Notification marked as read"}


@router.put("/notifications/read-all")
async def mark_all_notifications_read(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    name = current_user["full_name"]
    recipient = _recipient_filter(uid, name)
    auto_ids = [n["id"] for n in await _build_auto_notifications(current_user)]
    user = await db.users.find_one({"id": uid}, {"_id": 0, "notification_dismissals": 1}) or {}
    merged = list(dict.fromkeys((user.get("notification_dismissals") or []) + auto_ids))[-_MAX_DISMISSALS:]
    await db.users.update_one({"id": uid}, {"$set": {"notification_dismissals": merged}})
    await db.notifications.update_many({**recipient, "is_read": False}, {"$set": {"is_read": True}})
    return {"message": "All notifications marked as read"}
