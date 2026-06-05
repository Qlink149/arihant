from fastapi import APIRouter, Depends, HTTPException

from crm.core.state import db, get_current_user
from crm.models.schemas.assignment_schemas import AssignmentRule
from crm.services import assignment_router, assignment_service

router = APIRouter()


@router.get("/assignment-rules")
async def get_assignment_rules(current_user: dict = Depends(get_current_user)):
    return await assignment_service.list_rules()


@router.post("/assignment-rules")
async def create_assignment_rule(rule: AssignmentRule, current_user: dict = Depends(get_current_user)):
    return await assignment_service.create_rule(rule)


@router.post("/leads/auto-assign")
async def auto_assign_lead(lead_id: str, current_user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0, "id": 1})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return await assignment_router.reassign_new_lead(lead_id)
