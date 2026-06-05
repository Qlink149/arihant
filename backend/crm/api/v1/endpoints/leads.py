from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Response, UploadFile

from crm.core.state import get_current_user
from crm.models.schemas.lead_schemas import LeadCreate, LeadResponse, LeadUpdatePatch
from crm.services import lead_service
from crm.services.dashboard_scope import resolve_lead_or_403, resolve_leads_base_filter, role_scope_filter
from crm.services.lead_analytics_queries import (
    ORG_WIDE_DASHBOARD_METRICS,
    dormant_leads_query,
    fetch_lead_filter_options,
)
from crm.services.lead_overview_service import build_metric_context, metric_filter_for_key
from crm.services.lead_search import merge_query
from crm.services.ai_lead_regen import (
    ai_insights_stale,
    ai_refresh_in_progress,
    grok_keys_configured,
    schedule_lead_ai_refresh,
)

router = APIRouter()


@router.get("/leads/filter-options")
async def get_lead_filter_options(current_user: dict = Depends(get_current_user)):
    """Distinct project and location values from leads for Virtual Customer filters."""
    return await fetch_lead_filter_options(scope_filter=role_scope_filter(current_user))


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
    dormant: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
):
    query_base = None
    if metric:
        uid = current_user["id"]
        name = current_user["full_name"]
        is_admin_or_manager = current_user.get("role") in ("admin", "manager")
        if metric in ORG_WIDE_DASHBOARD_METRICS and is_admin_or_manager:
            ctx = build_metric_context({}, uid=uid, name=name, is_manager=False)
            query_base = metric_filter_for_key(metric, ctx)
        else:
            base_filter, is_manager = await resolve_leads_base_filter(uid, name, current_user)
            ctx = build_metric_context(base_filter, uid=uid, name=name, is_manager=is_manager)
            query_base = metric_filter_for_key(metric, ctx) or base_filter
    else:
        scope = role_scope_filter(current_user)
        if scope:
            query_base = scope

    if dormant:
        dormant_q = dormant_leads_query({})
        query_base = merge_query(query_base or {}, dormant_q)

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


@router.get("/leads/duplicates")
async def get_lead_duplicates(
    current_user: dict = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """Phone-number duplicate groups (scoped); replaces client-side 5k lead scan."""
    scope = role_scope_filter(current_user)
    query_base = scope if scope else {}
    groups, total_groups = await lead_service.find_duplicate_lead_groups(
        query_base, skip=skip, limit=limit
    )
    return {
        "groups": groups,
        "total_groups": total_groups,
        "skip": skip,
        "limit": limit,
    }


@router.get("/leads/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    await resolve_lead_or_403(lead_id, current_user)
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
    await resolve_lead_or_403(lead_id, current_user)
    return await lead_service.update_lead(lead_id, lead_update, current_user)


@router.post("/leads/upload-csv")
async def upload_leads_csv(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    replace_all: bool = False,
    confirm_replace: Optional[str] = Query(None),
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="CSV import requires admin role")
    if replace_all and confirm_replace != "CONFIRM_REPLACE_ALL":
        raise HTTPException(
            status_code=400,
            detail="To replace all leads, pass confirm_replace=CONFIRM_REPLACE_ALL",
        )
    return await lead_service.import_csv(
        file, current_user, replace_all=replace_all, confirm_replace=confirm_replace
    )


@router.post("/leads/{lead_id}/merge/{duplicate_id}")
async def merge_leads(lead_id: str, duplicate_id: str, current_user: dict = Depends(get_current_user)):
    await resolve_lead_or_403(lead_id, current_user)
    await resolve_lead_or_403(duplicate_id, current_user)
    return await lead_service.merge_leads(lead_id, duplicate_id, current_user)
