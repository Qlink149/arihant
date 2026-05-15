import uuid

from fastapi import APIRouter, Depends, HTTPException

from app_state import AssignmentRule, db, get_current_user, iso_utc_now, resolve_user_id_by_full_name, utc_now


router = APIRouter()


@router.get("/assignment-rules")
async def get_assignment_rules(current_user: dict = Depends(get_current_user)):
    rules = await db.assignment_rules.find({}, {"_id": 0}).to_list(100)
    return rules


@router.post("/assignment-rules")
async def create_assignment_rule(rule: AssignmentRule, current_user: dict = Depends(get_current_user)):
    rule_dict = rule.model_dump()
    await db.assignment_rules.insert_one(rule_dict)
    return rule_dict


@router.post("/leads/auto-assign")
async def auto_assign_lead(lead_id: str, current_user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    managers = await db.leads.distinct("presales_agent")
    managers = [m for m in managers if m and m.strip()]

    if not managers:
        return {"assigned_to": None, "message": "No sales managers found"}

    inactive_statuses = ["Advance Paid", "Closed", "Booked", "Dropped", "Unqualified"]
    pipeline = [
        {"$match": {"presales_agent": {"$in": managers}, "lead_status": {"$nin": inactive_statuses}}},
        {"$group": {"_id": "$assigned_to", "count": {"$sum": 1}}},
    ]
    counts = await db.leads.aggregate(pipeline).to_list(len(managers))
    count_map = {c["_id"]: c["count"] for c in counts if c["_id"]}

    min_count = float("inf")
    assigned_to = managers[0]
    for mgr in managers:
        c = count_map.get(mgr, 0)
        if c < min_count:
            min_count = c
            assigned_to = mgr

    now_dt = utc_now()
    now_iso = iso_utc_now()
    assignee_user_id = await resolve_user_id_by_full_name(assigned_to)
    await db.leads.update_one(
        {"id": lead_id},
        {
            "$set": {
                "assigned_to": assigned_to,
                "presales_agent": assigned_to,
                "assigned_user_id": assignee_user_id,
                "assigned_to_name": assigned_to,
                "updated_at": now_iso,
                "updated_at_dt": now_dt,
            },
            "$push": {
                "context_updates": {
                    "type": "assigned",
                    "timestamp": now_iso,
                    "timestamp_dt": now_dt,
                    "description": f"Auto-assigned to {assigned_to} (fewest active leads: {int(min_count)})",
                    "agent": "System",
                }
            },
        },
    )

    await db.notifications.insert_one(
        {
            "id": str(uuid.uuid4()),
            "type": "new_lead_assigned",
            "title": "New Lead Assigned",
            "message": f"Lead {lead.get('first_name', '')} {lead.get('last_name', '')} has been assigned to you from {lead.get('lead_source', 'Unknown')}",
            "lead_id": lead_id,
            "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}",
            "assigned_to": assigned_to,
            "user_id": assigned_to,
            "recipient_user_id": assignee_user_id,
            "recipient_name": assigned_to,
            "severity": "low",
            "urgency": "info",
            "is_read": False,
            "created_at": now_iso,
            "created_at_dt": now_dt,
        }
    )

    return {"assigned_to": assigned_to, "active_leads": int(min_count)}

