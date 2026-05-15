from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from crm.core.state import db, get_current_user, get_time_greeting, utc_now
from crm.constants.lead_kpi import (
    DEALS_CLOSED_STATUS_REGEX,
    RNR_STATUS_REGEX,
    SITE_VISIT_STATUS_REGEX,
)


router = APIRouter()

DORMANT_INACTIVITY_DAYS = 7

# Dashboard project distribution: exclude placeholders (case-insensitive match on whole string)
_INVALID_PROJECT_REGEX = {"$regex": r"^(?i)\s*(unknown|na|n/a|others|null)\s*$"}


def _created_since_filter(days: int) -> dict:
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


def _stale_activity_clause(cutoff: datetime, cutoff_iso: str) -> dict:
    """Lead has had no meaningful update in DORMANT_INACTIVITY_DAYS (prefer updated_at_dt / updated_at, else created)."""
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


def _non_dormant_terminal_status_clause() -> dict:
    """Option B: exclude Won, Lost, Advance Paid, Closed, Booked, Dropped, Unqualified (whole status, case-insensitive)."""
    return {
        "$nor": [
            {
                "lead_status": {
                    "$regex": r"(?i)^\s*(won|lost|advance\s*paid|closed|booked|dropped|unqualified)\s*$",
                }
            }
        ]
    }


def _dormant_leads_query(base_query: dict) -> dict:
    cutoff = utc_now() - timedelta(days=DORMANT_INACTIVITY_DAYS)
    cutoff_iso = cutoff.isoformat()
    return {"$and": [base_query, _stale_activity_clause(cutoff, cutoff_iso), _non_dormant_terminal_status_clause()]}


def _merge_query_with_valid_projects(query: dict) -> dict:
    """Combine time/user filter with valid project names for distribution charts."""
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


def _rep_name_expression() -> Dict[str, Any]:
    """Mirror Python: assigned_to_name or assigned_to or presales_agent or 'Unassigned' (empty strings skip)."""
    return {
        "$let": {
            "vars": {
                "n1": {"$toString": {"$ifNull": ["$assigned_to_name", ""]}},
                "n2": {"$toString": {"$ifNull": ["$assigned_to", ""]}},
                "n3": {"$toString": {"$ifNull": ["$presales_agent", ""]}},
            },
            "in": {
                "$cond": [
                    {"$gt": [{"$strLenCP": {"$trim": {"input": "$$n1"}}}, 0]},
                    {"$trim": {"input": "$$n1"}},
                    {
                        "$cond": [
                            {"$gt": [{"$strLenCP": {"$trim": {"input": "$$n2"}}}, 0]},
                            {"$trim": {"input": "$$n2"}},
                            {
                                "$cond": [
                                    {"$gt": [{"$strLenCP": {"$trim": {"input": "$$n3"}}}, 0]},
                                    {"$trim": {"input": "$$n3"}},
                                    "Unassigned",
                                ]
                            },
                        ]
                    },
                ]
            },
        }
    }


def _sales_metrics_stages() -> List[Dict[str, Any]]:
    """$addFields stages: rep, ls, then metric flags (aligned with seeded UI statuses)."""
    rep_expr = _rep_name_expression()
    return [
        {"$addFields": {"rep": rep_expr}},
        {
            "$addFields": {
                "ls": {"$toLower": {"$trim": {"input": {"$ifNull": ["$lead_status", ""]}}}},
                "ofs": {"$toLower": {"$trim": {"input": {"$ifNull": ["$original_fw_status", ""]}}}},
            }
        },
        {
            "$addFields": {
                "hot": {"$cond": [{"$eq": [{"$toLower": {"$ifNull": ["$temperature", ""]}}, "hot"]}, 1, 0]},
                "warm": {"$cond": [{"$eq": [{"$toLower": {"$ifNull": ["$temperature", ""]}}, "warm"]}, 1, 0]},
                "cold": {"$cond": [{"$eq": [{"$toLower": {"$ifNull": ["$temperature", ""]}}, "cold"]}, 1, 0]},
                "rnr": {
                    "$cond": [
                        {
                            "$or": [
                                {"$eq": ["$is_rnr", True]},
                                {"$regexMatch": {"input": "$ls", "regex": RNR_STATUS_REGEX}},
                                {"$regexMatch": {"input": "$ofs", "regex": RNR_STATUS_REGEX}},
                            ]
                        },
                        1,
                        0,
                    ]
                },
                "site_visits": {
                    "$cond": [{"$regexMatch": {"input": "$ls", "regex": SITE_VISIT_STATUS_REGEX}}, 1, 0]
                },
                "deals_closed": {
                    "$cond": [
                        {
                            "$regexMatch": {
                                "input": "$ls",
                                "regex": DEALS_CLOSED_STATUS_REGEX,
                            }
                        },
                        1,
                        0,
                    ]
                },
                "contacted": {
                    "$cond": [
                        {"$gt": [{"$size": {"$ifNull": ["$context_updates", []]}}, 1]},
                        1,
                        0,
                    ]
                },
                "negotiation": {
                    "$cond": [{"$regexMatch": {"input": "$ls", "regex": r"^negotiation$"}}, 1, 0]
                },
                "activity_dt": {
                    "$ifNull": [
                        "$updated_at_dt",
                        {
                            "$ifNull": [
                                {
                                    "$convert": {
                                        "input": "$updated_at",
                                        "to": "date",
                                        "onError": None,
                                        "onNull": None,
                                    }
                                },
                                {
                                    "$ifNull": [
                                        "$created_at_dt",
                                        {
                                            "$convert": {
                                                "input": "$created_at",
                                                "to": "date",
                                                "onError": None,
                                                "onNull": None,
                                            }
                                        },
                                    ]
                                },
                            ]
                        },
                    ]
                },
            }
        },
    ]


