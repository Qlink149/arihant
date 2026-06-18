import uuid
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from crm.api.v1.endpoints.my_dashboard import _transfer_at
from crm.services.dashboard_scope import resolve_leads_base_filter, user_owns_lead
from crm.core.platform_ops import assert_assignee_allowed, is_platform_operator
from crm.core.state import db, get_current_user, iso_utc_now, resolve_user_id_by_full_name, utc_now
from crm.services.lead_events import log_lead_event
from crm.services.notification_service import create_notification
from crm.services.transfer_queries import incoming_transfer_filter, outgoing_transfer_filter


router = APIRouter()


class TransferLeadRequest(BaseModel):
    lead_id: str
    to_rep: str
    to_user_id: Optional[str] = None
    notes: Optional[str] = None
    expected_from_user_id: Optional[str] = None


def _build_transfer_list_query(
    direction: str, name: str, uid: str, is_manager: bool, since_days: Optional[int]
) -> Dict[str, Any]:
    if direction == "incoming":
        query = incoming_transfer_filter(name, uid, is_manager, since_days=since_days)
    elif direction == "outgoing":
        query = outgoing_transfer_filter(name, uid, is_manager, since_days=since_days)
    else:
        query = {
            "$or": [
                incoming_transfer_filter(name, uid, is_manager, since_days=since_days),
                outgoing_transfer_filter(name, uid, is_manager, since_days=since_days),
            ]
        }
    return query


@router.get("/transfers")
async def list_transfers(
    direction: Literal["incoming", "outgoing", "all"] = Query("incoming"),
    since_days: Optional[int] = Query(90, ge=1, le=3650),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """List lead transfers for the current user (inbox, outbox, or both)."""
    name = current_user["full_name"]
    uid = current_user["id"]
    _, is_manager = await resolve_leads_base_filter(uid, name, current_user)

    query = _build_transfer_list_query(direction, name, uid, is_manager, since_days)
    rows = await db.lead_transfers.find(query, {"_id": 0}).to_list(limit * 2)
    transfers = sorted(rows, key=_transfer_at, reverse=True)[:limit]
    return {"transfers": transfers, "direction": direction, "count": len(transfers)}


@router.post("/leads/transfer")
async def transfer_lead(req: TransferLeadRequest, current_user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": req.lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(404, "Lead not found")

    uid = current_user["id"]
    name = current_user["full_name"]
    _, is_manager = await resolve_leads_base_filter(uid, name, current_user)
    if not is_manager and not is_platform_operator(current_user) and not user_owns_lead(lead, current_user):
        raise HTTPException(status_code=403, detail="You can only transfer leads assigned to you")

    await assert_assignee_allowed(req.to_rep)

    from_rep = lead.get("assigned_to") or lead.get("presales_agent") or current_user["full_name"]
    transfer_id = str(uuid.uuid4())
    now_dt = utc_now()
    now_iso = iso_utc_now()

    from_user_id = await resolve_user_id_by_full_name(from_rep)
    to_user_id = req.to_user_id or await resolve_user_id_by_full_name(req.to_rep)
    if not to_user_id:
        raise HTTPException(status_code=400, detail="to_user_id is required (no matching user for to_rep)")

    target_user = await db.users.find_one({"id": to_user_id}, {"_id": 0, "email": 1, "full_name": 1})
    if target_user:
        await assert_assignee_allowed(target_user.get("full_name"))
        await assert_assignee_allowed(target_user.get("email"))

    transfer_doc = {
        "id": transfer_id,
        "lead_id": req.lead_id,
        "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}",
        "from_rep": from_rep,
        "from_name": from_rep,
        "from_user_id": from_user_id,
        "to_rep": req.to_rep,
        "to_name": req.to_rep,
        "to_user_id": to_user_id,
        "notes": req.notes,
        "lead_temperature": lead.get("temperature") or "—",
        "project": lead.get("project", ""),
        "transferred_at": now_iso,
        "transferred_at_dt": now_dt,
        "transferred_by": current_user["full_name"],
        "transferred_by_user_id": current_user.get("id"),
    }
    await db.lead_transfers.insert_one(transfer_doc)

    lead_filter: Dict[str, Any] = {"id": req.lead_id}
    if req.expected_from_user_id:
        lead_filter["assigned_user_id"] = req.expected_from_user_id

    res = await db.leads.update_one(
        lead_filter,
        {
            "$set": {
                "assigned_to": req.to_rep,
                "assigned_to_name": req.to_rep,
                "assigned_user_id": to_user_id,
                "presales_agent": req.to_rep,
                "updated_at": now_iso,
                "updated_at_dt": now_dt,
            },
            "$push": {
                "context_updates": {
                    "type": "transfer",
                    "timestamp": now_iso,
                    "timestamp_dt": now_dt,
                    "description": f"Transferred from {from_rep} to {req.to_rep}"
                    + (f". Notes: {req.notes}" if req.notes else ""),
                    "agent": current_user["full_name"],
                    "actor_user_id": current_user.get("id"),
                    "actor_name": current_user.get("full_name"),
                }
            },
        },
    )
    if res.matched_count == 0:
        await db.lead_transfers.delete_one({"id": transfer_id})
        raise HTTPException(
            status_code=409,
            detail="Lead ownership changed. Refresh and retry the transfer.",
        )

    lead_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
    transfer_message = (
        f"{lead_name} assigned by {current_user['full_name']}"
        + (f". Notes: {req.notes}" if req.notes else "")
    )
    await create_notification(
        recipient_user_id=to_user_id,
        recipient_name=req.to_rep,
        title="Lead Assigned to You",
        message=transfer_message,
        notification_type="lead_transferred",
        lead_id=req.lead_id,
        lead_name=lead_name,
        severity="high",
        urgency="action_needed",
    )

    await log_lead_event(
        "transfer_created",
        lead_id=req.lead_id,
        actor_user_id=current_user.get("id"),
        actor_name=current_user.get("full_name"),
        payload={"transfer_id": transfer_id, "to_rep": req.to_rep, "from_rep": from_rep},
    )

    return {"message": "Lead transferred", "transfer_id": transfer_id}


@router.put("/leads/transfer/{transfer_id}/acknowledge")
async def acknowledge_transfer(transfer_id: str, current_user: dict = Depends(get_current_user)):
    _ = transfer_id
    _ = current_user
    raise HTTPException(
        status_code=410,
        detail="Transfers are one-way and no longer require acknowledgement.",
    )
