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
from crm.services.lead_field_normalize import remap_projects_from_values
from crm.services.lead_project_fields import coalesce_projects
from crm.utils.helpers import iso_utc_now

IST = ZoneInfo("Asia/Kolkata")

UNSPECIFIED_LABEL = "Unspecified"
# A visit by a lead interested in several projects cannot be attributed to one
# of them (we do not know which project was visited), so it gets its own bucket.
MULTIPLE_PROJECTS_LABEL = "Multiple projects"


def event_project_bucket(project: Optional[str], projects: Optional[List[str]] = None) -> str:
    """Report bucket for one event: the canonical project name (same client-approved
    mapping the leads use), MULTIPLE_PROJECTS_LABEL, or UNSPECIFIED_LABEL."""
    _, mapped = remap_projects_from_values(project, projects)
    if not mapped:
        return UNSPECIFIED_LABEL
    if len(mapped) > 1:
        return MULTIPLE_PROJECTS_LABEL
    return mapped[0]


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
        project = lead.get("project") or (projects[0] if projects else None)
        # Store canonical names so the permanent log never reintroduces old spellings.
        norm_project, norm_projects = remap_projects_from_values(project, projects)
        if norm_project is not None:
            project, projects = norm_project, norm_projects
        event = {
            "id": event_id,
            "lead_id": lead_id,
            "completed_at_dt": completed_at_dt,
            "completed_at": iso_utc_now(),
            "project": project,
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
                "_id": {"project": "$project", "projects": "$projects"},
                "count": {"$sum": 1},
            }
        },
    ]
    rows = await db.site_visit_events.aggregate(pipeline).to_list(5000)

    # Merge old/short spellings ("Reserve 16", "Vivriti", "Mélange" ...) into the
    # canonical project, so one project is one bar however its events were stored.
    merged: Dict[str, int] = {}
    for r in rows:
        key = r["_id"] or {}
        bucket = event_project_bucket(key.get("project"), key.get("projects"))
        merged[bucket] = merged.get(bucket, 0) + r["count"]

    by_project = [
        {"project": name, "count": count}
        for name, count in sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    total = sum(r["count"] for r in by_project)
    return {"total": total, "by_project": by_project}


async def build_site_visit_leads(
    *,
    window: Dict[str, Optional[datetime]],
    sales_owner_id: Optional[str] = None,
    project: Optional[str] = None,
    limit: int = 500,
) -> Dict[str, Any]:
    """The visits behind the report, one row per visit, with the lead's CURRENT status.

    Same filter as build_site_visit_report so the list always adds up to its total.
    `project` is a report bucket (canonical name, "Multiple projects" or "Unspecified").
    """
    filt = build_site_visit_report_filter(window=window, sales_owner_id=sales_owner_id)
    events = await db.site_visit_events.find(filt, {"_id": 0}).sort("completed_at_dt", -1).to_list(5000)
    if project:
        events = [e for e in events if event_project_bucket(e.get("project"), e.get("projects")) == project]
    total = len(events)
    events = events[: max(1, min(int(limit or 500), 2000))]

    lead_ids = list({e["lead_id"] for e in events if e.get("lead_id")})
    leads: Dict[str, Dict[str, Any]] = {}
    if lead_ids:
        for lead in await db.leads.find(
            {"id": {"$in": lead_ids}},
            {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "phone": 1, "lead_status": 1, "assigned_to_name": 1},
        ).to_list(len(lead_ids)):
            leads[lead["id"]] = lead

    rows: List[Dict[str, Any]] = []
    for e in events:
        lead = leads.get(e.get("lead_id")) or {}
        name = f"{(lead.get('first_name') or '').strip()} {(lead.get('last_name') or '').strip()}".strip()
        rows.append(
            {
                "event_id": e.get("id"),
                "lead_id": e.get("lead_id"),
                "lead_name": name or e.get("lead_name") or "Lead",
                "phone": lead.get("phone") or e.get("phone"),
                "project": event_project_bucket(e.get("project"), e.get("projects")),
                "visit_completed_at": e["completed_at_dt"].astimezone(timezone.utc).isoformat() if e.get("completed_at_dt") else None,
                "current_status": lead.get("lead_status"),  # None when the lead no longer exists
                "sales_owner": lead.get("assigned_to_name") or e.get("assigned_to_name"),
            }
        )
    return {"total": total, "distinct_leads": len({r["lead_id"] for r in rows}), "visits": rows}
