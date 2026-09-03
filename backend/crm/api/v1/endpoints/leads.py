from typing import List, Optional
import re
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel, Field

from crm.core.state import db, get_current_user, iso_utc_now, resolve_user_id_by_full_name
from crm.models.schemas.lead_schemas import LeadCreate, LeadResponse, LeadUpdatePatch
from crm.services import lead_service
from crm.services.lead_service import normalize_lead_for_response
from crm.utils.helpers import coerce_datetime, normalize_phone, utc_now
from crm.services.dashboard_scope import resolve_lead_or_403, resolve_lead_view_or_403, role_scope_filter, user_owns_lead
from crm.services.lead_analytics_queries import fetch_lead_filter_options
from crm.services.lead_search import build_exact_phone_lookup_queries, case_insensitive_regex_filter
from crm.services.lead_events import log_lead_event
from crm.services.lead_transfer_service import assign_lead_ownership
from crm.services.lead_view_grants import DEFAULT_GRANT_MINUTES, upsert_view_grant
from crm.services.notification_service import create_notification
from crm.services.lead_export_service import (
    assert_admin,
    create_export_job,
    download_export_file,
    get_export_field_catalog,
    get_export_job,
    run_export_job,
)
from crm.services.lead_filter_views_service import (
    LeadFilterViewCreate,
    LeadFilterViewUpdate,
    create_filter_view,
    delete_filter_view,
    list_filter_views,
    update_filter_view,
)
from crm.services.lead_list_query import (
    build_metric_snapshot_filter,
    parse_multi_filter,
    resolve_leads_list_query_base,
)
from crm.services.ai_lead_regen import (
    ai_insights_stale,
    ai_refresh_in_progress,
    grok_keys_configured,
    schedule_lead_ai_refresh,
)

router = APIRouter()


class LeadExportRequest(BaseModel):
    fields: List[str] = Field(..., min_length=1)


class BulkLeadUpdateRequest(BaseModel):
    lead_ids: List[str] = Field(..., min_length=1, max_length=200)
    assigned_user_id: Optional[str] = None
    to_rep: Optional[str] = None
    lead_status: Optional[str] = None
    lost_reason: Optional[str] = None


def _http_exc_reason(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, str):
        return detail
    return str(detail)


def _list_filter_params(
    *,
    project: Optional[str] = None,
    projects: Optional[List[str]] = None,
    project_id: Optional[str] = None,
    temperature: Optional[str] = None,
    budget: Optional[str] = None,
    budgets: Optional[List[str]] = None,
    location: Optional[str] = None,
    locations: Optional[List[str]] = None,
    sources: Optional[List[str]] = None,
    source: Optional[str] = None,
    sales_owners: Optional[List[str]] = None,
    sales_owner: Optional[str] = None,
    intent: Optional[str] = None,
    vip: Optional[bool] = None,
    re_enquiry: Optional[bool] = None,
    status: Optional[str] = None,
    statuses: Optional[List[str]] = None,
    search: Optional[str] = None,
    days: Optional[int] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
    meta_qualified: Optional[bool] = None,
    site_visit_min: Optional[int] = None,
    site_visit_max: Optional[int] = None,
    metric: Optional[str] = None,
    dormant: Optional[bool] = None,
    mine: Optional[bool] = None,
) -> dict:
    params = {
        "project": project,
        "projects": projects,
        "project_id": project_id,
        "temperature": temperature,
        "budget": budget,
        "budgets": budgets,
        "location": location,
        "locations": locations,
        "sources": sources,
        "source": source,
        "sales_owners": sales_owners,
        "sales_owner": sales_owner,
        "intent": intent,
        "vip": vip,
        "re_enquiry": re_enquiry,
        "status": status,
        "statuses": statuses,
        "search": search,
        "days": days,
        "created_from": created_from,
        "created_to": created_to,
        "updated_from": updated_from,
        "updated_to": updated_to,
        "meta_qualified": meta_qualified,
        "site_visit_min": site_visit_min,
        "site_visit_max": site_visit_max,
        "metric": metric,
        "dormant": dormant,
        "mine": mine,
    }
    return {k: v for k, v in params.items() if v is not None and v != []}


