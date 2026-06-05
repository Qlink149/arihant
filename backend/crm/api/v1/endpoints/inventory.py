import uuid
from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from pymongo.errors import BulkWriteError

from crm.core.state import db, get_current_user, iso_utc_now, logger, utc_now
from crm.services.inventory_match_service import find_matching_leads, list_leads_missing_preferences
from crm.services.notification_service import create_notification
from crm.services.notifications_stream import notifications_stream


router = APIRouter()


class InventoryLaunch(BaseModel):
    project: Optional[str] = None
    location: Optional[str] = None
    configuration: Optional[str] = None  # e.g. "2 BHK"
    budget: Optional[str] = None
    title: str


@router.post("/inventory/launch")
async def inventory_launch(item: InventoryLaunch, current_user: dict = Depends(get_current_user)):
    if not item.title.strip():
        raise HTTPException(status_code=400, detail="title is required")

    launch = item.model_dump()
    matches = await find_matching_leads(launch, status_regex=r"future\s*prospect|nurtur|new|contacted")

    now_dt = utc_now()
    now_iso = iso_utc_now()
    notifications = []
    tasks = []

    for match in matches:
        lead = match["lead"]
        warnings = match.get("warnings") or []
        uid = lead.get("assigned_user_id")
        if not uid:
            continue
        lead_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        warn_suffix = " (incomplete preferences)" if "preferences_incomplete" in warnings else ""
        loc_warn = " — city-level match" if "location_missing" in warnings else ""

        notif_id = str(uuid.uuid4())
        notif = {
            "id": notif_id,
            "type": "inventory_match",
            "notification_type": "action_required",
            "title": "Matching inventory launched",
            "message": f"{item.title} matches {lead_name}{warn_suffix}{loc_warn}",
            "lead_id": lead["id"],
            "lead_name": lead_name,
            "severity": "medium",
            "urgency": "info",
            "assigned_to": lead.get("assigned_to") or "",
            "recipient_name": lead.get("assigned_to") or "",
            "recipient_user_id": uid,
            "is_read": False,
            "fired_at_dt": now_dt,
            "created_at": now_iso,
            "created_at_dt": now_dt,
            "dedupe_key": f"inventory:{lead['id']}:{item.title}".lower(),
        }
        notifications.append(notif)

        task = {
            "id": str(uuid.uuid4()),
            "lead_id": lead["id"],
            "lead_name": lead_name,
            "project": (item.project or "").strip(),
            "description": f"Inventory match: {item.title}",
            "due_date": now_dt.astimezone(timezone.utc).strftime("%Y-%m-%d"),
            "due_time": "09:00",
            "due_at_dt": now_dt.replace(tzinfo=timezone.utc),
            "priority": "medium",
            "reminder_method": "email",
            "assigned_to": lead.get("assigned_to") or "",
            "assigned_to_name": lead.get("assigned_to") or "",
            "assigned_user_id": uid,
            "status": "pending",
            "created_by": current_user.get("full_name") or "System",
            "created_by_user_id": current_user.get("id"),
            "created_at": now_iso,
            "created_at_dt": now_dt,
            "dedupe_key": f"inventory_task:{lead['id']}:{item.title}".lower(),
            "source": "inventory",
        }
        tasks.append(task)

    notif_result = {"inserted": 0, "failed": 0, "errors": []}
    if notifications:
        notif_result = await _bulk_insert("notifications", notifications)

    task_result = {"inserted": 0, "failed": 0, "errors": []}
    if tasks:
        task_result = await _bulk_insert("tasks", tasks)

    for n in notifications:
        try:
            await notifications_stream.publish(n["recipient_user_id"], n)
        except Exception:
            pass

    return {
        "ok": True,
        "matched_leads": len(matches),
        "notifications": notif_result["inserted"],
        "tasks": task_result["inserted"],
        "insert_errors": {
            "notifications": notif_result,
            "tasks": task_result,
        },
    }


async def _bulk_insert(collection: str, items: list) -> dict:
    coll = getattr(db, collection)
    try:
        result = await coll.insert_many(items, ordered=False)
        return {"inserted": len(result.inserted_ids), "failed": 0, "errors": []}
    except BulkWriteError as e:
        inserted_count = e.details.get("nInserted", 0)
        failed_count = len(items) - inserted_count
        errors = e.details.get("writeErrors", [])
        logger.error(
            "Inventory bulk insert partial failure on %s: %s errors",
            collection,
            len(errors),
        )
        return {
            "inserted": inserted_count,
            "failed": failed_count,
            "errors": [{"index": err["index"], "message": err["errmsg"]} for err in errors[:10]],
        }


@router.get("/leads/missing-preferences")
async def leads_missing_preferences(
    current_user: dict = Depends(get_current_user),
    limit: int = 100,
):
    return await list_leads_missing_preferences(limit=limit)

