"""Shared query-base resolution and filter composition for lead list and export."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Union

from crm.services.dashboard_scope import rep_lead_filter, resolve_leads_base_filter, role_scope_filter
from crm.services.lead_analytics_queries import (
    ORG_WIDE_DASHBOARD_METRICS,
    build_created_cohort_filter,
    build_dashboard_snapshot_query,
    updated_range_filter,
)
from crm.services.lead_overview_service import (
    build_metric_context,
    enrich_follow_up_task_ids,
    is_overview_drill_metric,
    metric_filter_for_key,
    resolve_metric_key,
)
from crm.services.lead_search import build_leads_list_query, merge_query
from crm.services.sales_dashboard_filters import SALES_DASHBOARD_METRICS, build_sales_metric_filter


def parse_multi_filter(value: Union[str, List[str], None]) -> List[str]:
    """Accept repeated query params or comma-separated single string."""
    if value is None:
        return []
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            parts.extend(parse_multi_filter(item))
        return parts
    raw = str(value).strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_created_date_boundary(value: Optional[str], *, end_of_day: bool = False) -> Optional[str]:
    """Parse YYYY-MM-DD into inclusive UTC ISO boundary for created_at filtering."""
    if not value or not str(value).strip():
        return None
    raw = str(value).strip()[:10]
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return None
    if end_of_day:
        dt = datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)
    else:
        dt = datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def parse_updated_date_boundary(value: Optional[str], *, end_of_day: bool = False) -> Optional[str]:
    """Parse YYYY-MM-DD as IST calendar day boundary, returned as UTC ISO (legacy callers)."""
    from crm.services.lead_analytics_queries import _parse_ymd_boundary

    dt = _parse_ymd_boundary(value, end_of_day=end_of_day)
    if not dt:
        return None
    return dt.isoformat().replace("+00:00", "Z")


def build_metric_snapshot_filter(
    current_user: dict,
    *,
    project: Optional[str] = None,
    projects: Optional[Sequence[str]] = None,
    use_rep_pipeline: bool = False,
) -> dict:
    """Role scope + optional project filter (matches dashboard operational snapshot)."""
    if use_rep_pipeline:
        scope = rep_lead_filter(current_user["id"], current_user.get("full_name") or "")
    else:
        scope = role_scope_filter(current_user)
    snapshot_q = build_dashboard_snapshot_query(project=project, projects=list(projects) if projects else None)
    return merge_query(scope or {}, snapshot_q or {})


def _list_role_scope(current_user: dict, *, use_rep_pipeline: bool) -> dict:
    if use_rep_pipeline:
        return rep_lead_filter(current_user["id"], current_user.get("full_name") or "")
    # Org-wide VC list: all authenticated users can see all leads
    return {}


async def resolve_leads_list_query_base(
    current_user: dict,
    *,
    metric: Optional[str] = None,
    dormant: Optional[bool] = None,
    snapshot_filter: Optional[Dict[str, Any]] = None,
    use_rep_pipeline: bool = False,
) -> Optional[Dict[str, Any]]:
    """Role scope, metric drill-down, and dormant filters shared by list and export."""
    query_base: Optional[Dict[str, Any]] = None

    if metric:
        metric = resolve_metric_key(metric)
        if metric in SALES_DASHBOARD_METRICS and not is_overview_drill_metric(metric):
            scope = _list_role_scope(current_user, use_rep_pipeline=use_rep_pipeline)
            sales_filt = build_sales_metric_filter(metric)
            query_base = merge_query(scope or {}, sales_filt)
        else:
            uid = current_user["id"]
            name = current_user["full_name"]
            is_admin_or_manager = current_user.get("role") in ("admin", "manager")
            if metric in ORG_WIDE_DASHBOARD_METRICS and is_admin_or_manager and not use_rep_pipeline:
                ctx = build_metric_context(snapshot_filter or {}, uid=uid, name=name, is_manager=False)
            elif snapshot_filter:
                ctx = build_metric_context(snapshot_filter, uid=uid, name=name, is_manager=False)
            else:
                base_filter, is_manager = await resolve_leads_base_filter(uid, name, current_user)
                ctx = build_metric_context(base_filter, uid=uid, name=name, is_manager=is_manager)
            if metric in ("follow_up_today", "missed_follow_up"):
                enrich_base = snapshot_filter if snapshot_filter is not None else ctx.get("base_filter")
                await enrich_follow_up_task_ids(ctx, base_filter=enrich_base)
            query_base = metric_filter_for_key(metric, ctx)
            if not query_base and metric not in ORG_WIDE_DASHBOARD_METRICS:
                query_base = ctx.get("base_filter")
    else:
        scope = _list_role_scope(current_user, use_rep_pipeline=use_rep_pipeline)
        if scope:
            query_base = scope

    # Dormant lead filter removed (change tracker #43) — ignore legacy ?dormant=1.
    _ = dormant

    return query_base


def compose_leads_list_query(
    query_base: Optional[Dict[str, Any]],
    *,
    project: Optional[str] = None,
    projects: Optional[Sequence[str]] = None,
    project_id: Optional[str] = None,
    temperature: Optional[str] = None,
    budget: Optional[str] = None,
    budgets: Optional[Sequence[str]] = None,
    location: Optional[str] = None,
    locations: Optional[Sequence[str]] = None,
    intent: Optional[str] = None,
    vip: Optional[bool] = None,
    re_enquiry: Optional[bool] = None,
    status: Optional[str] = None,
    statuses: Optional[Sequence[str]] = None,
    search: Optional[str] = None,
    days: Optional[int] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
    sources: Optional[Sequence[str]] = None,
    source: Optional[str] = None,
    sales_owners: Optional[Sequence[str]] = None,
    sales_owner: Optional[str] = None,
    meta_qualified: Optional[bool] = None,
    site_visit_min: Optional[int] = None,
    site_visit_max: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the full MongoDB query for lead list/export endpoints."""
    query = build_leads_list_query(
        query_base,
        temperature=temperature,
        search=search,
        project=project,
        projects=projects,
        project_id=project_id,
        budget=budget,
        budgets=budgets,
        location=location,
        locations=locations,
        intent=intent,
        vip=vip,
        re_enquiry=re_enquiry,
        status=status,
        statuses=statuses,
        sources=sources,
        source=source,
        sales_owners=sales_owners,
        sales_owner=sales_owner,
        meta_qualified=meta_qualified,
        site_visit_min=site_visit_min,
        site_visit_max=site_visit_max,
    )

    created_cohort = build_created_cohort_filter(
        days=days,
        created_from=created_from,
        created_to=created_to,
    )
    if created_cohort:
        query = merge_query(query, created_cohort)

    updated_cohort = updated_range_filter(updated_from, updated_to)
    if updated_cohort:
        query = merge_query(query, updated_cohort)
    return query