def _normalize_list_filters(
    *,
    project: Optional[str] = None,
    projects: Optional[List[str]] = None,
    budget: Optional[str] = None,
    budgets: Optional[List[str]] = None,
    location: Optional[str] = None,
    locations: Optional[List[str]] = None,
    status: Optional[str] = None,
    statuses: Optional[List[str]] = None,
    sources: Optional[List[str]] = None,
    source: Optional[str] = None,
    sales_owners: Optional[List[str]] = None,
    sales_owner: Optional[str] = None,
) -> dict:
    """Merge legacy single-value and multi-value query params."""
    return {
        "projects": parse_multi_filter(projects) or parse_multi_filter(project),
        "budgets": parse_multi_filter(budgets) or parse_multi_filter(budget),
        "locations": parse_multi_filter(locations) or parse_multi_filter(location),
        "statuses": parse_multi_filter(statuses) or parse_multi_filter(status),
        "sources": parse_multi_filter(sources) or parse_multi_filter(source),
        "sales_owners": parse_multi_filter(sales_owners) or parse_multi_filter(sales_owner),
    }


@router.get("/leads/filter-options")
async def get_lead_filter_options(
    response: Response,
    current_user: dict = Depends(get_current_user),
):
    """Distinct project and location values from leads for Virtual Customer filters."""
    response.headers["Cache-Control"] = "private, max-age=300"
    return await fetch_lead_filter_options(scope_filter={})


@router.get("/leads/filter-views")
async def get_lead_filter_views(current_user: dict = Depends(get_current_user)):
    """List saved filter views for the current user."""
    return await list_filter_views(current_user["id"])


@router.post("/leads/filter-views")
async def post_lead_filter_view(
    body: LeadFilterViewCreate,
    current_user: dict = Depends(get_current_user),
):
    """Save a named filter view for Virtual Customer."""
    return await create_filter_view(current_user["id"], body)


