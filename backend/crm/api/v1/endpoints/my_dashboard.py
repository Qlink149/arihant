from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from crm.constants.lead_status import CLOSED_LEAD_STATUS_REGEX, NURTURING_STATUS
from crm.core.state import coerce_datetime, db, get_current_user, utc_now
from crm.services.dashboard_scope import resolve_leads_base_filter
from crm.services.lead_overview_service import (
    build_lead_overview_metrics,
    build_metric_context,
    metric_filter_for_key,
)
from crm.services.lead_search import build_leads_list_query, merge_query
from crm.services.transfer_queries import (
    incoming_transfer_filter,
    outgoing_transfer_filter,
)


router = APIRouter()

LEAD_PROJECTION = {
    "_id": 0,
    "id": 1,
    "first_name": 1,
    "last_name": 1,
    "project": 1,
    "phone": 1,
    "temperature": 1,
    "lead_status": 1,
    "vip": 1,
    "assigned_to": 1,
    "assigned_to_name": 1,
    "next_action_date": 1,
    "updated_at": 1,
}

LEAD_SORT = [("updated_at_dt", -1), ("updated_at", -1), ("created_at_dt", -1)]


def _transfer_at(t: dict) -> datetime:
    return (
        coerce_datetime(t.get("transferred_at_dt"))
        or coerce_datetime(t.get("transferred_at"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )


def _task_scope_filter(uid: str, name: str) -> dict:
    return {
        "$or": [
            {"assigned_user_id": uid},
            {"assigned_to": name},
            {"assigned_to_name": name},
        ],
    }


COMPLETED_TASK_STATUSES = frozenset({"completed", "done", "cancelled"})


@router.get("/my-dashboard")
async def get_my_dashboard(current_user: dict = Depends(get_current_user)):
    name = current_user["full_name"]
    uid = current_user["id"]
    now = utc_now()

    base_filter, is_manager = await resolve_leads_base_filter(uid, name, current_user)

    total_leads = await db.leads.count_documents(base_filter)
    nurturing_filter = {**base_filter, "lead_status": {"$regex": f"^{NURTURING_STATUS}$", "$options": "i"}}
    hot = await db.leads.count_documents({**nurturing_filter, "temperature": "Hot"})
    warm = await db.leads.count_documents({**nurturing_filter, "temperature": "Warm"})
    site_visits = await db.leads.count_documents(
        {**base_filter, "lead_status": {"$regex": "site visit", "$options": "i"}}
    )
    closed = await db.leads.count_documents(
        {
            **base_filter,
            "lead_status": {"$regex": CLOSED_LEAD_STATUS_REGEX, "$options": "i"},
        }
    )
    conversion_rate = round((closed / total_leads * 100), 1) if total_leads > 0 else 0

    incoming_q = incoming_transfer_filter(name, uid, is_manager, since_days=90)
    outgoing_q = outgoing_transfer_filter(name, uid, is_manager, since_days=90)
    leads_received = await db.lead_transfers.count_documents(incoming_q)
    leads_transferred = await db.lead_transfers.count_documents(outgoing_q)

    raw_incoming = await db.lead_transfers.find(incoming_q, {"_id": 0}).to_list(200)
    raw_outgoing = await db.lead_transfers.find(outgoing_q, {"_id": 0}).to_list(200)
    incoming_transfers = sorted(raw_incoming, key=_transfer_at, reverse=True)[:50]
    outgoing_transfers = sorted(raw_outgoing, key=_transfer_at, reverse=True)[:50]

    task_query = _task_scope_filter(uid, name)
    my_tasks = await db.tasks.find(task_query, {"_id": 0}).sort("due_date", 1).to_list(100)

    pending_tasks = [t for t in my_tasks if t.get("status") == "pending"]
    overdue_tasks = [t for t in pending_tasks if t.get("due_date", "9999") < now.strftime("%Y-%m-%d")]
    completed_tasks = [t for t in my_tasks if t.get("status") in COMPLETED_TASK_STATUSES]

    return {
        "rep_name": name,
        "is_manager": is_manager,
        "transferred_leads": incoming_transfers,
        "outgoing_transfers": outgoing_transfers,
        "my_tasks": my_tasks,
        "metrics": {
            "total_leads": total_leads,
            "hot": hot,
            "warm": warm,
            "nurturing_hot": hot,
            "nurturing_warm": warm,
            "site_visits": site_visits,
            "closed": closed,
            "conversion_rate": conversion_rate,
            "pending_tasks": len(pending_tasks),
            "overdue_tasks": len(overdue_tasks),
            "completed_tasks": len(completed_tasks),
            "leads_received": leads_received,
            "leads_transferred": leads_transferred,
        },
    }


@router.get("/my-dashboard/lead-overview")
async def get_lead_overview(current_user: dict = Depends(get_current_user)):
    uid = current_user["id"]
    name = current_user["full_name"]
    base_filter, is_manager = await resolve_leads_base_filter(uid, name, current_user)
    return await build_lead_overview_metrics(
        base_filter,
        uid=uid,
        name=name,
        is_manager=is_manager,
    )


@router.get("/my-dashboard/leads")
async def get_my_dashboard_leads(
    skip: int = Query(0, ge=0),
    limit: int = Query(150, ge=1, le=500),
    temperature: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    metric: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    uid = current_user["id"]
    name = current_user["full_name"]

    base_filter, is_manager = await resolve_leads_base_filter(uid, name, current_user)
    metric_clause = {}
    if metric:
        ctx = build_metric_context(base_filter, uid=uid, name=name, is_manager=is_manager)
        metric_clause = metric_filter_for_key(metric, ctx)

    query = build_leads_list_query(
        merge_query(base_filter, metric_clause) if metric_clause else base_filter,
        temperature=temperature,
        search=search,
    )

    total = await db.leads.count_documents(query)
    cursor = db.leads.find(query, LEAD_PROJECTION).sort(LEAD_SORT).skip(skip).limit(limit)
    leads = await cursor.to_list(limit)

    return {"leads": leads, "total": total, "skip": skip, "limit": limit}
