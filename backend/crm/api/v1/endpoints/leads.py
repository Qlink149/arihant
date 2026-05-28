from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Response, UploadFile

from crm.core.state import get_current_user
from crm.models.schemas.lead_schemas import LeadCreate, LeadResponse, LeadUpdatePatch
from crm.services import lead_service
from crm.services.dashboard_scope import resolve_leads_base_filter
from crm.services.lead_overview_service import build_metric_context, metric_filter_for_key
from crm.services.ai_lead_regen import (
    ai_insights_stale,
    ai_refresh_in_progress,
    grok_keys_configured,
    schedule_lead_ai_refresh,
)

router = APIRouter()


@router.post("/leads", response_model=LeadResponse)
async def create_lead(lead: LeadCreate, current_user: dict = Depends(get_current_user)):
    return await lead_service.create_lead(lead, current_user)


@router.get("/leads", response_model=List[LeadResponse])
async def get_leads(
    response: Response,
    current_user: dict = Depends(get_current_user),
    project: Optional[str] = None,
    project_id: Optional[str] = None,
    temperature: Optional[str] = None,
    budget: Optional[str] = None,
    location: Optional[str] = None,
    intent: Optional[str] = None,
    vip: Optional[bool] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    days: Optional[int] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    metric: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
):
    query_base = None
    if metric:
        uid = current_user["id"]
        name = current_user["full_name"]
        base_filter, is_manager = await resolve_leads_base_filter(uid, name, current_user)
        ctx = build_metric_context(base_filter, uid=uid, name=name, is_manager=is_manager)
        query_base = metric_filter_for_key(metric, ctx) or base_filter

    leads, total = await lead_service.list_leads(
        project=project,
        project_id=project_id,
        temperature=temperature,
        budget=budget,
        location=location,
        intent=intent,
        vip=vip,
        status=status,
        search=search,
        days=days,
        created_from=created_from,
        created_to=created_to,
        skip=skip,
        limit=limit,
        query_base=query_base,
    )
    response.headers["X-Total-Count"] = str(total)
    return leads


@router.get("/leads/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    lead = await lead_service.get_lead_by_id(lead_id)
    cfg = grok_keys_configured()
    stale = ai_insights_stale(lead)
    lead["ai_configured"] = cfg
    lead["ai_stale"] = stale
    lead["ai_generation_pending"] = bool(cfg and (stale or ai_refresh_in_progress(lead_id)))
    if cfg and stale:
        schedule_lead_ai_refresh(lead_id, background_tasks)
    return LeadResponse(**lead)


@router.put("/leads/{lead_id}", response_model=LeadResponse)
async def update_lead(lead_id: str, lead_update: LeadUpdatePatch, current_user: dict = Depends(get_current_user)):
    return await lead_service.update_lead(lead_id, lead_update, current_user)


@router.post("/leads/upload-csv")
async def upload_leads_csv(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    replace_all: bool = False,
):
    return await lead_service.import_csv(file, current_user, replace_all=replace_all)


@router.post("/leads/{lead_id}/merge/{duplicate_id}")
async def merge_leads(lead_id: str, duplicate_id: str, current_user: dict = Depends(get_current_user)):
    return await lead_service.merge_leads(lead_id, duplicate_id, current_user)