async def _sales_managers_from_aggregation() -> tuple[List[Dict[str, Any]], Dict[str, int], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Full-collection sales aggregates: managers (no embedded leads), totals, by_status, by_project."""
    metrics_stages = _sales_metrics_stages()
    group_stage = {
        "$group": {
            "_id": "$rep",
            "total": {"$sum": 1},
            "hot": {"$sum": "$hot"},
            "warm": {"$sum": "$warm"},
            "cold": {"$sum": "$cold"},
            "rnr": {"$sum": "$rnr"},
            "site_visits": {"$sum": "$site_visits"},
            "deals_closed": {"$sum": "$deals_closed"},
            "contacted": {"$sum": "$contacted"},
            "negotiation": {"$sum": "$negotiation"},
            "last_active": {"$max": "$activity_dt"},
        }
    }

    main_rows = await db.leads.aggregate(metrics_stages + [group_stage]).to_list(None)

    dormant_q = _dormant_leads_query({})
    dormant_rows = await db.leads.aggregate(
        [
            {"$match": dormant_q},
            {"$addFields": {"rep": _rep_name_expression()}},
            {"$group": {"_id": "$rep", "dormant": {"$sum": 1}}},
        ]
    ).to_list(None)
    dormant_by_rep = {r["_id"]: r["dormant"] for r in dormant_rows}

    managers: List[Dict[str, Any]] = []
    totals = {"total": 0, "hot": 0, "warm": 0, "cold": 0, "dormant": 0, "rnr": 0, "site_visits": 0, "deals_closed": 0}

    for r in main_rows:
        name = r["_id"] or "Unassigned"
        dcount = int(dormant_by_rep.get(name, 0))
        total = int(r.get("total", 0))
        deals = int(r.get("deals_closed", 0))
        conv = round((deals / total) * 100) if total > 0 else 0
        la = r.get("last_active")
        last_active = ""
        if isinstance(la, datetime):
            last_active = la.astimezone(timezone.utc).isoformat()
        managers.append(
            {
                "name": name,
                "total": total,
                "hot": int(r.get("hot", 0)),
                "warm": int(r.get("warm", 0)),
                "cold": int(r.get("cold", 0)),
                "dormant": dcount,
                "rnr": int(r.get("rnr", 0)),
                "site_visits": int(r.get("site_visits", 0)),
                "deals_closed": deals,
                "contacted": int(r.get("contacted", 0)),
                "negotiation": int(r.get("negotiation", 0)),
                "conversion_rate": conv,
                "last_active": last_active,
                "leads": [],
            }
        )
        totals["total"] += total
        totals["hot"] += int(r.get("hot", 0))
        totals["warm"] += int(r.get("warm", 0))
        totals["cold"] += int(r.get("cold", 0))
        totals["dormant"] += dcount
        totals["rnr"] += int(r.get("rnr", 0))
        totals["site_visits"] += int(r.get("site_visits", 0))
        totals["deals_closed"] += deals

    managers.sort(key=lambda x: x["name"])

    status_pipeline = [
        {"$group": {"_id": "$lead_status", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 50},
    ]
    status_raw = await db.leads.aggregate([{"$match": {}}] + status_pipeline).to_list(50)
    by_status = [{"name": (s["_id"] or "Unknown"), "count": s["count"]} for s in status_raw]

    project_pipeline = [
        {"$match": _merge_query_with_valid_projects({})},
        {"$group": {"_id": "$project", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 50},
    ]
    proj_raw = await db.leads.aggregate(project_pipeline).to_list(50)
    by_project = [{"name": (p["_id"] or "Unknown"), "count": p["count"]} for p in proj_raw]

    return managers, totals, by_status, by_project


@router.get("/analytics/dashboard")
async def get_dashboard_analytics(current_user: dict = Depends(get_current_user), days: Optional[int] = None):
    query: dict = {}
    if days:
        query = _created_since_filter(days)

    total_leads = await db.leads.count_documents(query)

    hot_leads = await db.leads.count_documents({**query, "temperature": {"$regex": "^hot$", "$options": "i"}})
    warm_leads = await db.leads.count_documents({**query, "temperature": {"$regex": "^warm$", "$options": "i"}})
    cold_leads = await db.leads.count_documents({**query, "temperature": {"$regex": "^cold$", "$options": "i"}})

    vip_leads = await db.leads.count_documents({**query, "vip": True})

    qualified = await db.leads.count_documents({**query, "lead_status": {"$regex": "qualified", "$options": "i"}})
    open_leads = await db.leads.count_documents({**query, "lead_status": {"$regex": "open|new|contacted", "$options": "i"}})
    lost = await db.leads.count_documents({**query, "lead_status": {"$regex": "lost|dropped|unqualified", "$options": "i"}})

    dormant_leads = await db.leads.count_documents(_dormant_leads_query(query))

    status_pipeline = [
        {"$match": query},
        {
            "$group": {
                "_id": {"$toLower": {"$trim": {"input": {"$ifNull": ["$lead_status", "unknown"]}}}},
                "count": {"$sum": 1},
                "label": {"$first": "$lead_status"},
            }
        },
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    statuses = await db.leads.aggregate(status_pipeline).to_list(20)

    source_pipeline = [
        {"$match": query},
        {"$group": {"_id": "$lead_source", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    sources = await db.leads.aggregate(source_pipeline).to_list(10)

    location_pipeline = [
        {"$match": query},
        {"$group": {"_id": "$location", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    locations = await db.leads.aggregate(location_pipeline).to_list(10)
    locations = [l for l in locations if l["_id"]]

    owner_pipeline = [
        {"$match": query},
        {
            "$group": {
                "_id": {
                    "$ifNull": [
                        "$assigned_to_name",
                        {"$ifNull": ["$assigned_to", "$presales_agent"]},
                    ]
                },
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    owners = await db.leads.aggregate(owner_pipeline).to_list(10)

    project_pipeline = [
        {"$match": _merge_query_with_valid_projects(query)},
        {"$group": {"_id": "$project", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 50},
    ]
    projects = await db.leads.aggregate(project_pipeline).to_list(50)

    return {
        "greeting": f"{get_time_greeting()}, {current_user['full_name'].split()[0]}",
        "total_leads": total_leads,
        "hot_leads": hot_leads,
        "warm_leads": warm_leads,
        "cold_leads": cold_leads,
        "vip_leads": vip_leads,
        "qualified_leads": qualified,
        "open_leads": open_leads,
        "lost_leads": lost,
        "dormant_leads": dormant_leads,
        "lead_sources": [{"name": s["_id"] or "Unknown", "count": s["count"]} for s in sources],
        "locations": [{"name": l["_id"] or "Unknown", "count": l["count"]} for l in locations],
        "projects": [{"name": p["_id"] or "Unknown", "count": p["count"]} for p in projects],
        "sales_owners": [{"name": o["_id"] or "Unassigned", "count": o["count"]} for o in owners],
        "status_breakdown": [
            {"name": (s.get("label") or s["_id"] or "Unknown"), "count": s["count"]} for s in statuses
        ],
        "status_distribution": {"qualified": qualified, "open": open_leads, "lost": lost},
    }


@router.get("/analytics/sales-dashboard")
async def get_sales_dashboard_analytics(current_user: dict = Depends(get_current_user)):
    managers, totals, by_status, by_project = await _sales_managers_from_aggregation()
    return {
        "managers": managers,
        "totals": totals,
        "by_status": by_status,
        "by_project": by_project,
    }


@router.get("/analytics/sales-dashboard/rep-leads")
async def get_sales_rep_leads(
    name: str = Query(..., min_length=1, description="Representative display name (must match dashboard row)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(150, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Paginated leads for a sales rep; same assignment logic as sales dashboard."""
    rep_expr = _rep_name_expression()
    match_expr = {"$expr": {"$eq": [rep_expr, name]}}
    total = await db.leads.count_documents(match_expr)

    projection = {
        "_id": 0,
        "id": 1,
        "first_name": 1,
        "last_name": 1,
        "project": 1,
        "temperature": 1,
        "lead_status": 1,
        "updated_at": 1,
        "created_at": 1,
        "context_updates": 1,
    }
    cursor = (
        db.leads.find(match_expr, projection)
        .sort([("updated_at_dt", -1), ("updated_at", -1), ("created_at_dt", -1)])
        .skip(skip)
        .limit(limit)
    )
    leads_out: List[Dict[str, Any]] = []
    async for lead in cursor:
        cu = lead.get("context_updates") or []
        leads_out.append(
            {
                "id": lead.get("id"),
                "first_name": lead.get("first_name"),
                "last_name": lead.get("last_name"),
                "project": lead.get("project"),
                "temperature": lead.get("temperature"),
                "lead_status": lead.get("lead_status"),
                "updated_at": lead.get("updated_at"),
                "created_at": lead.get("created_at"),
                "context_updates_count": len(cu),
            }
        )

    return {"name": name, "total": total, "skip": skip, "limit": limit, "leads": leads_out}
