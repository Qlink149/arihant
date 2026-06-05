import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from crm.services.dashboard_scope import resolve_lead_or_403, resolve_leads_base_filter
from crm.core.platform_ops import assert_assignee_allowed, is_platform_operator
from crm.core.state import db, get_current_user, utc_now, iso_utc_now, resolve_user_id_by_full_name
from crm.services.lead_events import log_lead_event
from crm.services.task_enrichment import enrich_tasks


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


TASK_OUTCOMES = {
    "Interested",
    "Not Interested",
    "Follow-up Scheduled",
    "Call back / Reschedule",
    "Others",
}


class TaskUpdatePatch(BaseModel):
    description: Optional[str] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    priority: Optional[str] = None
    reminder_method: Optional[str] = None
    assigned_to: Optional[str] = None
    assigned_user_id: Optional[str] = None
    status: Optional[str] = None
    task_outcome: Optional[str] = None
    task_outcome_reason: Optional[str] = None


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
    lead = await resolve_lead_or_403(lead_id, current_user)

    # Nurturing workflow rule: after transitioning into Nurturing, user must create a fresh task
    # before adding a new general note. Other update types remain allowed.
    if update.update_type == "general_note":
        status = (lead.get("lead_status") or "").strip().lower()
        if status == "nurturing":
            required_since = lead.get("nurture_task_required_since_dt")
            required_task_id = lead.get("nurture_task_required_task_id")
            if required_since and not required_task_id:
                raise HTTPException(
                    status_code=409,
                    detail="Create a follow-up task first after moving lead to Nurturing.",
                )

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

    await db.leads.update_one(
        {"id": lead_id},
        {"$push": {"context_updates": context_entry}, "$set": {"updated_at": now_iso, "updated_at_dt": now_dt}},
    )

    await log_lead_event(
        "note_added",
        lead_id=lead_id,
        actor_user_id=current_user.get("id"),
        actor_name=current_user.get("full_name"),
        payload={"update_type": update.update_type},
    )

    return {"message": "Context updated", "context_entry": context_entry}


