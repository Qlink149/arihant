"""Shared MongoDB query fragments for dashboard analytics and org-wide drill-down."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from crm.constants.lead_picklists import (
    CANONICAL_LOCATIONS,
    CANONICAL_PROJECTS,
    CANONICAL_SOURCES,
    merge_picklist_with_db,
)
from crm.constants.lead_status import terminal_exclusion_clause
from crm.core.state import db, utc_now
from crm.services.lead_search import case_insensitive_regex_filter, merge_query

IST = ZoneInfo("Asia/Kolkata")

DORMANT_INACTIVITY_DAYS = 7

ORG_WIDE_DASHBOARD_METRICS = frozenset(
    {
        "active_pipeline",
        "qualified_leads",
        "dormant_leads",
        "missed_follow_up",
        "todays_site_visits",
        "rnr",
        "negotiation",
        "follow_up_today",
        "todays_leads",
    }
)


def _parse_ymd_boundary(value: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
    """Parse YYYY-MM-DD as IST calendar day boundary, returned as UTC datetime."""
    if not value or not str(value).strip():
        return None
    raw = str(value).strip()[:10]
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return None
    if end_of_day:
        ist_dt = datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=IST)
    else:
        ist_dt = datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=IST)
    return ist_dt.astimezone(timezone.utc)


def created_since_filter(days: int) -> dict:
    cutoff_dt = utc_now() - timedelta(days=days)
    cutoff_iso = cutoff_dt.isoformat()
    no_dt = {"$or": [{"created_at_dt": {"$exists": False}}, {"created_at_dt": None}]}
    legacy = {
        "$or": [
            {"created_at": {"$gte": cutoff_iso}},
            {"created_at": {"$type": "date", "$gte": cutoff_dt}},
        ],
    }
    return {"$or": [{"created_at_dt": {"$gte": cutoff_dt}}, {"$and": [no_dt, legacy]}]}


def created_range_filter(created_from: Optional[str], created_to: Optional[str]) -> dict:
    clauses = []
    start = _parse_ymd_boundary(created_from, end_of_day=False)
    end = _parse_ymd_boundary(created_to, end_of_day=True)
    if start:
        clauses.append({"created_at_dt": {"$gte": start}})
    if end:
        clauses.append({"created_at_dt": {"$lte": end}})
    if not clauses:
        return {}
    return merge_query(*clauses)


_QUARTER_START_MONTH = {1: 1, 2: 4, 3: 7, 4: 10}
_QUARTER_END_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}
_QUARTER_LABEL_SUFFIX = {1: "Jan–Mar", 2: "Apr–Jun", 3: "Jul–Sep", 4: "Oct–Dec"}


def _quarter_date_bounds(year: int, quarter: int) -> tuple[str, str]:
    """Inclusive calendar quarter bounds as YYYY-MM-DD (IST calendar dates)."""
    if quarter not in _QUARTER_START_MONTH:
        raise ValueError(f"Invalid quarter: {quarter}")
    start = date(year, _QUARTER_START_MONTH[quarter], 1)
    end_month = _QUARTER_END_MONTH[quarter]
    if end_month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, end_month + 1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _current_ist_date() -> date:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Kolkata")).date()
    except Exception:
        return utc_now().date()


def resolve_quarter_param(quarter: Optional[str]) -> tuple[Optional[str], Optional[str], str, str]:
    """
    Parse quarter filter for sales ranking.

    Returns (created_from, created_to, quarter_key, quarter_label).
    For all-time, created_from and created_to are None.
    """
    raw = (quarter or "current").strip().lower()
    if raw in ("all", "all_time", "all-time"):
        return None, None, "all", "All Time"

    today = _current_ist_date()
    if raw == "current":
        q_num = (today.month - 1) // 3 + 1
        year = today.year
        key = f"{year}-Q{q_num}"
    else:
        import re

        m = re.match(r"^(\d{4})-q([1-4])$", raw.replace("Q", "q"))
        if not m:
            raise ValueError(f"Invalid quarter: {quarter}. Use current, all, or YYYY-Qn.")
        year = int(m.group(1))
        q_num = int(m.group(2))
        key = f"{year}-Q{q_num}"

    created_from, created_to = _quarter_date_bounds(year, q_num)
    label = f"Q{q_num} {year} · {_QUARTER_LABEL_SUFFIX[q_num]}"
    return created_from, created_to, key, label


def resolve_sales_period_filter(
    *,
    quarter: Optional[str] = None,
    days: Optional[int] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
) -> tuple[dict, str]:
    """
    Resolve sales dashboard period filters.

    Quarter takes precedence when set to a specific period. Otherwise uses days or
    explicit created_from / created_to bounds. Returns (mongo_filter, label).
    """
    q_raw = (quarter or "").strip()
    if q_raw and q_raw.lower() not in ("all", "all_time", "all-time"):
        cf, ct, _, qlabel = resolve_quarter_param(q_raw)
        if cf and ct:
            return created_range_filter(cf, ct), qlabel
        return {}, "All Time"

    if days and days > 0:
        return created_since_filter(days), f"Last {days} days"

    cf = (created_from or "").strip() or None
    ct = (created_to or "").strip() or None
    if cf or ct:
        rng = created_range_filter(cf, ct)
        if cf and ct and cf == ct:
            try:
                label = date.fromisoformat(cf).strftime("%d %b %Y")
            except ValueError:
                label = cf
        elif cf and ct:
            label = f"{cf} – {ct}"
        elif cf:
            label = f"From {cf}"
        else:
            label = f"Until {ct}"
        return rng, label

    return {}, "All Time"


def build_dashboard_base_query(
    *,
    days: Optional[int] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    project: Optional[str] = None,
) -> dict:
    """Cohort query: project + lead creation window (intake/history metrics)."""
    clauses = []
    if days and days > 0:
        clauses.append(created_since_filter(days))
    elif created_from or created_to:
        range_q = created_range_filter(created_from, created_to)
        if range_q:
            clauses.append(range_q)
    if project and str(project).strip() and str(project).strip().lower() != "all":
        clauses.append(case_insensitive_regex_filter("project", project))
    if not clauses:
        return {}
    return merge_query(*clauses)


def build_dashboard_snapshot_query(*, project: Optional[str] = None) -> dict:
    """Snapshot query: project only (operational queues — ignores created-date filters)."""
    if project and str(project).strip() and str(project).strip().lower() != "all":
        return case_insensitive_regex_filter("project", project)
    return {}


def build_created_cohort_filter(
    *,
    days: Optional[int] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
) -> dict:
    """Cohort created-date window (aligned with dashboard analytics intake filters)."""
    if days and days > 0 and not (created_from or created_to):
        return created_since_filter(days)
    if created_from or created_to:
        return created_range_filter(created_from, created_to)
    return {}


def _stale_activity_clause(cutoff: datetime, cutoff_iso: str) -> dict:
    no_updated_dt = {"$or": [{"updated_at_dt": {"$exists": False}}, {"updated_at_dt": None}]}
    no_updated_at = {"$or": [{"updated_at": {"$exists": False}}, {"updated_at": None}]}
    return {
        "$or": [
            {"updated_at_dt": {"$lt": cutoff}},
            {
                "$and": [
                    no_updated_dt,
                    {"$or": [{"updated_at": {"$lt": cutoff}}, {"updated_at": {"$lt": cutoff_iso}}]},
                ]
            },
            {
                "$and": [
                    no_updated_dt,
                    no_updated_at,
                    {"$or": [{"created_at_dt": {"$lt": cutoff}}, {"created_at": {"$lt": cutoff_iso}}]},
                ]
            },
        ]
    }


def non_dormant_terminal_status_clause() -> dict:
    return {"lead_status": terminal_exclusion_clause()}


def dormant_leads_query(base_query: Optional[dict] = None) -> dict:
    cutoff = utc_now() - timedelta(days=DORMANT_INACTIVITY_DAYS)
    cutoff_iso = cutoff.isoformat()
    base = base_query or {}
    return {
        "$and": [
            base,
            _stale_activity_clause(cutoff, cutoff_iso),
            non_dormant_terminal_status_clause(),
        ]
    }


def active_pipeline_filter() -> dict:
    """Contacted, Nurturing, or Negotiation — meaningful active pipeline stages."""
    return {"lead_status": {"$regex": r"^(contacted|nurturing|negotiation)$", "$options": "i"}}


def qualified_leads_filter() -> dict:
    """Backward-compatible alias for active pipeline metric key qualified_leads."""
    return active_pipeline_filter()


def nurturing_temperature_query(base: dict, label: str) -> dict:
    return {
        **base,
        "lead_status": {"$regex": r"^nurturing$", "$options": "i"},
        "temperature": {"$regex": f"^{label}$", "$options": "i"},
    }


_INVALID_PROJECT_REGEX = {"$regex": r"^(?i)\s*(unknown|na|n/a|others|null)\s*$"}
_INVALID_PROJECT_PART_REGEX = (
    r"(?i)^\s*(unknown|na|n/a|others?|null|sold\s*out\s*enquiry|homepage\s*enquiry|"
    r"all\s*projects?|commercial\s*space|upcoming\s*commercial)\s*$"
)
_INVALID_LOCATION_REGEX = {"$regex": r"^(?i)\s*(unknown|na|n/a|others?|null|-)\s*$"}


def merge_query_with_valid_projects(query: dict) -> dict:
    valid_proj = {
        "project": {
            "$exists": True,
            "$nin": [None, ""],
            "$not": _INVALID_PROJECT_REGEX,
        }
    }
    if not query:
        return valid_proj
    return {"$and": [query, valid_proj]}


def project_distribution_pipeline(match_query: dict, limit: int = 100) -> List[Dict[str, Any]]:
    """Split semicolon-delimited project fields and group by individual project name."""
    return [
        {"$match": match_query},
        {
            "$addFields": {
                "_project_parts": {
                    "$filter": {
                        "input": {
                            "$map": {
                                "input": {"$split": [{"$ifNull": ["$project", ""]}, ";"]},
                                "as": "p",
                                "in": {"$trim": {"input": "$$p"}},
                            }
                        },
                        "as": "p",
                        "cond": {
                            "$and": [
                                {"$gt": [{"$strLenCP": "$$p"}, 0]},
                                {
                                    "$not": {
                                        "$regexMatch": {
                                            "input": "$$p",
                                            "regex": _INVALID_PROJECT_PART_REGEX,
                                        }
                                    }
                                },
                            ]
                        },
                    }
                }
            }
        },
        {"$unwind": "$_project_parts"},
        {"$group": {"_id": "$_project_parts", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
    ]


async def fetch_lead_filter_options(
    *,
    scope_filter: Optional[Dict[str, Any]] = None,
    project_limit: int = 200,
    location_limit: int = 200,
    source_limit: int = 200,
) -> Dict[str, List[Dict[str, Any]]]:
    """Distinct projects, locations, and sources for Virtual Customer filter dropdowns."""
    base = scope_filter or {}
    project_rows = await db.leads.aggregate(
        project_distribution_pipeline(merge_query_with_valid_projects(base), limit=project_limit)
    ).to_list(project_limit)

    location_match: Dict[str, Any] = {
        "location": {"$exists": True, "$nin": [None, ""], "$not": _INVALID_LOCATION_REGEX},
    }
    if base:
        location_match = merge_query(base, location_match)
    location_pipeline = [
        {"$match": location_match},
        {
            "$group": {
                "_id": {"$trim": {"input": {"$ifNull": ["$location", ""]}}},
                "count": {"$sum": 1},
            }
        },
        {"$match": {"_id": {"$ne": ""}}},
        {"$sort": {"count": -1}},
        {"$limit": location_limit},
    ]
    location_rows = await db.leads.aggregate(location_pipeline).to_list(location_limit)

    source_match: Dict[str, Any] = {
        "lead_source": {"$exists": True, "$nin": [None, ""]},
    }
    if base:
        source_match = merge_query(base, source_match)
    source_pipeline = [
        {"$match": source_match},
        {
            "$group": {
                "_id": {"$trim": {"input": {"$ifNull": ["$lead_source", ""]}}},
                "count": {"$sum": 1},
            }
        },
        {"$match": {"_id": {"$ne": ""}}},
        {"$sort": {"count": -1}},
        {"$limit": source_limit},
    ]
    source_rows = await db.leads.aggregate(source_pipeline).to_list(source_limit)

    db_projects = [{"name": r["_id"], "count": r["count"]} for r in project_rows if r.get("_id")]
    db_locations = [{"name": r["_id"], "count": r["count"]} for r in location_rows if r.get("_id")]
    db_sources = [{"name": r["_id"], "count": r["count"]} for r in source_rows if r.get("_id")]

    return {
        "projects": merge_picklist_with_db(CANONICAL_PROJECTS, db_projects),
        "locations": merge_picklist_with_db(CANONICAL_LOCATIONS, db_locations),
        "sources": merge_picklist_with_db(CANONICAL_SOURCES, db_sources),
    }


def _nurturing_temp_match(label: str) -> dict:
    return {
        "lead_status": {"$regex": r"^nurturing$", "$options": "i"},
        "temperature": {"$regex": f"^{label}$", "$options": "i"},
    }


def _dormant_extra_match() -> dict:
    cutoff = utc_now() - timedelta(days=DORMANT_INACTIVITY_DAYS)
    cutoff_iso = cutoff.isoformat()
    return {
        "$and": [
            _stale_activity_clause(cutoff, cutoff_iso),
            non_dormant_terminal_status_clause(),
        ]
    }


def build_dashboard_cohort_facet_pipeline(cohort_query: dict) -> List[Dict[str, Any]]:
    """Single aggregation for cohort KPI counts (same filters as legacy count_documents)."""
    return [
        {"$match": cohort_query},
        {
            "$facet": {
                "total": [{"$count": "n"}],
                "hot": [{"$match": _nurturing_temp_match("hot")}, {"$count": "n"}],
                "warm": [{"$match": _nurturing_temp_match("warm")}, {"$count": "n"}],
                "vip": [{"$match": {"vip": True}}, {"$count": "n"}],
                "active_pipeline": [{"$match": active_pipeline_filter()}, {"$count": "n"}],
                "open": [
                    {
                        "$match": {
                            "lead_status": {"$regex": "open|new|contacted", "$options": "i"}
                        }
                    },
                    {"$count": "n"},
                ],
                "lost": [
                    {
                        "$match": {
                            "lead_status": {
                                "$regex": "lost|dropped|unqualified",
                                "$options": "i",
                            }
                        }
                    },
                    {"$count": "n"},
                ],
                "dormant": [{"$match": _dormant_extra_match()}, {"$count": "n"}],
            }
        },
    ]


def _facet_count(facet_doc: dict, key: str) -> int:
    branch = facet_doc.get(key) or []
    if not branch:
        return 0
    return int(branch[0].get("n", 0))


async def count_dashboard_cohort_metrics(cohort_query: dict) -> Dict[str, int]:
    rows = await db.leads.aggregate(build_dashboard_cohort_facet_pipeline(cohort_query)).to_list(1)
    if not rows:
        return {
            "total_leads": 0,
            "hot_leads": 0,
            "warm_leads": 0,
            "vip_leads": 0,
            "active_pipeline_leads": 0,
            "qualified_leads": 0,
            "open_leads": 0,
            "lost_leads": 0,
            "dormant_leads": 0,
        }
    doc = rows[0]
    return {
        "total_leads": _facet_count(doc, "total"),
        "hot_leads": _facet_count(doc, "hot"),
        "warm_leads": _facet_count(doc, "warm"),
        "vip_leads": _facet_count(doc, "vip"),
        "active_pipeline_leads": _facet_count(doc, "active_pipeline"),
        "qualified_leads": _facet_count(doc, "active_pipeline"),
        "open_leads": _facet_count(doc, "open"),
        "lost_leads": _facet_count(doc, "lost"),
        "dormant_leads": _facet_count(doc, "dormant"),
    }
