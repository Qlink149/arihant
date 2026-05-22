from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from crm.core.platform_ops import is_platform_operator
from crm.core.state import coerce_datetime, db, get_current_user, utc_now
from crm.services.lead_search import build_leads_list_query


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
    "updated_at": 1,
}

LEAD_SORT = [("updated_at_dt", -1), ("updated_at", -1), ("created_at_dt", -1)]


def _transfer_at(t: dict) -> datetime:
    return (
        coerce_datetime(t.get("transferred_at_dt"))
        or coerce_datetime(t.get("transferred_at"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )


def _rep_lead_filter(user_id: str, full_name: str) -> dict:
    return {
        "$or": [
            {"assigned_user_id": user_id},
            {"assigned_to_name": full_name},
            {"assigned_to": full_name},
            {"presales_agent": full_name},
        ]
    }


async def _resolve_leads_base_filter(uid: str, name: str, current_user: dict) -> tuple[dict, bool]:
    if is_platform_operator(current_user):
        return {}, True

    rep_filter = _rep_lead_filter(uid, name)
    rep_lead_count = await db.leads.count_documents(rep_filter)
    is_manager = rep_lead_count == 0
    base_filter: dict = {} if is_manager else rep_filter
    return base_filter, is_manager


@router.get("/my-dashboard")
async def get_my_dashboard(current_user: dict = Depends(get_current_user)):
    name = current_user["full_name"]
    uid = current_user["id"]
    now = utc_now()

    base_filter, is_manager = await _resolve_leads_base_filter(uid, name, current_user)

    total_leads = await db.leads.count_documents(base_filter)
    hot = await db.leads.count_documents({**base_filter, "temperature": "Hot"})
    warm = await db.leads.count_documents({**base_filter, "temperature": "Warm"})
    cold = await db.leads.count_documents({**base_filter, "temperature": "Cold"})
    site_visits = await db.leads.count_documents(
        {**base_filter, "lead_status": {"$regex": "site visit", "$options": "i"}}
    )
    closed = await db.leads.count_documents(
        {
            **base_filter,
            "lead_status": {"$regex": "advance paid|closed|booked", "$options": "i"},
        }
    )
    conversion_rate = round((closed / total_leads * 100), 1) if total_leads > 0 else 0

    transfer_query: Dict[str, Any] = {"acknowledged": {"$ne": True}}
    if not is_manager:
        transfer_query["to_rep"] = name
    raw_transfers = await db.lead_transfers.find(transfer_query, {"_id": 0}).to_list(200)
    transferred = sorted(raw_transfers, key=_transfer_at, reverse=True)[:50]

    task_query = {} if is_manager else {"assigned_to": name}
    my_tasks = await db.tasks.find(task_query, {"_id": 0}).sort("due_date", 1).to_list(100)

    pending_tasks = [t for t in my_tasks if t.get("status") == "pending"]
    overdue_tasks = [t for t in pending_tasks if t.get("due_date", "9999") < now.strftime("%Y-%m-%d")]

    return {
        "rep_name": name,
        "is_manager": is_manager,
        "transferred_leads": transferred,
        "my_tasks": my_tasks,
        "metrics": {
            "total_leads": total_leads,
            "hot": hot,
            "warm": warm,
            "cold": cold,
            "site_visits": site_visits,
            "closed": closed,
            "conversion_rate": conversion_rate,
            "pending_tasks": len(pending_tasks),
            "overdue_tasks": len(overdue_tasks),
        },
    }


@router.get("/my-dashboard/leads")
async def get_my_dashboard_leads(
    skip: int = Query(0, ge=0),
    limit: int = Query(150, ge=1, le=500),
    temperature: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    uid = current_user["id"]
    name = current_user["full_name"]

    base_filter, _ = await _resolve_leads_base_filter(uid, name, current_user)
    query = build_leads_list_query(base_filter, temperature=temperature, search=search)

    total = await db.leads.count_documents(query)
    cursor = db.leads.find(query, LEAD_PROJECTION).sort(LEAD_SORT).skip(skip).limit(limit)
    leads = await cursor.to_list(limit)

    return {"leads": leads, "total": total, "skip": skip, "limit": limit}
