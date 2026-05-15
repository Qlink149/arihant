import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from crm.core.state import db, get_current_user, utc_now, iso_utc_now, resolve_user_id_by_full_name


router = APIRouter()


class ContextUpdateCreate(BaseModel):
    note: str
    update_type: str = "general_note"


class TaskCreate(BaseModel):
    description: str
    due_date: str
    due_time: Optional[str] = None
    priority: str = "medium"
    reminder_method: str = "email"
    assigned_to: Optional[str] = None
    assigned_user_id: Optional[str] = None


class TaskUpdatePatch(BaseModel):
    description: Optional[str] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    priority: Optional[str] = None
    reminder_method: Optional[str] = None
    assigned_to: Optional[str] = None
    assigned_user_id: Optional[str] = None
    status: Optional[str] = None


class StandaloneTaskCreate(BaseModel):
    description: str
    due_date: str
    due_time: Optional[str] = None
    priority: str = "medium"
    lead_id: Optional[str] = None
    lead_name: Optional[str] = None
    assigned_user_id: Optional[str] = None


@router.post("/leads/{lead_id}/context")
async def add_context_update(lead_id: str, update: ContextUpdateCreate, current_user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    type_labels = {
        "call_note": "call",
        "site_visit_note": "site_visit",
        "whatsapp_update": "whatsapp",
        "email_update": "email",
        "meeting_note": "meeting",
        "general_note": "note",
    }

    now_dt = utc_now()
    now_iso = iso_utc_now()
    context_entry = {
        "type": type_labels.get(update.update_type, "note"),
        "timestamp": now_iso,
        "timestamp_dt": now_dt,
        "description": update.note,
        "agent": current_user["full_name"],
        "update_type": update.update_type,
        "actor_user_id": current_user.get("id"),
        "actor_name": current_user.get("full_name"),
    }

    existing_updates = lead.get("context_updates", [])
    existing_updates.append(context_entry)

    merged = {**lead, "context_updates": existing_updates, "presales_description": update.note}

    await db.leads.update_one(
        {"id": lead_id},
        {"$push": {"context_updates": context_entry}, "$set": {"updated_at": now_iso, "updated_at_dt": now_dt}},
    )

    return {"message": "Context updated", "context_entry": context_entry}


@router.post("/leads/{lead_id}/tasks")
async def add_task(lead_id: str, task: TaskCreate, current_user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    task_id = str(uuid.uuid4())
    assigned = task.assigned_to or lead.get("assigned_to") or lead.get("presales_agent") or current_user["full_name"]
    assigned_user_id = task.assigned_user_id or await resolve_user_id_by_full_name(assigned)
    if not assigned_user_id:
        raise HTTPException(status_code=400, detail="assigned_user_id is required (no matching user for assigned_to)")
    created_by_user_id = current_user.get("id")
    now_dt = utc_now()
    now_iso = iso_utc_now()

    task_doc = {
        "id": task_id,
        "lead_id": lead_id,
        "description": task.description,
        "due_date": task.due_date,
        "due_time": task.due_time,
        "due_at_dt": datetime.fromisoformat(f"{task.due_date}T{task.due_time or '09:00'}:00").replace(tzinfo=timezone.utc),
        "priority": task.priority,
        "reminder_method": task.reminder_method,
        "assigned_to": assigned,
        "assigned_to_name": assigned,
        "assigned_user_id": assigned_user_id,
        "status": "pending",
        "created_by": current_user["full_name"],
        "created_by_user_id": created_by_user_id,
        "created_at": now_iso,
        "created_at_dt": now_dt,
    }
    await db.tasks.insert_one(task_doc)

    due_str = task.due_date
    if task.due_time:
        due_str += f" at {task.due_time}"

    context_entry = {
        "type": "task",
        "timestamp": now_iso,
        "timestamp_dt": now_dt,
        "description": f"Task: {task.description} | Due: {due_str} | Priority: {task.priority} | Assigned to: {assigned}",
        "agent": current_user["full_name"],
        "task_id": task_id,
        "actor_user_id": current_user.get("id"),
        "actor_name": current_user.get("full_name"),
    }

    await db.leads.update_one({"id": lead_id}, {"$push": {"context_updates": context_entry}, "$set": {"updated_at": now_iso, "updated_at_dt": now_dt}})

    notification_doc = {
        "id": str(uuid.uuid4()),
        "type": "task_reminder",
        "title": f"Task: {task.description[:50]}",
        "message": f"Due {due_str} for {lead.get('first_name', '')} {lead.get('last_name', '')}",
        "lead_id": lead_id,
        "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}",
        "task_id": task_id,
        "severity": "high" if task.priority == "high" else "medium" if task.priority == "medium" else "low",
        "urgency": "action_needed",
        "assigned_to": assigned,
        "recipient_name": assigned,
        "recipient_user_id": assigned_user_id,
        "is_read": False,
        "created_at": now_iso,
        "created_at_dt": now_dt,
        "due_at": f"{task.due_date}T{task.due_time or '09:00'}:00",
    }
    await db.notifications.insert_one(notification_doc)

    return {"message": "Task created", "task_id": task_id, "context_entry": context_entry}


@router.post("/tasks")
async def create_standalone_task(task: StandaloneTaskCreate, current_user: dict = Depends(get_current_user)):
    task_id = str(uuid.uuid4())
    assigned = current_user["full_name"]
    assigned_user_id = task.assigned_user_id or current_user.get("id")
    if not assigned_user_id:
        raise HTTPException(status_code=400, detail="assigned_user_id is required")
    now_dt = utc_now()
    now_iso = iso_utc_now()
    lead_name = task.lead_name or ""

    if task.lead_id:
        lead = await db.leads.find_one({"id": task.lead_id}, {"_id": 0})
        if lead:
            lead_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()

    task_doc = {
        "id": task_id,
        "lead_id": task.lead_id or "",
        "lead_name": lead_name,
        "description": task.description,
        "due_date": task.due_date,
        "due_time": task.due_time,
        "due_at_dt": datetime.fromisoformat(f"{task.due_date}T{task.due_time or '09:00'}:00").replace(tzinfo=timezone.utc),
        "priority": task.priority,
        "reminder_method": "email",
        "assigned_to": assigned,
        "assigned_to_name": assigned,
        "assigned_user_id": assigned_user_id,
        "status": "pending",
        "created_by": current_user["full_name"],
        "created_by_user_id": current_user.get("id"),
        "created_at": now_iso,
        "created_at_dt": now_dt,
    }
    await db.tasks.insert_one(task_doc)
    return {"message": "Task created", "task_id": task_id}


@router.get("/tasks")
async def get_tasks(current_user: dict = Depends(get_current_user), status: Optional[str] = None, lead_id: Optional[str] = None):
    query = {}
    if status:
        query["status"] = status
    if lead_id:
        query["lead_id"] = lead_id
    tasks = await db.tasks.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return tasks


@router.put("/tasks/{task_id}")
async def update_task(task_id: str, update: TaskUpdatePatch, current_user: dict = Depends(get_current_user)):
    task = await db.tasks.find_one({"id": task_id}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    patch = update.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "status" in patch and patch["status"] not in {"pending", "done", "completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Invalid status")

    now_dt = utc_now()
    now_iso = iso_utc_now()
    patch["updated_at"] = now_iso
    patch["updated_at_dt"] = now_dt
    await db.tasks.update_one({"id": task_id}, {"$set": patch})
    return {"message": "Task updated"}

