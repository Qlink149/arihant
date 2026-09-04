import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from crm.services.dashboard_scope import resolve_lead_or_403, resolve_lead_view_or_403, resolve_leads_base_filter
from crm.core.platform_ops import assert_assignee_allowed, is_platform_operator
from crm.core.state import db, get_current_user, utc_now, iso_utc_now, resolve_user_id_by_full_name
from crm.services.lead_events import log_lead_event
from crm.services.notification_service import create_notification
from crm.services.note_notify import notify_note_recipients, resolve_mentioned_users
from crm.constants.task import TASK_REMINDER_METHOD_DEFAULT
from crm.services.lead_follow_up import recompute_lead_next_action_date
from crm.services.task_enrichment import enrich_tasks
from crm.utils.helpers import ist_wall_to_utc_dt


router = APIRouter()


class ContextUpdateCreate(BaseModel):
    note: str
    update_type: str = "general_note"
    mentioned_user_ids: Optional[List[str]] = Field(default=None)


class ContextUpdatePatch(BaseModel):
    note: str
    # Optional identity match when display index may not equal Mongo index
    timestamp: Optional[str] = None
    entry_type: Optional[str] = None
    previous_description: Optional[str] = None


class TaskCreate(BaseModel):
    description: str
    due_date: str
    due_time: Optional[str] = None
    priority: str = "medium"
    reminder_method: str = TASK_REMINDER_METHOD_DEFAULT
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
async def add_context_update(
    lead_id: str,
    update: ContextUpdateCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    # Org-wide notes (#39): any authenticated user can add general_note on any lead.
    # Other context types keep edit ACL (own / task / grant / admin|manager).
    if (update.update_type or "").strip() == "general_note":
        lead = await resolve_lead_view_or_403(lead_id, current_user)
    else:
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
    mentioned_users = await resolve_mentioned_users(
        mentioned_user_ids=update.mentioned_user_ids,
        note_text=update.note or "",
    )
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
    if mentioned_users:
        context_entry["mentioned_user_ids"] = [u["id"] for u in mentioned_users if u.get("id")]
        context_entry["mentioned_names"] = [
            (u.get("full_name") or "").strip() for u in mentioned_users if (u.get("full_name") or "").strip()
        ]

    await db.leads.update_one(
        {"id": lead_id},
        {
            "$push": {"context_updates": context_entry},
            "$set": {
                "updated_at": now_iso,
                "updated_at_dt": now_dt,
                "recent_note": update.note.strip(),
            },
        },
    )

    # Logging a follow-up note clears overdue Missed Follow-up debt for this lead.
    from crm.services.lead_follow_up import clear_missed_follow_up_after_activity
    from crm.services.lead_overview_service import ist_day_window

    today_str, _, _ = ist_day_window()
    await clear_missed_follow_up_after_activity(
        lead_id,
        today_str=today_str,
        actor_name=current_user.get("full_name") or "User",
    )

    await log_lead_event(
        "note_added",
        lead_id=lead_id,
        actor_user_id=current_user.get("id"),
        actor_name=current_user.get("full_name"),
        payload={"update_type": update.update_type},
    )

    await notify_note_recipients(
        lead=lead,
        author=current_user,
        note_text=update.note or "",
        mentioned_users=mentioned_users,
    )

    from crm.services.nudge_pending import clear_nudge_pending_if_assignee

    await clear_nudge_pending_if_assignee(lead_id, current_user, lead=lead)

    from crm.services.ai_lead_regen import schedule_lead_ai_refresh

    schedule_lead_ai_refresh(lead_id, background_tasks)

    return {"message": "Context updated", "context_entry": context_entry}


@router.patch("/leads/{lead_id}/context/{entry_index}")
async def patch_context_update(
    lead_id: str,
    entry_index: int,
    update: ContextUpdatePatch,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """Edit an existing timeline note/comment by Mongo array index (or identity match)."""
    await resolve_lead_or_403(lead_id, current_user)
    note = (update.note or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="Note cannot be empty")
    if entry_index < 0:
        raise HTTPException(status_code=400, detail="Invalid context entry index")

    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0, "context_updates": 1})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    updates = list(lead.get("context_updates") or [])

    resolved_index = entry_index
    # Prefer identity match when client sends timestamp/type (survives display reorder).
    match_ts = (update.timestamp or "").strip()
    match_type = (update.entry_type or "").strip().lower()
    match_prev = (update.previous_description or "").strip()
    if match_ts or match_type or match_prev:
        found = None
        for i, row in enumerate(updates):
            if not isinstance(row, dict):
                continue
            row_type = (row.get("type") or row.get("update_type") or "").strip().lower()
            if match_type and row_type != match_type and match_type not in row_type:
                continue
            row_ts = str(row.get("timestamp") or "").strip()
            row_ts_dt = row.get("timestamp_dt")
            ts_ok = True
            if match_ts:
                ts_ok = (
                    match_ts == row_ts
                    or (row_ts_dt is not None and match_ts[:19] in str(row_ts_dt))
                    or match_ts[:19] == row_ts[:19]
                )
            if not ts_ok:
                continue
            if match_prev and (row.get("description") or "").strip() != match_prev:
                continue
            found = i
            break
        if found is not None:
            resolved_index = found
        # else: keep URL entry_index (mongo index from _mongo_index) as fallback

    if resolved_index >= len(updates):
        raise HTTPException(status_code=404, detail="Context entry not found")

    entry = updates[resolved_index]
    if not isinstance(entry, dict):
        raise HTTPException(status_code=400, detail="Invalid context entry")

    editable_types = {"note", "call", "site_visit", "whatsapp", "email", "meeting", "general_note"}
    etype = (entry.get("type") or entry.get("update_type") or "").strip().lower()
    if etype and etype not in editable_types and "note" not in etype:
        raise HTTPException(status_code=400, detail="Only notes/comments can be edited")

    now_dt = utc_now()
    now_iso = iso_utc_now()
    entry = {
        **entry,
        "description": note,
        "edited_at": now_iso,
        "edited_at_dt": now_dt,
        "edited_by": current_user.get("full_name"),
        "edited_by_user_id": current_user.get("id"),
    }
    updates[resolved_index] = entry

    set_fields = {
        "context_updates": updates,
        "updated_at": now_iso,
        "updated_at_dt": now_dt,
    }
    # Keep stored recent_note in sync only when editing the newest timeline entry
    if resolved_index == len(updates) - 1:
        set_fields["recent_note"] = note

    await db.leads.update_one({"id": lead_id}, {"$set": set_fields})
    await log_lead_event(
        "note_edited",
        lead_id=lead_id,
        actor_user_id=current_user.get("id"),
        actor_name=current_user.get("full_name"),
        payload={"entry_index": resolved_index},
    )

    from crm.services.ai_lead_regen import schedule_lead_ai_refresh

    schedule_lead_ai_refresh(lead_id, background_tasks)
    return {
        "message": "Context entry updated",
        "context_entry": entry,
        "entry_index": resolved_index,
    }


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
        "due_at_dt": ist_wall_to_utc_dt(task.due_date, task.due_time or "09:00"),
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

    from crm.services.nudge_pending import clear_nudge_pending_if_assignee

    await clear_nudge_pending_if_assignee(lead_id, current_user, lead=lead)

    # Scheduling a new follow-up clears older overdue task debt from Missed Follow-up.
    from crm.services.lead_follow_up import complete_overdue_pending_tasks
    from crm.services.lead_overview_service import ist_day_window

    today_str, _, _ = ist_day_window()
    new_due = (task.due_date or "")[:10]
    if new_due and new_due >= today_str:
        await complete_overdue_pending_tasks(
            lead_id,
            today_str=today_str,
            actor_name=current_user.get("full_name") or "User",
        )
    await recompute_lead_next_action_date(lead_id)

    await create_notification(
        recipient_user_id=assigned_user_id,
        recipient_name=assigned,
        title=f"Task: {task.description[:50]}",
        message=f"Due {due_str} for {lead_name}",
        notification_type="task_reminder",
        lead_id=lead_id,
        lead_name=lead_name,
        task_id=task_id,
        severity="high" if task.priority == "high" else "medium" if task.priority == "medium" else "low",
        urgency="action_needed",
    )

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
        "due_at_dt": ist_wall_to_utc_dt(task.due_date, task.due_time or "09:00"),
        "priority": task.priority,
        "reminder_method": TASK_REMINDER_METHOD_DEFAULT,
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
        await recompute_lead_next_action_date(task.lead_id)

    await log_lead_event(
        "task_created",
        lead_id=task.lead_id or None,
        actor_user_id=current_user.get("id"),
        actor_name=current_user.get("full_name"),
        payload={"task_id": task_id},
    )

    due_str = task.due_date
    if task.due_time:
        due_str += f" at {task.due_time}"
    message = f"Due {due_str}"
    if lead_name:
        message += f" for {lead_name}"

    await create_notification(
        recipient_user_id=assigned_user_id,
        recipient_name=assigned,
        title=f"Task: {task.description[:50]}",
        message=message,
        notification_type="task_reminder",
        lead_id=task.lead_id or "",
        lead_name=lead_name,
        task_id=task_id,
        severity="high" if task.priority == "high" else "medium" if task.priority == "medium" else "low",
        urgency="action_needed",
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

    if "due_date" in patch or "due_time" in patch:
        next_date = patch.get("due_date", task.get("due_date"))
        next_time = patch.get("due_time", task.get("due_time")) or "09:00"
        if next_date:
            patch["due_at_dt"] = ist_wall_to_utc_dt(str(next_date)[:10], next_time)

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
    lead_id = task.get("lead_id") or ""

    # Completing/cancelling an RNR reminder cancels sibling open RNR reminders
    rnr_reminder = (
        task.get("source") == "sla"
        and (task.get("sla_rule") or "") == "rnr"
        and str(task.get("sla_threshold") or "").startswith("reminder_")
    )
    if completing and rnr_reminder and lead_id:
        await db.tasks.update_many(
            {
                "lead_id": lead_id,
                "source": "sla",
                "sla_rule": "rnr",
                "status": {"$in": ["pending", "in_progress"]},
                "sla_threshold": {"$regex": r"^reminder_"},
                "id": {"$ne": task_id},
            },
            {"$set": {"status": "cancelled", "updated_at": now_iso, "updated_at_dt": now_dt}},
        )

    if new_status == "completed" and lead_id:
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
        from crm.services.nudge_pending import clear_nudge_pending_if_assignee

        await clear_nudge_pending_if_assignee(lead_id, current_user)

    if lead_id and (
        completing
        or "due_date" in patch
        or patch.get("status") == "pending"
    ):
        if completing:
            from crm.services.lead_follow_up import clear_missed_follow_up_after_activity
            from crm.services.lead_overview_service import ist_day_window

            today_str, _, _ = ist_day_window()
            await clear_missed_follow_up_after_activity(
                lead_id,
                today_str=today_str,
                actor_name=current_user.get("full_name") or "User",
            )
        else:
            await recompute_lead_next_action_date(lead_id)

    if new_status:
        await log_lead_event(
            "task_updated",
            lead_id=lead_id or None,
            actor_user_id=current_user.get("id"),
            actor_name=current_user.get("full_name"),
            payload={"task_id": task_id, "status": new_status},
        )

    return {"message": "Task updated"}

