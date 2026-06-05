"""Lead overview KPI counts and drill-down filters for My Dashboard."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from crm.constants.lead_kpi import RNR_STATUS_REGEX, SITE_VISIT_STATUS_REGEX
from crm.constants.lead_status import CLOSED_LEAD_STATUS_REGEX
from crm.core.state import db
from crm.services.lead_analytics_queries import qualified_leads_filter
from crm.services.lead_search import merge_query
from crm.services.transfer_queries import incoming_transfer_filter, outgoing_transfer_filter

IST = ZoneInfo("Asia/Kolkata")

_RE_JUNK = {"$regex": r"junk", "$options": "i"}
_RE_GONE_COLD = {"$regex": r"gone\s*cold", "$options": "i"}
_RE_RE_ENGAGED_STATUS = {"$regex": r"re[\s\-]*engag", "$options": "i"}
_RE_SV_CONDUCTED = {"$regex": r"(site\s*visit\s*completed|visit\s*completed|office\s*visit\s*completed)", "$options": "i"}
_RE_NEGOTIATION = {"$regex": r"negotiat", "$options": "i"}
_RE_ACTIVE_RE_ENGAGE_STATUS = {
    "$regex": r"(contacted|nurtur|follow\s*up)",
    "$options": "i",
}
_RE_WAS_COLD = {"$regex": r"gone\s*cold", "$options": "i"}


def ist_day_window(now_dt: Optional[datetime] = None) -> Tuple[str, datetime, datetime]:
    """Return (today_str YYYY-MM-DD, day_start_utc, day_end_utc) for the current IST calendar day."""
    now = now_dt or datetime.now(timezone.utc)
    ist = now.astimezone(IST)
    today_str = ist.strftime("%Y-%m-%d")
    day_start_ist = datetime(
        ist.year, ist.month, ist.day, 0, 0, 0, tzinfo=IST
    )
    day_end_ist = day_start_ist + timedelta(days=1)
    return today_str, day_start_ist.astimezone(timezone.utc), day_end_ist.astimezone(timezone.utc)


def _active_pipeline_clause() -> dict:
    return {
        "lead_status": {
            "$not": {"$regex": CLOSED_LEAD_STATUS_REGEX.pattern, "$options": "i"},
        }
    }


def _rnr_clause() -> dict:
    return {
        "$or": [
            {"is_rnr": True},
            {"lead_status": {"$regex": RNR_STATUS_REGEX}},
            {"original_fw_status": {"$regex": RNR_STATUS_REGEX}},
        ]
    }


def _created_today_clause(day_start_utc: datetime, day_end_utc: datetime) -> dict:
    return {
        "$or": [
            {"created_at_dt": {"$gte": day_start_utc, "$lt": day_end_utc}},
            {
                "$and": [
                    {"created_at_dt": {"$exists": False}},
                    {"created_at": {"$gte": day_start_utc.isoformat(), "$lt": day_end_utc.isoformat()}},
                ]
            },
        ]
    }


def _visit_today_clause(day_start_utc: datetime, day_end_utc: datetime) -> dict:
    return {
        "$and": [
            {"visit_date_dt": {"$gte": day_start_utc, "$lt": day_end_utc}},
            {"lead_status": {"$regex": SITE_VISIT_STATUS_REGEX}},
        ]
    }


def _re_engaged_clause(recent_cutoff_utc: datetime) -> dict:
    return {
        "$or": [
            {"lead_status": _RE_RE_ENGAGED_STATUS},
            {
                "$and": [
                    {"lead_status": _RE_ACTIVE_RE_ENGAGE_STATUS},
                    {"original_fw_status": _RE_WAS_COLD},
                    {
                        "$or": [
                            {"updated_at_dt": {"$gte": recent_cutoff_utc}},
                            {"updated_at": {"$gte": recent_cutoff_utc.isoformat()}},
                        ]
                    },
                ]
            },
        ]
    }


METRIC_SPECS: List[Dict[str, Any]] = [
    {
        "key": "qualified_leads",
        "label": "Qualified leads",
        "subtitle": "Status contains qualified",
        "accent": "green",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "qualified_leads"}},
        "build_filter": lambda ctx: qualified_leads_filter(),
        "collection": "leads",
        "org_wide": True,
    },
    {
        "key": "all_leads",
        "label": "All leads",
        "subtitle": "In your pipeline",
        "accent": "gold",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "all_leads"}},
        "build_filter": lambda ctx: ctx["base_filter"],
        "collection": "leads",
    },
    {
        "key": "todays_leads",
        "label": "Today's leads",
        "subtitle": "Created today (IST)",
        "accent": "teal",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "todays_leads"}},
        "build_filter": lambda ctx: merge_query(
            ctx["base_filter"],
            _created_today_clause(ctx["day_start_utc"], ctx["day_end_utc"]),
        ),
        "collection": "leads",
    },
    {
        "key": "follow_up_today",
        "label": "Follow up today",
        "subtitle": "Due today",
        "accent": "amber",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "follow_up_today"}},
        "build_filter": lambda ctx: merge_query(
            ctx["base_filter"],
            _active_pipeline_clause(),
            {"next_action_date": ctx["today_str"]},
        ),
        "collection": "leads",
    },
    {
        "key": "missed_follow_up",
        "label": "Missed follow up",
        "subtitle": "Overdue follow-ups",
        "accent": "red",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "missed_follow_up"}},
        "build_filter": lambda ctx: merge_query(
            ctx["base_filter"],
            _active_pipeline_clause(),
            {
                "next_action_date": {"$exists": True, "$ne": None, "$lt": ctx["today_str"]},
            },
        ),
        "collection": "leads",
    },
    {
        "key": "rnr",
        "label": "RNR",
        "subtitle": "Ring no response",
        "accent": "red",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "rnr"}},
        "build_filter": lambda ctx: merge_query(ctx["base_filter"], _rnr_clause()),
        "collection": "leads",
    },
    {
        "key": "todays_site_visits",
        "label": "Today's site visits",
        "subtitle": "Scheduled today",
        "accent": "purple",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "todays_site_visits"}},
        "build_filter": lambda ctx: merge_query(
            ctx["base_filter"],
            _visit_today_clause(ctx["day_start_utc"], ctx["day_end_utc"]),
        ),
        "collection": "leads",
    },
    {
        "key": "sv_conducted",
        "label": "SV conducted",
        "subtitle": "Visits completed",
        "accent": "green",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "sv_conducted"}},
        "build_filter": lambda ctx: merge_query(
            ctx["base_filter"],
            {"lead_status": _RE_SV_CONDUCTED},
        ),
        "collection": "leads",
    },
    {
        "key": "negotiation",
        "label": "In negotiation",
        "subtitle": "Active deal discussions",
        "accent": "green",
        "org_wide": True,
        "drill_down": {"type": "virtual_customer", "params": {"metric": "negotiation"}},
        "build_filter": lambda ctx: merge_query(
            ctx["base_filter"],
            {"lead_status": _RE_NEGOTIATION},
        ),
        "collection": "leads",
    },
    {
        "key": "junk",
        "label": "Junk",
        "subtitle": "Disqualified",
        "accent": "slate",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "junk"}},
        "build_filter": lambda ctx: merge_query(
            ctx["base_filter"],
            {
                "$or": [
                    {"lead_status": _RE_JUNK},
                    {"original_fw_status": _RE_JUNK},
                ]
            },
        ),
        "collection": "leads",
    },
    {
        "key": "gone_cold",
        "label": "Gone cold",
        "subtitle": "Inactive pipeline",
        "accent": "slate",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "gone_cold"}},
        "build_filter": lambda ctx: merge_query(
            ctx["base_filter"],
            {"lead_status": _RE_GONE_COLD},
        ),
        "collection": "leads",
    },
    {
        "key": "re_engaged",
        "label": "Re-engaged",
        "subtitle": "Recently reactivated",
        "accent": "blue",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "re_engaged"}},
        "build_filter": lambda ctx: merge_query(
            ctx["base_filter"],
            _re_engaged_clause(ctx["recent_cutoff_utc"]),
        ),
        "collection": "leads",
    },
    {
        "key": "leads_received",
        "label": "Leads Received",
        "subtitle": "Incoming transfers",
        "accent": "amber",
        "drill_down": {
            "type": "my_dashboard_transfers",
            "params": {"sub_tab": "received"},
        },
        "build_filter": lambda ctx: incoming_transfer_filter(
            ctx["name"], ctx["uid"], ctx["is_manager"]
        ),
        "collection": "transfers",
    },
    {
        "key": "leads_transferred",
        "label": "Leads Transferred",
        "subtitle": "Outgoing transfers",
        "accent": "teal",
        "drill_down": {
            "type": "my_dashboard_transfers",
            "params": {"sub_tab": "sent"},
        },
        "build_filter": lambda ctx: outgoing_transfer_filter(
            ctx["name"], ctx["uid"], ctx["is_manager"]
        ),
        "collection": "transfers",
    },
]

_METRIC_BY_KEY = {spec["key"]: spec for spec in METRIC_SPECS}


def build_metric_context(
    base_filter: dict,
    *,
    uid: str,
    name: str,
    is_manager: bool,
    now_dt: Optional[datetime] = None,
) -> dict:
    today_str, day_start_utc, day_end_utc = ist_day_window(now_dt)
    now = now_dt or datetime.now(timezone.utc)
    recent_cutoff_utc = now - timedelta(days=14)
    return {
        "base_filter": base_filter or {},
        "uid": uid,
        "name": name,
        "is_manager": is_manager,
        "today_str": today_str,
        "day_start_utc": day_start_utc,
        "day_end_utc": day_end_utc,
        "recent_cutoff_utc": recent_cutoff_utc,
    }


def metric_filter_for_key(metric_key: str, ctx: dict) -> dict:
    spec = _METRIC_BY_KEY.get(metric_key)
    if not spec:
        return {}
    return spec["build_filter"](ctx)


async def _count_for_spec(spec: dict, ctx: dict) -> int:
    filt = spec["build_filter"](ctx)
    if spec["collection"] == "transfers":
        return await db.lead_transfers.count_documents(filt)
    return await db.leads.count_documents(filt)


async def count_org_wide_metrics(
    snapshot_base: dict,
    metric_keys: tuple[str, ...],
    *,
    now_dt: Optional[datetime] = None,
) -> Dict[str, int]:
    """Count operational KPIs org-wide using snapshot base (project filter only)."""
    return await count_dashboard_operational_metrics(
        snapshot_base, metric_keys, now_dt=now_dt
    )


def build_dashboard_operational_facet_pipeline(
    snapshot_base: dict,
    metric_keys: tuple[str, ...],
    *,
    now_dt: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    ctx = build_metric_context(
        snapshot_base or {},
        uid="",
        name="",
        is_manager=False,
        now_dt=now_dt,
    )
    facet: Dict[str, List[dict]] = {}
    for key in metric_keys:
        spec = _METRIC_BY_KEY.get(key)
        if not spec or spec.get("collection") != "leads":
            facet[key] = [{"$limit": 0}, {"$count": "n"}]
        else:
            facet[key] = [{"$match": spec["build_filter"](ctx)}, {"$count": "n"}]
    return [{"$facet": facet}]


def _operational_facet_count(facet_doc: dict, key: str) -> int:
    branch = facet_doc.get(key) or []
    if not branch:
        return 0
    return int(branch[0].get("n", 0))


async def count_dashboard_operational_metrics(
    snapshot_base: dict,
    metric_keys: tuple[str, ...],
    *,
    now_dt: Optional[datetime] = None,
) -> Dict[str, int]:
    """One aggregation for dashboard operational tiles (same filters as count_org_wide_metrics)."""
    if not metric_keys:
        return {}
    pipeline = build_dashboard_operational_facet_pipeline(
        snapshot_base, metric_keys, now_dt=now_dt
    )
    rows = await db.leads.aggregate(pipeline).to_list(1)
    if not rows:
        return {key: 0 for key in metric_keys}
    doc = rows[0]
    return {key: _operational_facet_count(doc, key) for key in metric_keys}


async def build_lead_overview_metrics(
    base_filter: dict,
    *,
    uid: str,
    name: str,
    is_manager: bool,
    now_dt: Optional[datetime] = None,
) -> dict:
    ctx = build_metric_context(
        base_filter, uid=uid, name=name, is_manager=is_manager, now_dt=now_dt
    )
    counts = await asyncio.gather(*[_count_for_spec(spec, ctx) for spec in METRIC_SPECS])

    metrics = []
    for spec, count in zip(METRIC_SPECS, counts):
        metrics.append(
            {
                "key": spec["key"],
                "label": spec["label"],
                "count": count,
                "subtitle": spec["subtitle"],
                "accent": spec["accent"],
                "drill_down": spec["drill_down"],
            }
        )

    as_of = datetime.now(timezone.utc).astimezone(IST).isoformat()
    return {"as_of": as_of, "metrics": metrics}
