"""Admin-only Meta CAPI test endpoint (no automatic CRM trigger)."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from crm.core.state import db, get_current_user
from crm.services.meta_capi_service import send_qualified_lead_event

router = APIRouter()


def _require_admin(user: dict) -> None:
    role = (user.get("role") or "").strip().lower()
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


class MetaCapiTestBody(BaseModel):
    lead_id: str = Field(..., min_length=1)


@router.post("/internal/meta-capi/test")
async def test_meta_capi_qualified_lead(
    body: MetaCapiTestBody,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Look up a lead and send a QualifiedLead event to Meta (test / manual only)."""
    _require_admin(current_user)

    lead_id = body.lead_id.strip()
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = await send_qualified_lead_event(lead)
    return result
