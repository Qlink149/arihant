import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import List
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from crm.core.state import (
    db,
    logger,
    get_current_user,
    GUPSHUP_API_KEY,
    GUPSHUP_BASE_URL,
    GUPSHUP_SOURCE_PHONE,
    utc_now,
    iso_utc_now,
    resolve_user_id_by_full_name,
)
from crm.services.notification_service import create_notification
from crm.services.reminder_queries import (
    rnr_status_clause,
    site_visit_tomorrow_clause,
    sla_paused_exclusion,
    stale_updated_clause,
    status_clause,
)
from crm.utils.helpers import coerce_datetime


router = APIRouter()


REMINDER_TEMPLATES = {
    "followup": "clara_reminder_1",
    "task_due": "clara_task_reminder",
}


class ReminderRule(BaseModel):
    name: str
    trigger: str
    days_threshold: int = 0
    is_active: bool = True
    send_whatsapp: bool = True
    lead_statuses: List[str] = []


class ManualReminderRequest(BaseModel):
    lead_id: str
    message: str
    send_whatsapp: bool = False


async def _emit_reminder_notification(
    *,
    rep_user_id: str | None,
    rep_name: str,
    title: str,
    message: str,
    lead_id: str,
    dedupe_key: str,
    urgency: str = "action_needed",
    lead_name: str = "",
    task_id: str | None = None,
):
    if not rep_user_id:
        return None
    return await create_notification(
        recipient_user_id=rep_user_id,
        recipient_name=rep_name,
        title=title,
        message=message,
        notification_type="reminder",
        lead_id=lead_id,
        lead_name=lead_name,
        task_id=task_id,
        urgency=urgency,
        dedupe_key=dedupe_key,
    )


async def send_whatsapp_template(destination: str, template_name: str, params: List[str]):
    try:
        destination = re.sub(r"[^0-9]", "", destination)
        if len(destination) == 10:
            destination = "91" + destination

        template_data = {"id": template_name, "params": params}
        data = {"source": GUPSHUP_SOURCE_PHONE, "destination": destination, "template": json.dumps(template_data)}

        async with httpx.AsyncClient() as client_http:
            resp = await client_http.post(
                f"{GUPSHUP_BASE_URL}/wa/api/v1/template/msg",
                headers={"apikey": GUPSHUP_API_KEY, "Content-Type": "application/x-www-form-urlencoded"},
                data=data,
                timeout=30.0,
            )
            result = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text}
            logger.info(f"WhatsApp template sent to {destination}: {result}")
            return result
    except Exception as e:
        logger.error(f"Failed to send WhatsApp template to {destination}: {e}")
        return None


async def seed_default_reminder_rules():
    rules = [
        {"id": str(uuid.uuid4()), "name": "Follow-up Due (2 days)", "trigger": "followup_due", "days_threshold": 2, "is_active": True, "send_whatsapp": True, "lead_statuses": ["Follow Up 1", "Follow Up 2"]},
        {"id": str(uuid.uuid4()), "name": "Site Visit Tomorrow", "trigger": "site_visit_tomorrow", "days_threshold": 0, "is_active": True, "send_whatsapp": True, "lead_statuses": ["Site Visit Scheduled"]},
        {"id": str(uuid.uuid4()), "name": "RNR Stale (3 days)", "trigger": "rnr_stale", "days_threshold": 3, "is_active": True, "send_whatsapp": False, "lead_statuses": ["RNR"]},
        {"id": str(uuid.uuid4()), "name": "Task Overdue", "trigger": "task_overdue", "days_threshold": 0, "is_active": True, "send_whatsapp": True, "lead_statuses": []},
        {"id": str(uuid.uuid4()), "name": "Cold Lead Reactivation (7 days)", "trigger": "followup_due", "days_threshold": 7, "is_active": True, "send_whatsapp": False, "lead_statuses": ["Gone Cold"]},
    ]
    for rule in rules:
        rule["created_at"] = iso_utc_now()
        rule["created_at_dt"] = utc_now()
        await db.reminder_rules.insert_one(rule)
    logger.info("Seeded 5 default reminder rules")
    return rules


