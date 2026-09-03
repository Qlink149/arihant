"""#53/#54: Append-only site visit completion events + analytics.

Reference fields on the lead document (`visit_completed_at_dt`, `site_visit_count`)
are first-stamp / running-total only and get overwritten on later transitions.
This collection is append-only history: one event per transition into
"Visit Completed", surviving later status changes, used to build a permanent
report of visit totals by project / date range / sales owner.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from crm.core.state import db
from crm.services.lead_project_fields import coalesce_projects
from crm.utils.helpers import iso_utc_now

IST = ZoneInfo("Asia/Kolkata")


def _lead_name(lead: Dict[str, Any]) -> str:
    name = f"{(lead.get('first_name') or '').strip()} {(lead.get('last_name') or '').strip()}".strip()
    return name or (lead.get("name") or "Lead")


async def record_site_visit_event(
    lead_id: str,
    lead: Dict[str, Any],
    *,
    actor: Dict[str, Any],
    completed_at_dt: datetime,
) -> str:
    """Append one site-visit-completion event. Never raises (best-effort logging)."""
    event_id = str(uuid.uuid4())
    try:
        projects = coalesce_projects(lead) or ([lead.get("project")] if lead.get("project") else [])
        event = {
            "id": event_id,
            "lead_id": lead_id,
            "completed_at_dt": completed_at_dt,
            "completed_at": iso_utc_now(),
            "project": (lead.get("project") or (projects[0] if projects else None)),
            "projects": projects,
            "assigned_user_id": lead.get("assigned_user_id"),
            "assigned_to_name": lead.get("assigned_to_name") or lead.get("assigned_to"),
            "actor_user_id": actor.get("id"),
            "actor_name": actor.get("full_name"),
            "lead_name": _lead_name(lead),
            "phone": lead.get("phone"),
        }
        await db.site_visit_events.insert_one(event)
    except Exception:  # noqa: BLE001 — logging must never block the status update
        pass
    return event_id


def _ist_period_bounds(period: str, now_dt: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) for preset IST periods: week | month | quarter."""
    now = now_dt or datetime.now(timezone.utc)
    ist_now = now.astimezone(IST)
    today = datetime(ist_now.year, ist_now.month, ist_now.day, tzinfo=IST)

    if period == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)
    elif period == "quarter":
        q_start_month = ((ist_now.month - 1) // 3) * 3 + 1
        start = datetime(ist_now.year, q_start_month, 1, tzinfo=IST)
        end_month = q_start_month + 3
        end_year = ist_now.year
        if end_month > 12:
            end_month -= 12
            end_year += 1
        end = datetime(end_year, end_month, 1, tzinfo=IST)
    else:  # "month" default
        start = datetime(ist_now.year, ist_now.month, 1, tzinfo=IST)
        next_month = ist_now.month + 1
        next_year = ist_now.year
        if next_month > 12:
            next_month = 1
            next_year += 1
        end = datetime(next_year, next_month, 1, tzinfo=IST)

    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def resolve_report_window(
    *,
    preset: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    now_dt: Optional[datetime] = None,
) -> Dict[str, Optional[datetime]]:
    """Resolve a `{from, to}` UTC datetime window from a preset or explicit range."""
    if preset in ("week", "month", "quarter"):
        start, end = _ist_period_bounds(preset, now_dt)
        return {"from": start, "to": end}

    result: Dict[str, Optional[datetime]] = {"from": None, "to": None}
    if date_from:
        try:
            d = datetime.fromisoformat(date_from[:10]).replace(tzinfo=IST)
            result["from"] = d.astimezone(timezone.utc)
        except ValueError:
            pass
    if date_to:
        try:
            d = datetime.fromisoformat(date_to[:10]).replace(tzinfo=IST) + timedelta(days=1)
            result["to"] = d.astimezone(timezone.utc)
        except ValueError:
            pass
    return result


def build_site_visit_report_filter(
    *,
    window: Dict[str, Optional[datetime]],
    sales_owner_id: Optional[str] = None,
) -> Dict[str, Any]:
    filt: Dict[str, Any] = {}
    range_clause: Dict[str, Any] = {}
    if window.get("from"):
        range_clause["$gte"] = window["from"]
    if window.get("to"):
        range_clause["$lt"] = window["to"]
    if range_clause:
        filt["completed_at_dt"] = range_clause
    if sales_owner_id:
        filt["assigned_user_id"] = sales_owner_id
    return filt


async def build_site_visit_report(
    *,
    window: Dict[str, Optional[datetime]],
    sales_owner_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Totals by project for the given window/owner, plus overall total."""
    filt = build_site_visit_report_filter(window=window, sales_owner_id=sales_owner_id)
    pipeline: List[Dict[str, Any]] = [
        {"$match": filt},
        {
            "$group": {
                "_id": {"$ifNull": ["$project", "Unspecified"]},
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"count": -1}},
    ]
    rows = await db.site_visit_events.aggregate(pipeline).to_list(500)
    by_project = [{"project": r["_id"] or "Unspecified", "count": r["count"]} for r in rows]
    total = sum(r["count"] for r in by_project)
    return {"total": total, "by_project": by_project}
