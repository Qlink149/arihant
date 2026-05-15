from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app_state import coerce_datetime, db, get_current_user, utc_now


router = APIRouter()

MAX_LEADS_SCAN = 4000


def _lead_updated_at(lead: dict) -> datetime:
    return (
        coerce_datetime(lead.get("updated_at_dt"))
        or coerce_datetime(lead.get("updated_at"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )


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


@router.get("/my-dashboard")
async def get_my_dashboard(current_user: dict = Depends(get_current_user)):
    name = current_user["full_name"]
    uid = current_user["id"]
    now = utc_now()

    rep_filter = _rep_lead_filter(uid, name)
    rep_lead_count = await db.leads.count_documents(rep_filter)
    is_manager = rep_lead_count == 0

    if is_manager:
        raw_leads = await db.leads.find({}, {"_id": 0}).to_list(MAX_LEADS_SCAN)
    else:
        raw_leads = await db.leads.find(rep_filter, {"_id": 0}).to_list(MAX_LEADS_SCAN)

    my_leads = sorted(raw_leads, key=_lead_updated_at, reverse=True)[:500]

    transfer_query = {"acknowledged": {"$ne": True}}
    if not is_manager:
        transfer_query["to_rep"] = name
    raw_transfers = await db.lead_transfers.find(transfer_query, {"_id": 0}).to_list(200)
    transferred = sorted(raw_transfers, key=_transfer_at, reverse=True)[:50]

    task_query = {} if is_manager else {"assigned_to": name}
    my_tasks = await db.tasks.find(task_query, {"_id": 0}).sort("due_date", 1).to_list(100)

    total_leads = len(my_leads)
    hot = sum(1 for l in my_leads if l.get("temperature") == "Hot")
    warm = sum(1 for l in my_leads if l.get("temperature") == "Warm")
    cold = sum(1 for l in my_leads if l.get("temperature") == "Cold")
    site_visits = sum(1 for l in my_leads if "site visit" in (l.get("lead_status") or "").lower())
    closed = sum(1 for l in my_leads if (l.get("lead_status") or "").lower() in ["advance paid", "closed", "booked"])
    conversion_rate = round((closed / total_leads * 100), 1) if total_leads > 0 else 0

    pending_tasks = [t for t in my_tasks if t.get("status") == "pending"]
    overdue_tasks = [t for t in pending_tasks if t.get("due_date", "9999") < now.strftime("%Y-%m-%d")]

    return {
        "rep_name": name,
        "is_manager": is_manager,
        "my_leads": my_leads,
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