async def process_reminders():
    try:
        now_dt = utc_now()
        now_iso = iso_utc_now()
        today = now_dt.strftime("%Y-%m-%d")

        rules = await db.reminder_rules.find({"is_active": True}, {"_id": 0}).to_list(50)
        if not rules:
            rules = await seed_default_reminder_rules()

        users = await db.users.find({}, {"_id": 0, "email": 1, "full_name": 1, "phone": 1}).to_list(100)
        user_phones = {u["full_name"]: u.get("phone", "") for u in users}

        reminders_created = 0

        for rule in rules:
            if not rule.get("is_active", True):
                continue

            trigger = rule["trigger"]
            days = rule.get("days_threshold", 0)

            if trigger == "followup_due":
                cutoff_dt = now_dt - timedelta(days=days)
                cutoff_iso = cutoff_dt.isoformat()
                status_filter = status_clause(
                    rule.get("lead_statuses"),
                    default_regex="Follow Up",
                )
                leads = await db.leads.find(
                    {"$and": [status_filter, stale_updated_clause(cutoff_dt, cutoff_iso), sla_paused_exclusion()]},
                    {"_id": 0},
                ).to_list(200)

                for lead in leads:
                    dedupe_key = f"reminder:{trigger}:{lead['id']}:{today}"
                    already = await db.reminders.find_one({"dedupe_key": dedupe_key})
                    if already:
                        continue

                    rep = lead.get("assigned_to") or lead.get("presales_agent", "")
                    lead_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
                    project = lead.get("project", "N/A")

                    rep_user_id = await resolve_user_id_by_full_name(rep)
                    notif_dedupe = f"notification:reminder:{trigger}:{lead['id']}:{today}"
                    reminder_doc = {
                        "id": str(uuid.uuid4()),
                        "lead_id": lead["id"],
                        "lead_name": lead_name,
                        "assigned_to": rep,
                        "assigned_user_id": rep_user_id,
                        "trigger": trigger,
                        "rule_name": rule["name"],
                        "message": f"Follow up reminder: {lead_name} ({project}) is in {lead.get('lead_status', '')} status for {days}+ days",
                        "status": "sent",
                        "whatsapp_sent": False,
                        "created_at": now_iso,
                        "created_at_dt": now_dt,
                        "dedupe_key": dedupe_key,
                    }

                    phone = user_phones.get(rep, "")
                    if rule.get("send_whatsapp", True) and phone:
                        result = await send_whatsapp_template(
                            phone,
                            REMINDER_TEMPLATES.get("followup", ""),
                            [rep.split()[0] if rep else "Team", lead_name, project, lead.get("lead_status", "Follow Up")],
                        )
                        if result:
                            reminder_doc["whatsapp_sent"] = True

                    await _emit_reminder_notification(
                        rep_user_id=rep_user_id,
                        rep_name=rep,
                        title="Follow-up Due",
                        message=reminder_doc["message"],
                        lead_id=lead["id"],
                        lead_name=lead_name,
                        dedupe_key=notif_dedupe,
                    )

                    await db.reminders.insert_one(reminder_doc)
                    reminders_created += 1

            elif trigger == "site_visit_tomorrow":
                leads = await db.leads.find(
                    {"$and": [site_visit_tomorrow_clause(now_dt), sla_paused_exclusion()]},
                    {"_id": 0},
                ).to_list(200)
                for lead in leads:
                    dedupe_key = f"reminder:{trigger}:{lead['id']}:{today}"
                    already = await db.reminders.find_one({"dedupe_key": dedupe_key})
                    if already:
                        continue

                    rep = lead.get("assigned_to") or lead.get("presales_agent", "")
                    lead_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
                    project = lead.get("project", "N/A")
                    visit_dt = coerce_datetime(lead.get("visit_date_dt"))
                    visit_label = (
                        visit_dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y")
                        if visit_dt
                        else "tomorrow"
                    )

                    rep_user_id = await resolve_user_id_by_full_name(rep)
                    notif_dedupe = f"notification:reminder:{trigger}:{lead['id']}:{today}"
                    reminder_doc = {
                        "id": str(uuid.uuid4()),
                        "lead_id": lead["id"],
                        "lead_name": lead_name,
                        "assigned_to": rep,
                        "assigned_user_id": rep_user_id,
                        "trigger": trigger,
                        "rule_name": rule["name"],
                        "message": f"Site visit tomorrow: {lead_name} — {visit_label} ({project})",
                        "status": "sent",
                        "whatsapp_sent": False,
                        "created_at": now_iso,
                        "created_at_dt": now_dt,
                        "dedupe_key": dedupe_key,
                    }

                    phone = user_phones.get(rep, "")
                    if rule.get("send_whatsapp", True) and phone:
                        result = await send_whatsapp_template(
                            phone,
                            REMINDER_TEMPLATES.get("followup", ""),
                            [rep.split()[0] if rep else "Team", lead_name, project, "Site Visit Scheduled"],
                        )
                        if result:
                            reminder_doc["whatsapp_sent"] = True

                    await _emit_reminder_notification(
                        rep_user_id=rep_user_id,
                        rep_name=rep,
                        title="Site Visit Tomorrow",
                        message=reminder_doc["message"],
                        lead_id=lead["id"],
                        lead_name=lead_name,
                        dedupe_key=notif_dedupe,
                    )
                    await db.reminders.insert_one(reminder_doc)
                    reminders_created += 1

            elif trigger == "rnr_stale":
                cutoff_dt = now_dt - timedelta(days=days)
                cutoff_iso = cutoff_dt.isoformat()
                status_filter = rnr_status_clause(rule.get("lead_statuses"))
                leads = await db.leads.find(
                    {"$and": [status_filter, stale_updated_clause(cutoff_dt, cutoff_iso), sla_paused_exclusion()]},
                    {"_id": 0},
                ).to_list(200)
                for lead in leads:
                    dedupe_key = f"reminder:{trigger}:{lead['id']}:{today}"
                    already = await db.reminders.find_one({"dedupe_key": dedupe_key})
                    if already:
                        continue

                    rep = lead.get("assigned_to") or lead.get("presales_agent", "")
                    lead_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()

                    rep_user_id = await resolve_user_id_by_full_name(rep)
                    notif_dedupe = f"notification:reminder:{trigger}:{lead['id']}:{today}"
                    reminder_doc = {
                        "id": str(uuid.uuid4()),
                        "lead_id": lead["id"],
                        "lead_name": lead_name,
                        "assigned_to": rep,
                        "assigned_user_id": rep_user_id,
                        "trigger": trigger,
                        "rule_name": rule["name"],
                        "message": f"RNR Alert: {lead_name} has been unreachable for {days}+ days. Consider reassignment.",
                        "status": "sent",
                        "whatsapp_sent": False,
                        "created_at": now_iso,
                        "created_at_dt": now_dt,
                        "dedupe_key": dedupe_key,
                    }

                    await _emit_reminder_notification(
                        rep_user_id=rep_user_id,
                        rep_name=rep,
                        title="RNR Stale",
                        message=reminder_doc["message"],
                        lead_id=lead["id"],
                        lead_name=lead_name,
                        dedupe_key=notif_dedupe,
                        urgency="critical",
                    )
                    await db.reminders.insert_one(reminder_doc)
                    reminders_created += 1

            elif trigger == "task_overdue":
                overdue_tasks = await db.tasks.find({"status": "pending", "due_date": {"$lt": today}}, {"_id": 0}).to_list(200)
                task_lead_ids = {t.get("lead_id") for t in overdue_tasks if t.get("lead_id")}
                paused_lead_ids: set[str] = set()
                if task_lead_ids:
                    paused_leads = await db.leads.find(
                        {"id": {"$in": list(task_lead_ids)}, "sla_paused": True},
                        {"_id": 0, "id": 1},
                    ).to_list(len(task_lead_ids))
                    paused_lead_ids = {lead["id"] for lead in paused_leads}
                for task in overdue_tasks:
                    if task.get("lead_id") in paused_lead_ids:
                        continue
                    dedupe_key = f"reminder:{trigger}:{task['id']}:{today}"
                    already = await db.reminders.find_one({"dedupe_key": dedupe_key})
                    if already:
                        continue

                    rep = task.get("assigned_to", "")
                    rep_user_id = await resolve_user_id_by_full_name(rep)
                    reminder_doc = {
                        "id": str(uuid.uuid4()),
                        "task_id": task["id"],
                        "lead_id": task.get("lead_id", ""),
                        "lead_name": task.get("lead_name", ""),
                        "assigned_to": rep,
                        "assigned_user_id": rep_user_id,
                        "trigger": trigger,
                        "rule_name": rule["name"],
                        "message": f"Overdue task: '{task.get('description', '')}' was due on {task.get('due_date', '')}",
                        "status": "sent",
                        "whatsapp_sent": False,
                        "created_at": now_iso,
                        "created_at_dt": now_dt,
                        "dedupe_key": dedupe_key,
                    }

                    phone = user_phones.get(rep, "")
                    if rule.get("send_whatsapp", True) and phone:
                        result = await send_whatsapp_template(
                            phone,
                            REMINDER_TEMPLATES.get("task_due", ""),
                            [rep.split()[0] if rep else "Team", task.get("description", "")[:50], task.get("due_date", "today"), task.get("priority", "medium")],
                        )
                        if result:
                            reminder_doc["whatsapp_sent"] = True

                    await _emit_reminder_notification(
                        rep_user_id=rep_user_id,
                        rep_name=rep,
                        title="Task Overdue",
                        message=reminder_doc["message"],
                        lead_id=task.get("lead_id", ""),
                        lead_name=task.get("lead_name", ""),
                        task_id=task["id"],
                        dedupe_key=f"notification:reminder:{trigger}:{task['id']}:{today}",
                        urgency="critical",
                    )
                    await db.reminders.insert_one(reminder_doc)
                    reminders_created += 1

        logger.info(f"Reminder engine: created {reminders_created} reminders")
        return reminders_created
    except Exception as e:
        logger.error(f"Reminder engine error: {e}")
        return 0


