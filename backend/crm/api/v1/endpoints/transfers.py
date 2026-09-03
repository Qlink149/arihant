from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from crm.api.v1.endpoints.my_dashboard import _transfer_at
from crm.services.dashboard_scope import resolve_leads_base_filter, user_owns_lead
from crm.core.platform_ops import assert_assignee_allowed, is_platform_operator
from crm.core.state import db, get_current_user, resolve_user_id_by_full_name
from crm.services.lead_transfer_service import assign_lead_ownership
from crm.services.transfer_queries import incoming_transfer_filter_still_owned, outgoing_transfer_filter


router = APIRouter()


class TransferLeadRequest(BaseModel):
    lead_id: str
    to_rep: str
    to_user_id: Optional[str] = None
    notes: Optional[str] = None
    expected_from_user_id: Optional[str] = None


async def _build_transfer_list_query(
    direction: str, name: str, uid: str, is_manager: bool, since_days: Optional[int]
) -> Dict[str, Any]:
    """#50: "incoming"/"received" only counts leads still assigned to the current user."""
    if direction == "incoming":
        query = await incoming_transfer_filter_still_owned(name, uid, is_manager, since_days=since_days)
    elif direction == "outgoing":
        query = outgoing_transfer_filter(name, uid, is_manager, since_days=since_days)
    else:
        query = {
            "$or": [
                await incoming_transfer_filter_still_owned(name, uid, is_manager, since_days=since_days),
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

    query = await _build_transfer_list_query(direction, name, uid, is_manager, since_days)
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

    to_user_id = req.to_user_id or await resolve_user_id_by_full_name(req.to_rep)
    if not to_user_id:
        raise HTTPException(status_code=400, detail="to_user_id is required (no matching user for to_rep)")

    transfer_id = await assign_lead_ownership(
        lead=lead,
        to_rep=req.to_rep,
        to_user_id=to_user_id,
        current_user=current_user,
        notes=req.notes,
        expected_from_user_id=req.expected_from_user_id,
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
