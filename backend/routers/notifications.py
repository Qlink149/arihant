from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from backend.app_state import db, get_current_user, utc_now, iso_utc_now


router = APIRouter()

_MAX_DISMISSALS = 4000


def _parse_lead_ts(val: Any, fallback: datetime) -> datetime:
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    return fallback


async def _build_auto_notifications() -> List[Dict[str, Any]]:
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

    overdue_tasks = await db.tasks.find({"status": "pending", "due_date": {"$lt": now_dt.strftime("%Y-%m-%d")}}, {"_id": 0}).to_list(50)
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
async def get_notifications(current_user: dict = Depends(get_current_user), unread_only: bool = False):
    query: Dict[str, Any] = {}
    if unread_only:
        query["is_read"] = False

    stored = await db.notifications.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)

    dismissed = set(current_user.get("notification_dismissals") or [])
    auto_notifications = [n for n in await _build_auto_notifications() if n.get("id") not in dismissed]

    all_notifications = stored + auto_notifications
    all_notifications.sort(key=lambda n: n.get("created_at", ""), reverse=True)
    return all_notifications[:100]


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
    await db.notifications.update_one({"id": notification_id}, {"$set": {"is_read": True}})
    return {"message": "Notification marked as read"}


@router.put("/notifications/read-all")
async def mark_all_notifications_read(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    auto_ids = [n["id"] for n in await _build_auto_notifications()]
    user = await db.users.find_one({"id": uid}, {"_id": 0, "notification_dismissals": 1}) or {}
    merged = list(dict.fromkeys((user.get("notification_dismissals") or []) + auto_ids))[-_MAX_DISMISSALS:]
    await db.users.update_one({"id": uid}, {"$set": {"notification_dismissals": merged}})
    await db.notifications.update_many({"is_read": False}, {"$set": {"is_read": True}})
    return {"message": "All notifications marked as read"}