@router.put("/leads/filter-views/{view_id}")
async def put_lead_filter_view(
    view_id: str,
    body: LeadFilterViewUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update a saved filter view."""
    return await update_filter_view(current_user["id"], view_id, body)


@router.delete("/leads/filter-views/{view_id}")
async def delete_lead_filter_view(
    view_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a saved filter view."""
    await delete_filter_view(current_user["id"], view_id)
    return {"message": "Filter view deleted"}


@router.post("/leads", response_model=LeadResponse)
async def create_lead(lead: LeadCreate, current_user: dict = Depends(get_current_user)):
    return await lead_service.create_lead(lead, current_user)


@router.get("/leads", response_model=List[LeadResponse])
async def get_leads(
    response: Response,
    current_user: dict = Depends(get_current_user),
    project: Optional[str] = None,
    projects: Optional[List[str]] = Query(None),
    project_id: Optional[str] = None,
    temperature: Optional[str] = None,
    budget: Optional[str] = None,
    budgets: Optional[List[str]] = Query(None),
    location: Optional[str] = None,
    locations: Optional[List[str]] = Query(None),
    sources: Optional[List[str]] = Query(None),
    source: Optional[str] = None,
    sales_owners: Optional[List[str]] = Query(None),
    sales_owner: Optional[str] = None,
    intent: Optional[str] = None,
    vip: Optional[bool] = None,
    re_enquiry: Optional[bool] = None,
    status: Optional[str] = None,
    statuses: Optional[List[str]] = Query(None),
    search: Optional[str] = None,
    days: Optional[int] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
    meta_qualified: Optional[bool] = None,
    site_visit_min: Optional[int] = None,
    site_visit_max: Optional[int] = None,
    metric: Optional[str] = None,
    dormant: Optional[bool] = None,
    mine: Optional[bool] = Query(None, description="Scope to the user's assigned pipeline (My Dashboard drill-down)"),
    skip: int = 0,
    limit: int = 100,
    include_total: bool = Query(True),
):
    multi = _normalize_list_filters(
        project=project,
        projects=projects,
        budget=budget,
        budgets=budgets,
        location=location,
        locations=locations,
        status=status,
        statuses=statuses,
        sources=sources,
        source=source,
        sales_owners=sales_owners,
        sales_owner=sales_owner,
    )
    snapshot_filter = None
    use_rep_pipeline = bool(mine)
    if metric:
        snapshot_filter = build_metric_snapshot_filter(
            current_user,
            project=project,
            projects=multi["projects"] or None,
            use_rep_pipeline=use_rep_pipeline,
        )
    query_base = await resolve_leads_list_query_base(
        current_user,
        metric=metric,
        dormant=dormant,
        snapshot_filter=snapshot_filter,
        use_rep_pipeline=use_rep_pipeline,
    )

    leads, total = await lead_service.list_leads(
        project=project,
        projects=multi["projects"] or None,
        project_id=project_id,
        temperature=temperature,
        budget=budget,
        budgets=multi["budgets"] or None,
        location=location,
        locations=multi["locations"] or None,
        sources=multi["sources"] or None,
        source=source,
        sales_owners=multi["sales_owners"] or None,
        sales_owner=sales_owner,
        intent=intent,
        vip=vip,
        re_enquiry=re_enquiry,
        status=status,
        statuses=multi["statuses"] or None,
        search=search,
        days=days,
        created_from=created_from,
        created_to=created_to,
        updated_from=updated_from,
        updated_to=updated_to,
        meta_qualified=meta_qualified,
        site_visit_min=site_visit_min,
        site_visit_max=site_visit_max,
        skip=skip,
        limit=min(limit, 100),
        query_base=query_base,
        include_total=include_total if skip == 0 else False,
    )
    if total > 0 or skip == 0:
        response.headers["X-Total-Count"] = str(total)
    return leads


@router.get("/leads/export/fields")
async def get_leads_export_fields(current_user: dict = Depends(get_current_user)):
    assert_admin(current_user)
    return {"fields": get_export_field_catalog()}


@router.post("/leads/export")
async def start_leads_export(
    body: LeadExportRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    project: Optional[str] = None,
    projects: Optional[List[str]] = Query(None),
    project_id: Optional[str] = None,
    temperature: Optional[str] = None,
    budget: Optional[str] = None,
    budgets: Optional[List[str]] = Query(None),
    location: Optional[str] = None,
    locations: Optional[List[str]] = Query(None),
    sources: Optional[List[str]] = Query(None),
    source: Optional[str] = None,
    sales_owners: Optional[List[str]] = Query(None),
    sales_owner: Optional[str] = None,
    intent: Optional[str] = None,
    vip: Optional[bool] = None,
    re_enquiry: Optional[bool] = None,
    status: Optional[str] = None,
    statuses: Optional[List[str]] = Query(None),
    search: Optional[str] = None,
    days: Optional[int] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
    meta_qualified: Optional[bool] = None,
    site_visit_min: Optional[int] = None,
    site_visit_max: Optional[int] = None,
    metric: Optional[str] = None,
    dormant: Optional[bool] = None,
    mine: Optional[bool] = None,
):
    multi = _normalize_list_filters(
        project=project,
        projects=projects,
        budget=budget,
        budgets=budgets,
        location=location,
        locations=locations,
        status=status,
        statuses=statuses,
        sources=sources,
        source=source,
        sales_owners=sales_owners,
        sales_owner=sales_owner,
    )
    filters = _list_filter_params(
        project=project,
        projects=multi["projects"] or None,
        project_id=project_id,
        temperature=temperature,
        budget=budget,
        budgets=multi["budgets"] or None,
        location=location,
        locations=multi["locations"] or None,
        sources=multi["sources"] or None,
        source=source,
        sales_owners=multi["sales_owners"] or None,
        sales_owner=sales_owner,
        intent=intent,
        vip=vip,
        re_enquiry=re_enquiry,
        status=status,
        statuses=multi["statuses"] or None,
        search=search,
        days=days,
        created_from=created_from,
        created_to=created_to,
        updated_from=updated_from,
        updated_to=updated_to,
        meta_qualified=meta_qualified,
        site_visit_min=site_visit_min,
        site_visit_max=site_visit_max,
        metric=metric,
        dormant=dormant,
        mine=mine,
    )
    job = await create_export_job(current_user, body.fields, filters)
    background_tasks.add_task(run_export_job, job["id"])
    return job


@router.get("/leads/export/jobs/{job_id}")
async def poll_leads_export_job(job_id: str, current_user: dict = Depends(get_current_user)):
    return await get_export_job(job_id, current_user)


@router.get("/leads/export/jobs/{job_id}/download")
async def download_leads_export(job_id: str, current_user: dict = Depends(get_current_user)):
    content, filename = await download_export_file(job_id, current_user)
    return FastAPIResponse(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


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


@router.get("/leads/exact-lookup", response_model=LeadResponse)
async def exact_lookup_lead(
    phone: Optional[str] = None,
    email: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """
    Exact-match lookup for a single lead by full phone/email.

    MUST be registered before /leads/{lead_id} so "exact-lookup" is not captured as an id.

    - Admin/manager: org-wide lookup (no grant needed).
    - Rep: only full identifiers are accepted; if matched lead is outside rep scope,
      a temporary view-only grant is created so GET /leads/{id} works for a short window.

    Phone match order: exact typed phone/work_phone, then normalized last-10 fallback.
    """
    if (phone and str(phone).strip()) and (email and str(email).strip()):
        raise HTTPException(status_code=400, detail="Provide only one of phone or email")
    if not ((phone and str(phone).strip()) or (email and str(email).strip())):
        raise HTTPException(status_code=400, detail="Provide phone or email")

    lead = None
    lookup_type = None
    lookup_value = None

    if phone and str(phone).strip():
        lookup_type = "phone"
        raw_phone = str(phone).strip()
        digits = re.sub(r"\D", "", raw_phone)
        normalized = normalize_phone(raw_phone)
        # Full identifier: 10–15 digits (local 10 or with country code). Partials stay on list search.
        if len(digits) < 10 or len(digits) > 15:
            raise HTTPException(status_code=400, detail="Phone must be a full number (10–15 digits)")
        lookup_value = normalized if len(normalized) == 10 else digits
        for query in build_exact_phone_lookup_queries(raw_phone):
            lead = await db.leads.find_one(query, {"_id": 0})
            if lead:
                break
    else:
        lookup_type = "email"
        raw = str(email).strip()
        if " " in raw or "@" not in raw or len(raw) < 5:
            raise HTTPException(status_code=400, detail="Email must be a full address")
        lookup_value = raw
        lead = await db.leads.find_one(case_insensitive_regex_filter("email", raw, exact=True), {"_id": 0})

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Rep: if lead is outside ownership/task rules, mint a short-lived view grant.
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "manager"):
        if not user_owns_lead(lead, current_user):
            # task-assignee access already works via existing ACL and doesn't require a grant
            await upsert_view_grant(
                lead_id=lead["id"],
                user_id=current_user.get("id") or "",
                minutes=DEFAULT_GRANT_MINUTES,
                reason="exact_lookup",
                lookup_type=lookup_type,
                lookup_value=lookup_value,
            )
            await log_lead_event(
                "lead_exact_lookup_granted",
                lead_id=lead.get("id"),
                actor_user_id=current_user.get("id"),
                actor_name=current_user.get("full_name"),
                payload={"lookup_type": lookup_type, "grant_minutes": DEFAULT_GRANT_MINUTES},
            )

    if isinstance(lead.get("created_at"), str):
        lead["created_at"] = coerce_datetime(lead.get("created_at")) or utc_now()
    if isinstance(lead.get("updated_at"), str):
        lead["updated_at"] = coerce_datetime(lead.get("updated_at")) or utc_now()
    lead = normalize_lead_for_response(lead)
    return LeadResponse(**lead)


@router.get("/leads/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    lead = await resolve_lead_view_or_403(lead_id, current_user)
    if isinstance(lead.get("created_at"), str):
        lead["created_at"] = coerce_datetime(lead.get("created_at")) or utc_now()
    if isinstance(lead.get("updated_at"), str):
        lead["updated_at"] = coerce_datetime(lead.get("updated_at")) or utc_now()
    lead = normalize_lead_for_response(lead)
    cfg = grok_keys_configured()
    stale = ai_insights_stale(lead)
    lead["ai_configured"] = cfg
    lead["ai_stale"] = stale
    lead["ai_generation_pending"] = bool(cfg and (stale or ai_refresh_in_progress(lead_id)))
    if cfg and stale:
        schedule_lead_ai_refresh(lead_id, background_tasks)
    return LeadResponse(**lead)


@router.post("/leads/{lead_id}/grant", status_code=200)
async def mint_search_grant(lead_id: str, current_user: dict = Depends(get_current_user)):
    """
    Mint a temporary 10-minute edit grant for the current user on a specific lead.
    Called by the frontend when a rep navigates to any lead via the search bar
    (regex name search or exact phone/email lookup). Admins/managers skip — they
    always have full access. Audited so you can see who accessed what.
    """
    role = (current_user.get("role") or "").lower()
    if role in ("admin", "manager"):
        return {"granted": False, "reason": "admin/manager always have access"}

    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0, "id": 1})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    await upsert_view_grant(
        lead_id=lead_id,
        user_id=current_user.get("id") or "",
        minutes=DEFAULT_GRANT_MINUTES,
        reason="search_navigation",
    )
    await log_lead_event(
        "lead_search_grant",
        lead_id=lead_id,
        actor_user_id=current_user.get("id"),
        actor_name=current_user.get("full_name"),
        payload={"grant_minutes": DEFAULT_GRANT_MINUTES, "reason": "search_navigation"},
    )
    return {"granted": True, "minutes": DEFAULT_GRANT_MINUTES}


@router.post("/leads/bulk-update")
async def bulk_update_leads(
    req: BulkLeadUpdateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """Bulk assign and/or status-change leads (admin/manager only). Partial success."""
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Only admin or manager can bulk-update leads")

    lead_ids = list(dict.fromkeys([lid for lid in req.lead_ids if (lid or "").strip()]))
    if not lead_ids:
        raise HTTPException(status_code=400, detail="lead_ids is required")
    if len(lead_ids) > 200:
        raise HTTPException(status_code=400, detail="Maximum 200 leads per bulk update")

    want_assign = bool((req.assigned_user_id or "").strip() or (req.to_rep or "").strip())
    want_status = bool((req.lead_status or "").strip())
    if not want_assign and not want_status:
        raise HTTPException(
            status_code=400,
            detail="Provide assigned_user_id/to_rep and/or lead_status",
        )

    to_rep = (req.to_rep or "").strip() or None
    to_user_id = (req.assigned_user_id or "").strip() or None
    if want_assign:
        if to_user_id and not to_rep:
            user_doc = await db.users.find_one(
                {"id": to_user_id}, {"_id": 0, "full_name": 1}
            )
            if not user_doc or not (user_doc.get("full_name") or "").strip():
                raise HTTPException(status_code=400, detail="assigned_user_id not found")
            to_rep = user_doc["full_name"].strip()
        if to_rep and not to_user_id:
            to_user_id = await resolve_user_id_by_full_name(to_rep)
        if not to_rep or not to_user_id:
            raise HTTPException(
                status_code=400,
                detail="assigned_user_id or to_rep must resolve to a valid user",
            )

    updated: List[str] = []
    failed: List[dict] = []

    for lead_id in lead_ids:
        try:
            lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
            if not lead:
                failed.append({"id": lead_id, "reason": "Lead not found"})
                continue

            if want_assign:
                known_owner = (lead.get("assigned_user_id") or "").strip() or None
                await assign_lead_ownership(
                    lead=lead,
                    to_rep=to_rep,
                    to_user_id=to_user_id,
                    current_user=current_user,
                    notes=None,
                    expected_from_user_id=known_owner,
                )

            if want_status:
                patch_kwargs = {"lead_status": req.lead_status.strip()}
                if req.lost_reason is not None:
                    patch_kwargs["lost_reason"] = req.lost_reason
                await lead_service.update_lead(
                    lead_id,
                    LeadUpdatePatch(**patch_kwargs),
                    current_user,
                )
                schedule_lead_ai_refresh(lead_id, background_tasks)

            updated.append(lead_id)
        except HTTPException as exc:
            failed.append({"id": lead_id, "reason": _http_exc_reason(exc)})
        except Exception as exc:  # noqa: BLE001 — partial success must not abort batch
            failed.append({"id": lead_id, "reason": str(exc) or "Unexpected error"})

    return {"updated": updated, "failed": failed}


@router.post("/leads/{lead_id}/nudge")
async def nudge_lead(lead_id: str, current_user: dict = Depends(get_current_user)):
    """Admin/manager reminder notification to the lead's assignee."""
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Only admin or manager can nudge")

    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    assignee_id = (lead.get("assigned_user_id") or "").strip()
    assignee_name = (
        lead.get("assigned_to_name") or lead.get("assigned_to") or lead.get("presales_agent") or ""
    ).strip()
    if not assignee_id and assignee_name:
        assignee_id = (await resolve_user_id_by_full_name(assignee_name) or "").strip()
    if not assignee_id:
        raise HTTPException(status_code=400, detail="Lead has no assignee to nudge")

    recent = await db.notifications.find_one(
        {
            "lead_id": lead_id,
            "notification_type": "admin_nudge",
            "recipient_user_id": assignee_id,
            "created_at_dt": {"$gte": utc_now() - timedelta(seconds=60)},
        },
        {"_id": 0, "id": 1},
    )
    if recent:
        return {"ok": True, "deduped": True, "message": "Nudge already sent recently"}

    lead_name = (
        f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        or lead.get("name")
        or "Lead"
    )
    admin_name = current_user.get("full_name") or "Admin"
    await create_notification(
        recipient_user_id=assignee_id,
        recipient_name=assignee_name,
        title="Nudge by Admin",
        message=f"{admin_name} nudged you on {lead_name}",
        notification_type="admin_nudge",
        lead_id=lead_id,
        lead_name=lead_name,
        severity="high",
        urgency="action_needed",
    )

    now_dt = utc_now()
    now_iso = iso_utc_now()
    await db.leads.update_one(
        {"id": lead_id},
        {
            "$push": {
                "context_updates": {
                    "type": "nudge",
                    "timestamp": now_iso,
                    "timestamp_dt": now_dt,
                    "description": "Nudge by Admin",
                    "agent": admin_name,
                    "actor_user_id": current_user.get("id"),
                    "actor_name": admin_name,
                }
            },
            "$set": {"updated_at": now_iso, "updated_at_dt": now_dt},
        },
    )
    return {"ok": True, "deduped": False}


@router.put("/leads/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: str,
    lead_update: LeadUpdatePatch,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    await resolve_lead_or_403(lead_id, current_user)
    patch = lead_update.model_dump(exclude_unset=True)
    result = await lead_service.update_lead(lead_id, lead_update, current_user)
    # Any lead overview / status edit appends timeline "updated" — refresh AI
    if patch:
        schedule_lead_ai_refresh(lead_id, background_tasks)
    return result


@router.post("/leads/upload-csv")
async def upload_leads_csv(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="CSV import requires admin role")
    return await lead_service.import_csv(file, current_user)


@router.post("/leads/{lead_id}/merge/{duplicate_id}")
async def merge_leads(lead_id: str, duplicate_id: str, current_user: dict = Depends(get_current_user)):
    await resolve_lead_or_403(lead_id, current_user)
    await resolve_lead_or_403(duplicate_id, current_user)
    return await lead_service.merge_leads(lead_id, duplicate_id, current_user)
