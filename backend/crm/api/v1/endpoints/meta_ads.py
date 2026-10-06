"""Meta Ads (Campaign/AdSet/Ad) dashboard - reads meta_ads_daily_metrics,
populated by the daily sync (crm/services/meta_ads_sync_service.py via
POST /v1/cron/sync-meta-ads). Admin-only per SOP v3.1 §3, same as marketing.py."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from crm.core.state import db, get_current_user

router = APIRouter()


def _require_admin(user: dict) -> None:
    role = (user.get("role") or "").strip().lower()
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


def _date_query(date_from: Optional[str], date_to: Optional[str]) -> dict:
    q: dict = {}
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["date"] = rng
    return q


@router.get("/meta-ads/dashboard")
async def get_meta_ads_dashboard(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    project: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Shape mirrors marketing.py's get_marketing_dashboard() (by_project,
    entries, totals) so the frontend reuses the same chart/table components."""
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
    """Flat campaign-level rows for the table/export."""
    _require_admin(current_user)
    query = _date_query(date_from, date_to)
    query["level"] = "campaign"
    rows = await db.meta_ads_daily_metrics.find(query, {"_id": 0}).sort("date", -1).to_list(10000)
    return rows


@router.get("/meta-ads/last-sync")
async def get_meta_ads_last_sync(current_user: dict = Depends(get_current_user)):
    """The latest sync run - what the "Last synced" indicator reads."""
    _require_admin(current_user)
    latest = await db.meta_ads_sync_logs.find_one({}, {"_id": 0}, sort=[("started_at_dt", -1)])
    return latest or {}
