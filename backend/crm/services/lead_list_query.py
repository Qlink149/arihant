"""Shared query-base resolution and filter composition for lead list and export."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Union

from crm.services.dashboard_scope import resolve_leads_base_filter, role_scope_filter
from crm.services.lead_analytics_queries import ORG_WIDE_DASHBOARD_METRICS, dormant_leads_query
from crm.services.lead_overview_service import (
    build_metric_context,
    enrich_follow_up_task_ids,
    metric_filter_for_key,
    resolve_metric_key,
)
from crm.services.lead_search import build_leads_list_query, merge_query


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
    """Parse YYYY-MM-DD into inclusive UTC ISO boundary for updated_at filtering."""
    return parse_created_date_boundary(value, end_of_day=end_of_day)


async def resolve_leads_list_query_base(
    current_user: dict,
    *,
    metric: Optional[str] = None,
    dormant: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Role scope, metric drill-down, and dormant filters shared by list and export."""
    query_base: Optional[Dict[str, Any]] = None

    if metric:
        metric = resolve_metric_key(metric)
        uid = current_user["id"]
        name = current_user["full_name"]
        is_admin_or_manager = current_user.get("role") in ("admin", "manager")
        if metric in ORG_WIDE_DASHBOARD_METRICS and is_admin_or_manager:
            ctx = build_metric_context({}, uid=uid, name=name, is_manager=False)
        else:
            base_filter, is_manager = await resolve_leads_base_filter(uid, name, current_user)
            ctx = build_metric_context(base_filter, uid=uid, name=name, is_manager=is_manager)
        if metric in ("follow_up_today", "missed_follow_up"):
            await enrich_follow_up_task_ids(ctx, base_filter=ctx.get("base_filter"))
        query_base = metric_filter_for_key(metric, ctx)
        if not query_base and metric not in ORG_WIDE_DASHBOARD_METRICS:
            query_base = ctx.get("base_filter")
    else:
        scope = role_scope_filter(current_user)
        if scope:
            query_base = scope

    if dormant:
        dormant_q = dormant_leads_query({})
        query_base = merge_query(query_base or {}, dormant_q)

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
    meta_qualified: Optional[bool] = None,
    site_visit_min: Optional[int] = None,
    site_visit_max: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the full MongoDB query for lead list/export endpoints."""
    created_at_from_iso = parse_created_date_boundary(created_from, end_of_day=False)
    created_at_to_iso = parse_created_date_boundary(created_to, end_of_day=True)
    updated_at_from_iso = parse_updated_date_boundary(updated_from, end_of_day=False)
    updated_at_to_iso = parse_updated_date_boundary(updated_to, end_of_day=True)

    days_cutoff_iso = None
    if days and not (created_at_from_iso or created_at_to_iso):
        days_cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    return build_leads_list_query(
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
        status=status,
        statuses=statuses,
        days_cutoff_iso=days_cutoff_iso,
        created_at_from_iso=created_at_from_iso,
        created_at_to_iso=created_at_to_iso,
        updated_at_from_iso=updated_at_from_iso,
        updated_at_to_iso=updated_at_to_iso,
        sources=sources,
        source=source,
        meta_qualified=meta_qualified,
        site_visit_min=site_visit_min,
        site_visit_max=site_visit_max,
    )
