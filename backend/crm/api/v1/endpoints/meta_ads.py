"""Meta Ads (Campaign/AdSet/Ad) dashboard - reads meta_ads_daily_metrics and
meta_ads_entities, populated by the daily sync (crm/services/meta_ads_sync_service.py
via POST /v1/cron/sync-meta-ads, or the admin "Sync now" button). Admin-only
per SOP v3.1 §3, same as marketing.py.

Aggregation rules live in crm/services/meta_ads_queries.py."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from crm.core.state import db, get_current_user, utc_now
from crm.services import meta_ads_queries as q
from crm.services.lead_analytics_queries import created_range_filter
from crm.services.sales_dashboard_filters import DEALS_WON_STATUS_REGEX

router = APIRouter()

CRM_META_SOURCES = ("Facebook", "Instagram")
_LOCK_JOB = "meta_ads_sync"
_MAX_ROWS = 20000


def _require_admin(user: dict) -> None:
    role = (user.get("role") or "").strip().lower()
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


def _date_query(date_from: Optional[str], date_to: Optional[str]) -> dict:
    query: dict = {}
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        query["date"] = rng
    return query


def _range_or_400(date_from: Optional[str], date_to: Optional[str]) -> tuple:
    try:
        return q.parse_range(date_from, date_to)
    except q.RangeError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _is_sync_running() -> bool:
    lock = await db.cron_locks.find_one({"job": _LOCK_JOB, "expires_at": {"$gt": utc_now()}}, {"_id": 0, "job": 1})
    return bool(lock)


async def _kpis(match: dict) -> dict:
    rows = await db.meta_ads_daily_metrics.aggregate(q.totals_pipeline(match)).to_list(1)
    return q.with_ratios(rows[0] if rows else {})


async def _crm_by_campaign(d_from: str, d_to: str) -> dict:
    pipeline = q.crm_funnel_pipeline(
        created_range_filter(d_from, d_to), CRM_META_SOURCES, DEALS_WON_STATUS_REGEX, group_key="$campaign_id"
    )
    rows = await db.leads.aggregate(pipeline).to_list(_MAX_ROWS)
    return {str(r["_id"]): r for r in rows if r.get("_id")}


@router.get("/meta-ads/dashboard")
async def get_meta_ads_dashboard(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    project: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Legacy summary kept for compatibility. Shape mirrors marketing.py's
    get_marketing_dashboard() (by_project, entries, totals)."""
    _require_admin(current_user)
    query = _date_query(date_from, date_to)
    query["level"] = "campaign"
    if project:
        query["resolved_project"] = project
    rows = await db.meta_ads_daily_metrics.find(query, {"_id": 0}).to_list(10000)

    by_project: dict = {}
    for r in rows:
        proj = r.get("resolved_project") or "Unresolved"
        if proj not in by_project:
            by_project[proj] = {"project": proj, "total_spend": 0, "total_leads": 0, "total_impressions": 0, "total_clicks": 0}
        by_project[proj]["total_spend"] += r.get("spend", 0)
        by_project[proj]["total_leads"] += r.get("leads", 0)
        by_project[proj]["total_impressions"] += r.get("impressions", 0)
        by_project[proj]["total_clicks"] += r.get("clicks", 0)

    for p in by_project.values():
        p["cpl"] = round(p["total_spend"] / p["total_leads"], 2) if p["total_leads"] > 0 else 0

    return {
        "by_project": list(by_project.values()),
        "entries": rows,
        "total_spend": sum(r.get("spend", 0) for r in rows),
        "total_leads": sum(r.get("leads", 0) for r in rows),
        "total_impressions": sum(r.get("impressions", 0) for r in rows),
        "total_clicks": sum(r.get("clicks", 0) for r in rows),
    }


