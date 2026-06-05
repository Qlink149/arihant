"""Shared MongoDB query fragments for dashboard analytics and org-wide drill-down."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from crm.core.state import db, utc_now
from crm.services.lead_search import case_insensitive_regex_filter, merge_query

DORMANT_INACTIVITY_DAYS = 7

ORG_WIDE_DASHBOARD_METRICS = frozenset(
    {
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
    if not value or not str(value).strip():
        return None
    raw = str(value).strip()[:10]
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return None
    if end_of_day:
        return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)
    return datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=timezone.utc)


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
    return {
        "$nor": [
            {
                "lead_status": {
                    "$regex": r"(?i)^\s*(won|lost|advance\s*paid|closed|booked|dropped|unqualified)\s*$",
                }
            }
        ]
    }


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


def qualified_leads_filter() -> dict:
    return {"lead_status": {"$regex": "qualified", "$options": "i"}}


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
) -> Dict[str, List[Dict[str, Any]]]:
    """Distinct projects (split) and locations for Virtual Customer filter dropdowns."""
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

    return {
        "projects": [
            {"name": r["_id"], "count": r["count"]}
            for r in project_rows
            if r.get("_id")
        ],
        "locations": [
            {"name": r["_id"], "count": r["count"]}
            for r in location_rows
            if r.get("_id")
        ],
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
                "qualified": [{"$match": qualified_leads_filter()}, {"$count": "n"}],
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
        "qualified_leads": _facet_count(doc, "qualified"),
        "open_leads": _facet_count(doc, "open"),
        "lost_leads": _facet_count(doc, "lost"),
        "dormant_leads": _facet_count(doc, "dormant"),
    }
