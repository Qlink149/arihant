import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from crm.core.state import db, get_current_user, get_time_greeting, utc_now
from crm.services.dashboard_scope import role_scope_filter
from crm.services.lead_search import merge_query
from crm.constants.lead_kpi import RNR_STATUS_REGEX, SITE_VISIT_STATUS_REGEX
from crm.constants.lead_status import CLOSED_LEAD_STATUS_REGEX
from crm.services.lead_analytics_queries import (
    DORMANT_INACTIVITY_DAYS,
    build_dashboard_base_query,
    build_dashboard_snapshot_query,
    count_dashboard_cohort_metrics,
    created_since_filter,
    merge_query_with_valid_projects,
    project_distribution_pipeline,
)
from crm.services.lead_overview_service import count_dashboard_operational_metrics


router = APIRouter()


def _nurturing_label_flag(label: str) -> Dict[str, Any]:
    """Count 1 when lead is Nurturing and temperature matches label (Hot/Warm)."""
    return {
        "$cond": [
            {
                "$and": [
                    {"$eq": ["$ls", "nurturing"]},
                    {"$eq": [{"$toLower": {"$ifNull": ["$temperature", ""]}}, label.lower()]},
                ]
            },
            1,
            0,
        ]
    }


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
                "hot": _nurturing_label_flag("hot"),
                "warm": _nurturing_label_flag("warm"),
                "cold": {"$literal": 0},
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
                                "regex": CLOSED_LEAD_STATUS_REGEX.pattern,
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
                    "$cond": [{"$regexMatch": {"input": "$ls", "regex": r"negotiat"}}, 1, 0]
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


async def _sales_managers_from_aggregation(
    scope_filter: Optional[Dict[str, Any]] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, int], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Sales aggregates: managers (no embedded leads), totals, by_status, by_project."""
    metrics_stages = _sales_metrics_stages()
    prefix: List[Dict[str, Any]] = [{"$match": scope_filter}] if scope_filter else []
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

    main_rows = await db.leads.aggregate(prefix + metrics_stages + [group_stage]).to_list(None)

    managers: List[Dict[str, Any]] = []
    totals = {
        "total": 0,
        "hot": 0,
        "warm": 0,
        "cold": 0,
        "negotiation": 0,
        "rnr": 0,
        "site_visits": 0,
        "deals_closed": 0,
    }

    for r in main_rows:
        name = r["_id"] or "Unassigned"
        total = int(r.get("total", 0))
        deals = int(r.get("deals_closed", 0))
        conv = round((deals / total) * 100) if total > 0 else 0
        la = r.get("last_active")
        last_active = ""
        if isinstance(la, datetime):
            last_active = la.astimezone(timezone.utc).isoformat()
        negotiation = int(r.get("negotiation", 0))
        managers.append(
            {
                "name": name,
                "total": total,
                "hot": int(r.get("hot", 0)),
                "warm": int(r.get("warm", 0)),
                "cold": int(r.get("cold", 0)),
                "rnr": int(r.get("rnr", 0)),
                "site_visits": int(r.get("site_visits", 0)),
                "deals_closed": deals,
                "contacted": int(r.get("contacted", 0)),
                "negotiation": negotiation,
                "conversion_rate": conv,
                "last_active": last_active,
                "leads": [],
            }
        )
        totals["total"] += total
        totals["hot"] += int(r.get("hot", 0))
        totals["warm"] += int(r.get("warm", 0))
        totals["cold"] += int(r.get("cold", 0))
        totals["negotiation"] += negotiation
        totals["rnr"] += int(r.get("rnr", 0))
        totals["site_visits"] += int(r.get("site_visits", 0))
        totals["deals_closed"] += deals

    managers.sort(key=lambda x: x["name"])

    status_pipeline = [
        {"$group": {"_id": "$lead_status", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 50},
    ]
    status_match = scope_filter or {}
    status_raw = await db.leads.aggregate([{"$match": status_match}] + status_pipeline).to_list(50)
    by_status = [{"name": (s["_id"] or "Unknown"), "count": s["count"]} for s in status_raw]

    project_pipeline = project_distribution_pipeline(merge_query_with_valid_projects(status_match))
    proj_raw = await db.leads.aggregate(project_pipeline).to_list(50)
    by_project = [{"name": (p["_id"] or "Unknown"), "count": p["count"]} for p in proj_raw]

    return managers, totals, by_status, by_project


@router.get("/analytics/dashboard")
async def get_dashboard_analytics(
    current_user: dict = Depends(get_current_user),
    days: Optional[int] = None,
    project: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
):
    scope = role_scope_filter(current_user)
    cohort_query = merge_query(
        scope,
        build_dashboard_base_query(
            days=days,
            created_from=created_from,
            created_to=created_to,
            project=project,
        ),
    )
    snapshot_query = merge_query(scope, build_dashboard_snapshot_query(project=project))

    operational_keys = (
        "missed_follow_up",
        "todays_site_visits",
        "rnr",
        "negotiation",
        "follow_up_today",
        "todays_leads",
    )
    operational_counts, cohort_counts = await asyncio.gather(
        count_dashboard_operational_metrics(snapshot_query, operational_keys),
        count_dashboard_cohort_metrics(cohort_query),
    )

    total_leads = cohort_counts["total_leads"]
    hot_leads = cohort_counts["hot_leads"]
    warm_leads = cohort_counts["warm_leads"]
    cold_leads = 0
    vip_leads = cohort_counts["vip_leads"]
    qualified = cohort_counts["qualified_leads"]
    open_leads = cohort_counts["open_leads"]
    lost = cohort_counts["lost_leads"]
    dormant_leads = cohort_counts["dormant_leads"]

    status_pipeline = [
        {"$match": cohort_query},
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
        {"$match": cohort_query},
        {"$group": {"_id": "$lead_source", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    sources = await db.leads.aggregate(source_pipeline).to_list(10)

    location_pipeline = [
        {"$match": cohort_query},
        {"$group": {"_id": "$location", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    locations = await db.leads.aggregate(location_pipeline).to_list(10)
    locations = [l for l in locations if l["_id"]]

    owner_pipeline = [
        {"$match": cohort_query},
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

    project_pipeline = project_distribution_pipeline(merge_query_with_valid_projects(cohort_query))
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
        "operational": operational_counts,
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
    scope = role_scope_filter(current_user)
    managers, totals, by_status, by_project = await _sales_managers_from_aggregation(scope or None)
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
    if current_user.get("role") not in ("admin", "manager"):
        own = (current_user.get("full_name") or "").strip()
        if name.strip() != own:
            raise HTTPException(status_code=403, detail="Access denied")
    scope = role_scope_filter(current_user)
    rep_expr = _rep_name_expression()
    match_expr = merge_query(scope, {"$expr": {"$eq": [rep_expr, name]}})
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