@router.get("/meta-ads/campaigns")
async def get_meta_ads_campaigns(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Flat campaign-level rows (legacy)."""
    _require_admin(current_user)
    query = _date_query(date_from, date_to)
    query["level"] = "campaign"
    rows = await db.meta_ads_daily_metrics.find(query, {"_id": 0}).sort("date", -1).to_list(10000)
    return rows


@router.get("/meta-ads/overview")
async def get_meta_ads_overview(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    projects: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """KPIs + previous-period comparison + zero-filled daily series.
    Campaign-level rows only (ad set / ad rows would triple-count)."""
    _require_admin(current_user)
    d_from, d_to = _range_or_400(date_from, date_to)
    p_from, p_to = q.previous_period(d_from, d_to)
    plist = q.parse_projects(projects)

    cur_match = q.daily_match("campaign", d_from, d_to, plist)
    prev_match = q.daily_match("campaign", p_from, p_to, plist)
    current = await _kpis(cur_match)
    previous = await _kpis(prev_match)
    series_rows = await db.meta_ads_daily_metrics.aggregate(q.daily_series_pipeline(cur_match)).to_list(_MAX_ROWS)
    return {
        "date_from": d_from,
        "date_to": d_to,
        "previous_from": p_from,
        "previous_to": p_to,
        "current": current,
        "previous": previous,
        "deltas": q.kpi_deltas(current, previous),
        "series": q.fill_series(series_rows, d_from, d_to),
    }


@router.get("/meta-ads/breakdown")
async def get_meta_ads_breakdown(
    level: str = "campaign",
    parent_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    projects: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "spend",
    sort_dir: str = "desc",
    include_idle: bool = False,
    limit: int = Query(100, ge=1, le=q.MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """Per-entity aggregates for one level. parent_id filters ad sets to a
    campaign (level=adset) or ads to an ad set (level=ad). Ratios are
    recomputed from sums; reach/frequency are deliberately not aggregated."""
    _require_admin(current_user)
    if level not in q.LEVELS:
        raise HTTPException(status_code=400, detail="level must be campaign, adset or ad")
    d_from, d_to = _range_or_400(date_from, date_to)
    plist = q.parse_projects(projects)

    parent_campaign = parent_id if level == "adset" else None
    parent_adset = parent_id if level == "ad" else None
    match = q.daily_match(
        level, d_from, d_to, plist, parent_campaign_id=parent_campaign, parent_adset_id=parent_adset
    )
    aggregated = await db.meta_ads_daily_metrics.aggregate(q.entity_pipeline(match)).to_list(_MAX_ROWS)

    ent_query: dict = {"level": level}
    if parent_campaign:
        ent_query["parent_campaign_id"] = parent_campaign
    if parent_adset:
        ent_query["parent_adset_id"] = parent_adset
    entity_docs = await db.meta_ads_entities.find(ent_query, {"_id": 0}).to_list(_MAX_ROWS)
    entities = {e["entity_id"]: e for e in entity_docs}

    rows = q.merge_entities(aggregated, entities, include_idle=include_idle, projects=plist)
    if level == "campaign":
        crm = await _crm_by_campaign(d_from, d_to)
        for r in rows:
            c = crm.get(r["entity_id"])
            r["crm_leads"] = int(c["leads"]) if c else None
            r["crm_site_visits"] = int(c["site_visits"]) if c else None
            r["crm_bookings"] = int(c["bookings"]) if c else None
    page, total = q.filter_sort_page(
        rows, status=status, search=search, sort_by=sort_by, sort_dir=sort_dir, limit=limit, offset=offset
    )
    return {
        "level": level,
        "date_from": d_from,
        "date_to": d_to,
        "total": total,
        "rows": page,
        "entity_data_available": bool(entities),
    }


@router.get("/meta-ads/entity/{level}/{entity_id}/daily")
async def get_meta_ads_entity_daily(
    level: str,
    entity_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Exact per-day rows for one entity - the only place reach/frequency are
    shown, because only a single day's value is exact."""
    _require_admin(current_user)
    if level not in q.LEVELS:
        raise HTTPException(status_code=400, detail="level must be campaign, adset or ad")
    d_from, d_to = _range_or_400(date_from, date_to)
    rows = (
        await db.meta_ads_daily_metrics.find(
            {"level": level, "entity_id": entity_id, "date": {"$gte": d_from, "$lte": d_to}},
            {"_id": 0, "actions": 0},
        )
        .sort("date", 1)
        .to_list(q.MAX_RANGE_DAYS + 1)
    )
    meta = await db.meta_ads_entities.find_one({"level": level, "entity_id": entity_id}, {"_id": 0})
    days = [
        {**q.with_ratios(r), "date": r["date"], "reach": r.get("reach", 0), "frequency": r.get("frequency", 0)}
        for r in rows
    ]
    return {"level": level, "entity_id": entity_id, "entity": meta, "days": days}


@router.get("/meta-ads/project-funnel")
async def get_meta_ads_project_funnel(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Meta spend per project next to the CRM cohort (Facebook/Instagram leads
    created in range -> site visits -> bookings), with cost per CRM lead /
    site visit / booking. Meta leads and CRM leads are different definitions
    and are returned separately."""
    _require_admin(current_user)
    d_from, d_to = _range_or_400(date_from, date_to)
    meta_rows = await db.meta_ads_daily_metrics.aggregate(
        q.project_pipeline(q.daily_match("campaign", d_from, d_to))
    ).to_list(_MAX_ROWS)
    crm_rows = await db.leads.aggregate(
        q.crm_funnel_pipeline(created_range_filter(d_from, d_to), CRM_META_SOURCES, DEALS_WON_STATUS_REGEX)
    ).to_list(_MAX_ROWS)
    funnel = q.assemble_funnel(meta_rows, crm_rows)
    return {
        "date_from": d_from,
        "date_to": d_to,
        **funnel,
        "attribution": q.attribution_summary(crm_rows),
    }


@router.post("/meta-ads/sync")
async def trigger_meta_ads_sync(background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """Admin "Sync now": runs the same sync as the cron in the background.
    The cron_locks mutex inside the service prevents overlapping runs."""
    _require_admin(current_user)
    from crm.core.state import META_ADS_ACCESS_TOKEN, META_ADS_ACCOUNT_IDS
    from crm.services.meta_ads_sync_service import sync_daily_meta_ads

    if not META_ADS_ACCESS_TOKEN or not META_ADS_ACCOUNT_IDS:
        return {"started": False, "reason": "not_configured"}
    if await _is_sync_running():
        return {"started": False, "reason": "already_running"}
    background_tasks.add_task(sync_daily_meta_ads)
    return {"started": True}


@router.get("/meta-ads/last-sync")
async def get_meta_ads_last_sync(current_user: dict = Depends(get_current_user)):
    """The latest sync run - what the "Last synced" indicator reads. `running`
    is true while a sync holds the lock."""
    _require_admin(current_user)
    latest = await db.meta_ads_sync_logs.find_one({}, {"_id": 0}, sort=[("started_at_dt", -1)])
    return {**(latest or {}), "running": await _is_sync_running()}