@router.post("/leads/{lead_id}/tasks")
async def add_task(lead_id: str, task: TaskCreate, current_user: dict = Depends(get_current_user)):
    lead = await resolve_lead_or_403(lead_id, current_user)

    task_id = str(uuid.uuid4())
    assigned = task.assigned_to or lead.get("assigned_to") or lead.get("presales_agent") or current_user["full_name"]
    await assert_assignee_allowed(assigned)
    assigned_user_id = task.assigned_user_id or await resolve_user_id_by_full_name(assigned)
    if not assigned_user_id:
        raise HTTPException(status_code=400, detail="assigned_user_id is required (no matching user for assigned_to)")
    created_by_user_id = current_user.get("id")
    now_dt = utc_now()
    now_iso = iso_utc_now()

    lead_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
    task_doc = {
        "id": task_id,
        "lead_id": lead_id,
        "lead_name": lead_name,
        "project": (lead.get("project") or "").strip(),
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

    # If lead is in the post-nurturing task-required state, satisfy it atomically with this new task.
    await db.leads.update_one(
        {
            "id": lead_id,
            "lead_status": "Nurturing",
            "nurture_task_required_since_dt": {"$ne": None},
            "$or": [
                {"nurture_task_required_task_id": {"$exists": False}},
                {"nurture_task_required_task_id": None},
                {"nurture_task_required_task_id": ""},
            ],
        },
        {"$set": {"nurture_task_required_task_id": task_id}},
    )

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
    project = ""

    if task.lead_id:
        lead = await db.leads.find_one({"id": task.lead_id}, {"_id": 0})
        if lead:
            lead_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
            project = (lead.get("project") or "").strip()

    task_doc = {
        "id": task_id,
        "lead_id": task.lead_id or "",
        "lead_name": lead_name,
        "project": project,
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

    if task.lead_id:
        due_str = task.due_date
        if task.due_time:
            due_str += f" at {task.due_time}"
        context_entry = {
            "type": "task",
            "timestamp": now_iso,
            "timestamp_dt": now_dt,
            "description": f"Task: {task.description} | Due: {due_str} | Priority: {task.priority}",
            "agent": current_user["full_name"],
            "task_id": task_id,
            "actor_user_id": current_user.get("id"),
            "actor_name": current_user.get("full_name"),
        }
        await db.leads.update_one(
            {"id": task.lead_id},
            {"$push": {"context_updates": context_entry}, "$set": {"updated_at": now_iso, "updated_at_dt": now_dt}},
        )

    await log_lead_event(
        "task_created",
        lead_id=task.lead_id or None,
        actor_user_id=current_user.get("id"),
        actor_name=current_user.get("full_name"),
        payload={"task_id": task_id},
    )
    return {"message": "Task created", "task_id": task_id}


def _task_scope_for_user(current_user: dict, is_manager: bool) -> dict:
    uid = current_user["id"]
    name = current_user["full_name"]
    if is_manager or is_platform_operator(current_user):
        return {}
    return {
        "$or": [
            {"assigned_user_id": uid},
            {"assigned_to": name},
            {"assigned_to_name": name},
        ],
    }


@router.get("/tasks")
async def get_tasks(
    current_user: dict = Depends(get_current_user),
    status: Optional[str] = None,
    lead_id: Optional[str] = None,
    mine: bool = False,
):
    uid = current_user["id"]
    name = current_user["full_name"]
    _, is_manager = await resolve_leads_base_filter(uid, name, current_user)

    query: dict = _task_scope_for_user(current_user, False if mine else is_manager)
    if status:
        query = {"$and": [query, {"status": status}]} if query else {"status": status}
    if lead_id:
        lead_clause = {"lead_id": lead_id}
        query = {"$and": [query, lead_clause]} if query else lead_clause
    tasks = await db.tasks.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return await enrich_tasks(tasks)


@router.put("/tasks/{task_id}")
async def update_task(task_id: str, update: TaskUpdatePatch, current_user: dict = Depends(get_current_user)):
    task = await db.tasks.find_one({"id": task_id}, {"_id": 0})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    patch = update.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "assigned_to" in patch:
        await assert_assignee_allowed(patch["assigned_to"])

    if "status" in patch and patch["status"] not in {"pending", "done", "completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Invalid status")

    now_dt = utc_now()
    now_iso = iso_utc_now()
    patch["updated_at"] = now_iso
    patch["updated_at_dt"] = now_dt

    terminal = {"done", "completed", "cancelled"}
    completing = "status" in patch and patch["status"] in terminal
    if completing:
        if patch["status"] == "done":
            patch["status"] = "completed"
        patch["completed_at"] = now_iso
        patch["completed_at_dt"] = now_dt

    visit_sla_task = (task.get("sla_rule") or "") == "visit_completed" or (
        task.get("source") == "sla" and "post-visit" in (task.get("description") or "").lower()
    )
    if completing and patch.get("status") == "completed" and visit_sla_task:
        outcome = (patch.get("task_outcome") or task.get("task_outcome") or "").strip()
        if outcome not in TASK_OUTCOMES:
            raise HTTPException(
                status_code=400,
                detail="task_outcome is required when completing a post-visit SLA task",
            )
        if outcome == "Others" and not (patch.get("task_outcome_reason") or task.get("task_outcome_reason") or "").strip():
            raise HTTPException(status_code=400, detail="task_outcome_reason is required when outcome is Others")

    await db.tasks.update_one({"id": task_id}, {"$set": patch})

    new_status = patch.get("status")
    if new_status == "completed" and task.get("lead_id"):
        context_entry = {
            "type": "task_completed",
            "timestamp": now_iso,
            "timestamp_dt": now_dt,
            "description": f"Task completed: {task.get('description', '')[:200]}",
            "agent": current_user["full_name"],
            "task_id": task_id,
            "actor_user_id": current_user.get("id"),
            "actor_name": current_user.get("full_name"),
        }
        lead_set = {"updated_at": now_iso, "updated_at_dt": now_dt}
        if visit_sla_task and patch.get("status") == "completed":
            outcome = (patch.get("task_outcome") or "").strip()
            lead_set["visit_sla_reference_dt"] = now_dt
            await db.tasks.update_many(
                {
                    "lead_id": task["lead_id"],
                    "source": "sla",
                    "status": "pending",
                    "sla_rule": "visit_completed",
                },
                {"$set": {"status": "cancelled", "updated_at": now_iso, "updated_at_dt": now_dt}},
            )
            if outcome == "Call back / Reschedule":
                lead_set["visit_sla_reference_dt"] = now_dt
        await db.leads.update_one(
            {"id": task["lead_id"]},
            {"$push": {"context_updates": context_entry}, "$set": lead_set},
        )

    if new_status:
        await log_lead_event(
            "task_updated",
            lead_id=task.get("lead_id") or None,
            actor_user_id=current_user.get("id"),
            actor_name=current_user.get("full_name"),
            payload={"task_id": task_id, "status": new_status},
        )

    return {"message": "Task updated"}

