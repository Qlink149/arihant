import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app_state import db, get_current_user, utc_now, iso_utc_now, resolve_user_id_by_full_name


router = APIRouter()


class TransferLeadRequest(BaseModel):
    lead_id: str
    to_rep: str
    to_user_id: Optional[str] = None
    notes: Optional[str] = None


@router.post("/leads/transfer")
async def transfer_lead(req: TransferLeadRequest, current_user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": req.lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(404, "Lead not found")

    from_rep = lead.get("assigned_to") or lead.get("presales_agent") or current_user["full_name"]
    transfer_id = str(uuid.uuid4())
    now_dt = utc_now()
    now_iso = iso_utc_now()

    from_user_id = await resolve_user_id_by_full_name(from_rep)
    to_user_id = req.to_user_id or await resolve_user_id_by_full_name(req.to_rep)
    if not to_user_id:
        raise HTTPException(status_code=400, detail="to_user_id is required (no matching user for to_rep)")

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
        "lead_temperature": lead.get("temperature", "Unknown"),
        "project": lead.get("project", ""),
        "acknowledged": False,
        "transferred_at": now_iso,
        "transferred_at_dt": now_dt,
        "transferred_by": current_user["full_name"],
        "transferred_by_user_id": current_user.get("id"),
    }
    await db.lead_transfers.insert_one(transfer_doc)

    await db.leads.update_one(
        {"id": req.lead_id},
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
                    "description": f"Transferred from {from_rep} to {req.to_rep}" + (f". Notes: {req.notes}" if req.notes else ""),
                    "agent": current_user["full_name"],
                    "actor_user_id": current_user.get("id"),
                    "actor_name": current_user.get("full_name"),
                }
            },
        },
    )

    await db.notifications.insert_one(
        {
            "id": str(uuid.uuid4()),
            "type": "lead_transferred",
            "title": "Lead Transferred to You",
            "message": f"{lead.get('first_name', '')} {lead.get('last_name', '')} transferred from {from_rep}" + (f". Notes: {req.notes}" if req.notes else ""),
            "lead_id": req.lead_id,
            "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}",
            "severity": "high",
            "urgency": "action_needed",
            "assigned_to": req.to_rep,
            "recipient_name": req.to_rep,
            "recipient_user_id": to_user_id,
            "is_read": False,
            "created_at": now_iso,
            "created_at_dt": now_dt,
        }
    )

    return {"message": "Lead transferred", "transfer_id": transfer_id}


@router.put("/leads/transfer/{transfer_id}/acknowledge")
async def acknowledge_transfer(transfer_id: str, current_user: dict = Depends(get_current_user)):
    await db.lead_transfers.update_one(
        {"id": transfer_id},
        {"$set": {"acknowledged": True, "acknowledged_at": iso_utc_now(), "acknowledged_at_dt": utc_now()}},
    )
    return {"message": "Transfer acknowledged"}

