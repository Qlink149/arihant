"""Lead overview KPI counts and drill-down filters for My Dashboard."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from crm.constants.lead_kpi import SITE_VISIT_STATUS_REGEX
from crm.constants.lead_status import (
    CLOSED_LEAD_STATUS_REGEX,
    SV_FOLLOWUP_1_STATUS_QUERY,
    SV_FOLLOWUP_2_STATUS_QUERY,
    SV_FOLLOWUP_STATUS_QUERY,
)
from crm.services.sales_dashboard_filters import rnr_metric_clause
from crm.core.state import db
from crm.services.lead_analytics_queries import active_pipeline_filter
from crm.services.lead_follow_up import (
    follow_up_today_clause,
    missed_follow_up_clause,
    pending_task_due_lead_ids,
)
from crm.services.lead_search import merge_query
from crm.services.transfer_queries import incoming_transfer_filter, outgoing_transfer_filter

IST = ZoneInfo("Asia/Kolkata")

_RE_JUNK = {"$regex": r"junk", "$options": "i"}
_RE_UNQUALIFIED = {"$regex": r"unqualified", "$options": "i"}
_RE_GONE_COLD = {"$regex": r"gone\s*cold", "$options": "i"}
_RE_RE_ENGAGED_STATUS = {"$regex": r"re[\s\-]*engag", "$options": "i"}
_RE_SV_VISIT_COMPLETED = {
    "$regex": r"(site\s*visit\s*completed|visit\s*completed|office\s*visit\s*completed)",
    "$options": "i",
}
_RE_NEGOTIATION = {"$regex": r"negotiat", "$options": "i"}
_RE_ACTIVE_RE_ENGAGE_STATUS = {
    "$regex": r"(contacted|nurtur|follow\s*up)",
    "$options": "i",
}
_RE_WAS_COLD = {"$regex": r"gone\s*cold", "$options": "i"}


def sv_conducted_status_clause() -> dict:
    """Visit completed plus SV follow-up pipeline stages."""
    return {
        "$or": [
            {"lead_status": _RE_SV_VISIT_COMPLETED},
            {"lead_status": SV_FOLLOWUP_STATUS_QUERY},
            {"lead_status": SV_FOLLOWUP_1_STATUS_QUERY},
            {"lead_status": SV_FOLLOWUP_2_STATUS_QUERY},
        ]
    }


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


def ist_tomorrow_window(now_dt: Optional[datetime] = None) -> Tuple[str, datetime, datetime]:
    """Return (tomorrow_str YYYY-MM-DD in IST, tomorrow_start_utc, tomorrow_end_utc)."""
    _, _, day_end_utc = ist_day_window(now_dt)
    tomorrow_start_utc = day_end_utc
    tomorrow_end_utc = tomorrow_start_utc + timedelta(days=1)
    tomorrow_ist = tomorrow_start_utc.astimezone(IST)
    tomorrow_str = tomorrow_ist.strftime("%Y-%m-%d")
    return tomorrow_str, tomorrow_start_utc, tomorrow_end_utc


def ist_recent_cutoff_utc(days: int = 14, now_dt: Optional[datetime] = None) -> datetime:
    """Rolling window cutoff aligned to IST calendar start of today minus N days."""
    today_str, day_start_utc, _ = ist_day_window(now_dt)
    start_ist = datetime.fromisoformat(today_str).replace(tzinfo=IST)
    cutoff_ist = start_ist - timedelta(days=days)
    return cutoff_ist.astimezone(timezone.utc)


def _active_pipeline_clause() -> dict:
    return {
        "lead_status": {
            "$not": {"$regex": CLOSED_LEAD_STATUS_REGEX.pattern, "$options": "i"},
        }
    }


def _rnr_clause() -> dict:
    """Delegate to shared current-status RNR clause (no historical FW-only match)."""
    return rnr_metric_clause()


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


def _build_follow_up_today_filter(ctx: dict) -> dict:
    return merge_query(
        ctx["base_filter"],
        follow_up_today_clause(ctx, ctx.get("follow_up_today_task_lead_ids")),
    )


def _build_missed_follow_up_filter(ctx: dict) -> dict:
    return merge_query(
        ctx["base_filter"],
        missed_follow_up_clause(ctx, ctx.get("missed_follow_up_task_lead_ids")),
    )


METRIC_KEY_ALIASES = {
    "qualified_leads": "active_pipeline",
}


def resolve_metric_key(metric_key: str) -> str:
    return METRIC_KEY_ALIASES.get(metric_key, metric_key)


METRIC_SPECS: List[Dict[str, Any]] = [
    {
        "key": "active_pipeline",
        "label": "Active pipeline",
        "subtitle": "Contacted, Nurturing, Negotiation",
        "accent": "green",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "active_pipeline"}},
        "build_filter": lambda ctx: merge_query(ctx["base_filter"], active_pipeline_filter()),
        "collection": "leads",
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
        "subtitle": "Due today (IST)",
        "accent": "amber",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "follow_up_today"}},
        "build_filter": _build_follow_up_today_filter,
        "collection": "leads",
    },
    {
        "key": "missed_follow_up",
        "label": "Missed follow up",
        "subtitle": "Overdue follow-ups (IST)",
        "accent": "red",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "missed_follow_up"}},
        "build_filter": _build_missed_follow_up_filter,
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
        "subtitle": "Scheduled today (IST)",
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
        "subtitle": "Visits completed + SV follow-up",
        "accent": "green",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "sv_conducted"}},
        "build_filter": lambda ctx: merge_query(
            ctx["base_filter"],
            sv_conducted_status_clause(),
        ),
        "collection": "leads",
    },
    {
        "key": "negotiation",
        "label": "In negotiation",
        "subtitle": "Active deal discussions",
        "accent": "green",
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
        "key": "unqualified",
        "label": "Unqualified",
        "subtitle": "Not qualified",
        "accent": "slate",
        "drill_down": {"type": "virtual_customer", "params": {"metric": "unqualified"}},
        "build_filter": lambda ctx: merge_query(
            ctx["base_filter"],
            {
                "$or": [
                    {"lead_status": _RE_UNQUALIFIED},
                    {"original_fw_status": _RE_UNQUALIFIED},
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
for _alias, _canonical in METRIC_KEY_ALIASES.items():
    if _canonical in _METRIC_BY_KEY:
        _METRIC_BY_KEY[_alias] = _METRIC_BY_KEY[_canonical]


def is_overview_drill_metric(metric_key: str) -> bool:
    """True when metric maps to a lead-collection overview spec (My Dashboard tiles)."""
    key = resolve_metric_key(metric_key)
    spec = _METRIC_BY_KEY.get(key)
    return bool(spec and spec.get("collection") == "leads")


def build_metric_context(
    base_filter: dict,
    *,
    uid: str,
    name: str,
    is_manager: bool,
    now_dt: Optional[datetime] = None,
) -> dict:
    today_str, day_start_utc, day_end_utc = ist_day_window(now_dt)
    recent_cutoff_utc = ist_recent_cutoff_utc(14, now_dt)
    return {
        "base_filter": base_filter or {},
        "uid": uid,
        "name": name,
        "is_manager": is_manager,
        "today_str": today_str,
        "day_start_utc": day_start_utc,
        "day_end_utc": day_end_utc,
        "recent_cutoff_utc": recent_cutoff_utc,
        "follow_up_today_task_lead_ids": [],
        "missed_follow_up_task_lead_ids": [],
    }


async def enrich_follow_up_task_ids(ctx: dict, *, base_filter: Optional[dict] = None) -> dict:
    """Populate task-backed lead ids for follow-up metrics, scoped to base_filter when provided."""
    today_str = ctx["today_str"]
    scope_lead_ids: Optional[List[str]] = None
    if base_filter:
        scope_lead_ids = []
        async for doc in db.leads.find(base_filter or {}, {"_id": 0, "id": 1}):
            lid = (doc.get("id") or "").strip()
            if lid:
                scope_lead_ids.append(lid)
        if not scope_lead_ids:
            ctx["follow_up_today_task_lead_ids"] = []
            ctx["missed_follow_up_task_lead_ids"] = []
            return ctx
    today_ids, missed_ids = await asyncio.gather(
        pending_task_due_lead_ids(today_str, due_today=True, scope_lead_ids=scope_lead_ids),
        pending_task_due_lead_ids(today_str, overdue=True, scope_lead_ids=scope_lead_ids),
    )
    ctx["follow_up_today_task_lead_ids"] = today_ids
    ctx["missed_follow_up_task_lead_ids"] = missed_ids
    return ctx


def metric_filter_for_key(metric_key: str, ctx: dict) -> dict:
    spec = _METRIC_BY_KEY.get(resolve_metric_key(metric_key))
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


async def build_dashboard_operational_facet_pipeline(
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
    await enrich_follow_up_task_ids(ctx, base_filter=snapshot_base or {})
    facet: Dict[str, List[dict]] = {}
    for key in metric_keys:
        spec = _METRIC_BY_KEY.get(key)
        if not spec or spec.get("collection") != "leads":
            facet[key] = [{"$limit": 0}, {"$count": "n"}]
        else:
            filt = merge_query(snapshot_base or {}, spec["build_filter"](ctx))
            facet[key] = [{"$match": filt}, {"$count": "n"}]
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
    pipeline = await build_dashboard_operational_facet_pipeline(
        snapshot_base, metric_keys, now_dt=now_dt
    )
    rows = await db.leads.aggregate(pipeline).to_list(1)
    if not rows:
        return {key: 0 for key in metric_keys}
    doc = rows[0]
    return {key: _operational_facet_count(doc, key) for key in metric_keys}


async def build_lead_overview_facet_pipeline(ctx: dict) -> List[Dict[str, Any]]:
    """Single $facet for all lead-collection overview metrics."""
    facet: Dict[str, List[dict]] = {}
    for spec in METRIC_SPECS:
        if spec.get("collection") != "leads":
            continue
        filt = spec["build_filter"](ctx)
        facet[spec["key"]] = [{"$match": filt}, {"$count": "n"}]
    return [{"$facet": facet}] if facet else []


async def build_transfer_overview_facet_pipeline(ctx: dict) -> List[Dict[str, Any]]:
    """Single $facet for transfer-collection overview metrics."""
    facet: Dict[str, List[dict]] = {}
    for spec in METRIC_SPECS:
        if spec.get("collection") != "transfers":
            continue
        filt = spec["build_filter"](ctx)
        facet[spec["key"]] = [{"$match": filt}, {"$count": "n"}]
    return [{"$facet": facet}] if facet else []


def _facet_count(facet_doc: dict, key: str) -> int:
    branch = facet_doc.get(key) or []
    if not branch:
        return 0
    return int(branch[0].get("n", 0))


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
    await enrich_follow_up_task_ids(ctx, base_filter=base_filter)

    lead_pipeline = await build_lead_overview_facet_pipeline(ctx)
    transfer_pipeline = await build_transfer_overview_facet_pipeline(ctx)

    async def _empty_rows():
        return []

    lead_rows, transfer_rows = await asyncio.gather(
        db.leads.aggregate(lead_pipeline).to_list(1) if lead_pipeline else _empty_rows(),
        db.lead_transfers.aggregate(transfer_pipeline).to_list(1) if transfer_pipeline else _empty_rows(),
    )

    counts_by_key: Dict[str, int] = {}
    if lead_rows:
        doc = lead_rows[0]
        for spec in METRIC_SPECS:
            if spec.get("collection") == "leads":
                counts_by_key[spec["key"]] = _facet_count(doc, spec["key"])
    if transfer_rows:
        doc = transfer_rows[0]
        for spec in METRIC_SPECS:
            if spec.get("collection") == "transfers":
                counts_by_key[spec["key"]] = _facet_count(doc, spec["key"])

    metrics = []
    for spec in METRIC_SPECS:
        metrics.append(
            {
                "key": spec["key"],
                "label": spec["label"],
                "count": counts_by_key.get(spec["key"], 0),
                "subtitle": spec["subtitle"],
                "accent": spec["accent"],
                "drill_down": spec["drill_down"],
            }
        )

    as_of = datetime.now(timezone.utc).astimezone(IST).isoformat()
    return {"as_of": as_of, "metrics": metrics}
