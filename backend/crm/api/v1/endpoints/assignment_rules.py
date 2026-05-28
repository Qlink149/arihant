from fastapi import APIRouter, Depends

from crm.core.state import get_current_user
from crm.models.schemas.assignment_schemas import AssignmentRule
from crm.services import assignment_service

router = APIRouter()


@router.get("/assignment-rules")
async def get_assignment_rules(current_user: dict = Depends(get_current_user)):
    return await assignment_service.list_rules()


@router.post("/assignment-rules")
async def create_assignment_rule(rule: AssignmentRule, current_user: dict = Depends(get_current_user)):
    return await assignment_service.create_rule(rule)


@router.post("/leads/auto-assign")
async def auto_assign_lead(lead_id: str, current_user: dict = Depends(get_current_user)):
    return await assignment_service.auto_assign_lead(lead_id)