@router.get("/reminders/rules")
async def get_reminder_rules(current_user: dict = Depends(get_current_user)):
    rules = await db.reminder_rules.find({}, {"_id": 0}).to_list(50)
    if not rules:
        rules = await seed_default_reminder_rules()
    return rules


@router.put("/reminders/rules/{rule_id}")
async def update_reminder_rule(rule_id: str, updates: dict, current_user: dict = Depends(get_current_user)):
    allowed = {"is_active", "send_whatsapp", "days_threshold", "name"}
    update_data = {k: v for k, v in updates.items() if k in allowed}
    await db.reminder_rules.update_one({"id": rule_id}, {"$set": update_data})
    return {"message": "Rule updated"}


@router.get("/reminders/history")
async def get_reminder_history(limit: int = 50, current_user: dict = Depends(get_current_user)):
    reminders = await db.reminders.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return reminders


@router.post("/reminders/trigger")
async def trigger_reminders_now(current_user: dict = Depends(get_current_user)):
    count = await process_reminders()
    return {"message": f"Reminder engine ran. Created {count} reminders."}


@router.post("/reminders/send")
async def send_manual_reminder(req: ManualReminderRequest, current_user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": req.lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
    rep = lead.get("assigned_to") or lead.get("presales_agent", "")
    rep_user_id = await resolve_user_id_by_full_name(rep)
    now_dt = utc_now()
    now_iso = iso_utc_now()
    dedupe_key = f"reminder:manual:{req.lead_id}:{now_iso}"

    reminder_doc = {
        "id": str(uuid.uuid4()),
        "lead_id": req.lead_id,
        "lead_name": lead_name,
        "assigned_to": rep,
        "assigned_user_id": rep_user_id,
        "trigger": "manual",
        "rule_name": "Manual Reminder",
        "message": req.message,
        "status": "sent",
        "whatsapp_sent": False,
        "created_at": now_iso,
        "created_at_dt": now_dt,
        "dedupe_key": dedupe_key,
    }

    if req.send_whatsapp:
        users = await db.users.find({"full_name": rep}, {"_id": 0}).to_list(1)
        phone = users[0].get("phone", "") if users else ""
        if phone:
            result = await send_whatsapp_template(
                phone,
                REMINDER_TEMPLATES.get("followup", ""),
                [rep.split()[0] if rep else "Team", lead_name, lead.get("project", "N/A"), lead.get("lead_status", "Open")],
            )
            if result:
                reminder_doc["whatsapp_sent"] = True

    await _emit_reminder_notification(
        rep_user_id=rep_user_id,
        rep_name=rep,
        title="Manual Reminder",
        message=req.message,
        lead_id=req.lead_id,
        lead_name=lead_name,
        dedupe_key=f"notification:reminder:manual:{req.lead_id}:{now_iso}",
    )

    await db.reminders.insert_one(reminder_doc)
    return {"message": "Reminder sent", "id": reminder_doc["id"], "whatsapp_sent": reminder_doc["whatsapp_sent"]}

