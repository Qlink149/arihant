import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from crm.constants.lead_status import CLOSED_LEAD_STATUS_REGEX, NURTURING_STATUS
from crm.core.state import coerce_datetime, db, get_current_user, utc_now
from crm.services.dashboard_scope import resolve_leads_base_filter
from crm.services.lead_overview_service import (
    build_lead_overview_metrics,
    build_metric_context,
    enrich_follow_up_task_ids,
    ist_day_window,
    metric_filter_for_key,
    resolve_metric_key,
)
from crm.services.lead_search import build_leads_list_query, merge_query
from crm.services.transfer_queries import (
    incoming_transfer_filter,
    outgoing_transfer_filter,
)
from crm.services.lead_projections import LEAD_LIST_SORT, MY_DASHBOARD_LEAD_PROJECTION
from crm.services.task_enrichment import enrich_tasks


router = APIRouter()

LEAD_PROJECTION = MY_DASHBOARD_LEAD_PROJECTION
LEAD_SORT = LEAD_LIST_SORT


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

    nurturing_filter = {**base_filter, "lead_status": {"$regex": f"^{NURTURING_STATUS}$", "$options": "i"}}
    closed_filter = {
        **base_filter,
        "lead_status": {"$regex": CLOSED_LEAD_STATUS_REGEX.pattern, "$options": "i"},
    }
    dashboard_facet = [
        {
            "$facet": {
                "total_leads": [{"$match": base_filter}, {"$count": "n"}],
                "hot": [{"$match": {**nurturing_filter, "temperature": "Hot"}}, {"$count": "n"}],
                "warm": [{"$match": {**nurturing_filter, "temperature": "Warm"}}, {"$count": "n"}],
                "site_visits": [
                    {"$match": {**base_filter, "lead_status": {"$regex": "site visit", "$options": "i"}}},
                    {"$count": "n"},
                ],
                "closed": [{"$match": closed_filter}, {"$count": "n"}],
            }
        }
    ]
    facet_rows = await db.leads.aggregate(dashboard_facet).to_list(1)
    facet_doc = facet_rows[0] if facet_rows else {}

    def _count(key: str) -> int:
        branch = facet_doc.get(key) or []
        return int(branch[0].get("n", 0)) if branch else 0

    total_leads = _count("total_leads")
    hot = _count("hot")
    warm = _count("warm")
    site_visits = _count("site_visits")
    closed = _count("closed")
    conversion_rate = round((closed / total_leads * 100), 1) if total_leads > 0 else 0

    incoming_q = incoming_transfer_filter(name, uid, is_manager, since_days=90)
    outgoing_q = outgoing_transfer_filter(name, uid, is_manager, since_days=90)
    leads_received, leads_transferred, incoming_transfers, outgoing_transfers = await asyncio.gather(
        db.lead_transfers.count_documents(incoming_q),
        db.lead_transfers.count_documents(outgoing_q),
        db.lead_transfers.find(incoming_q, {"_id": 0}).sort("transferred_at_dt", -1).sort("transferred_at", -1).limit(50).to_list(50),
        db.lead_transfers.find(outgoing_q, {"_id": 0}).sort("transferred_at_dt", -1).sort("transferred_at", -1).limit(50).to_list(50),
    )

    task_query = _task_scope_filter(uid, name)
    my_tasks = await db.tasks.find(task_query, {"_id": 0}).sort("due_date", 1).to_list(100)
    my_tasks = await enrich_tasks(my_tasks)

    pending_tasks = [t for t in my_tasks if t.get("status") == "pending"]
    today_str, _, _ = ist_day_window(now)
    overdue_tasks = [t for t in pending_tasks if (t.get("due_date") or "9999")[:10] < today_str]
    completed_tasks = [t for t in my_tasks if t.get("status") in COMPLETED_TASK_STATUSES]

    return {
        "rep_name": name,
        "is_manager": is_manager,
        "transferred_leads": incoming_transfers,
        "outgoing_transfers": outgoing_transfers,
        "incoming_transfers_total": leads_received,
        "outgoing_transfers_total": leads_transferred,
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
        metric = resolve_metric_key(metric)
        ctx = build_metric_context(base_filter, uid=uid, name=name, is_manager=is_manager)
        if metric in ("follow_up_today", "missed_follow_up"):
            await enrich_follow_up_task_ids(ctx, base_filter=base_filter)
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
