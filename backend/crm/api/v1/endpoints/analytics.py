import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from crm.core.state import db, get_current_user, get_time_greeting, utc_now
from crm.services.dashboard_scope import role_scope_filter, sales_dashboard_scope_filter
from crm.services.lead_search import merge_query
from crm.constants.lead_kpi import RNR_STATUS_REGEX, SITE_VISIT_STATUS_REGEX
from crm.constants.lead_status import CLOSED_LEAD_STATUS_REGEX
from crm.services.sales_dashboard_filters import (
    CONTACTED_STATUS_REGEX,
    DEALS_LOST_STATUS_REGEX,
    DEALS_WON_STATUS_REGEX,
    NEGOTIATION_STATUS_REGEX,
    build_sales_metric_filter,
)
from crm.services.lead_analytics_queries import (
    DORMANT_INACTIVITY_DAYS,
    build_dashboard_base_query,
    build_dashboard_snapshot_query,
    count_dashboard_cohort_metrics,
    created_range_filter,
    created_since_filter,
    merge_query_with_valid_projects,
    project_distribution_pipeline,
    resolve_quarter_param,
    resolve_sales_period_filter,
)
from crm.services.lead_overview_service import count_dashboard_operational_metrics
from crm.services.site_visit_events import build_site_visit_report, resolve_report_window


router = APIRouter()

_SALES_AGG_CACHE: Dict[str, tuple[float, tuple]] = {}
_SALES_AGG_CACHE_TTL_SEC = 60


def _sales_cache_key(scope_filter: Optional[Dict[str, Any]]) -> str:
    return str(sorted((scope_filter or {}).items()))


async def _cached_sales_managers_from_aggregation(
    scope_filter: Optional[Dict[str, Any]] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, int], List[Dict[str, Any]], List[Dict[str, Any]]]:
    key = _sales_cache_key(scope_filter)
    now = utc_now().timestamp()
    cached = _SALES_AGG_CACHE.get(key)
    if cached and (now - cached[0]) < _SALES_AGG_CACHE_TTL_SEC:
        return cached[1]
    result = await _sales_managers_from_aggregation(scope_filter)
    _SALES_AGG_CACHE[key] = (now, result)
    return result


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


def _rep_id_expression() -> Dict[str, Any]:
    """batch2 item 1: authoritative grouping key for per-agent dashboards -
    assigned_user_id (see Batch 1 #55), never a name field. The empty-string
    bucket is leads with no owner id at all, resolved to the "Unassigned"
    display name after aggregation (dashboard_scope.resolve_owner_names)."""
    return {"$ifNull": ["$assigned_user_id", ""]}


def _sales_metrics_stages() -> List[Dict[str, Any]]:
    """$addFields stages: rep_id, ls, then metric flags (aligned with seeded UI statuses)."""
    rep_id_expr = _rep_id_expression()
    return [
        {"$addFields": {"rep_id": rep_id_expr}},
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
                            "$and": [
                                {
                                    "$or": [
                                        {"$regexMatch": {"input": "$ls", "regex": RNR_STATUS_REGEX}},
                                        {"$eq": ["$ls", "rnr"]},
                                    ]
                                },
                                {
                                    "$not": [
                                        {
                                            "$regexMatch": {
                                                "input": "$ls",
                                                "regex": CLOSED_LEAD_STATUS_REGEX.pattern,
                                            }
                                        }
                                    ]
                                },
                            ]
                        },
                        1,
                        0,
                    ]
                },
                "site_visits": {
                    "$cond": [{"$regexMatch": {"input": "$ls", "regex": SITE_VISIT_STATUS_REGEX}}, 1, 0]
                },
                "deals_won": {
                    "$cond": [
                        {
                            "$regexMatch": {
                                "input": "$ls",
                                "regex": DEALS_WON_STATUS_REGEX,
                            }
                        },
                        1,
                        0,
                    ]
                },
                "deals_lost": {
                    "$cond": [
                        {
                            "$regexMatch": {
                                "input": "$ls",
                                "regex": DEALS_LOST_STATUS_REGEX,
                            }
                        },
                        1,
                        0,
                    ]
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
                        {"$regexMatch": {"input": "$ls", "regex": CONTACTED_STATUS_REGEX}},
                        1,
                        0,
                    ]
                },
                "negotiation": {
                    "$cond": [
                        {"$regexMatch": {"input": "$ls", "regex": NEGOTIATION_STATUS_REGEX}},
                        1,
                        0,
                    ]
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


def missed_pickups_pipeline(scope_filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Per-agent "missed pickups" (SOP section 10, Agent Scorecard additional metric).

    `pool_assignment_history` is the ordered list of agents the router has given a
    lead to; the last entry is the latest router assignment. Every EARLIER entry is
    an agent the lead was routed away from by the 1-hour (New) or 7-day (Contacted)
    no-activity rules, or by the RNR day-4 transfer - i.e. leads that agent did not
    action in time. Visibility only: it never drives an automation.
    """
    match: Dict[str, Any] = {"pool_assignment_history.1": {"$exists": True}}
    if scope_filter:
        match = {"$and": [scope_filter, match]}
    return [
        {"$match": match},
        {
            "$project": {
                "missed": {
                    "$slice": [
                        "$pool_assignment_history",
                        {"$subtract": [{"$size": "$pool_assignment_history"}, 1]},
                    ]
                }
            }
        },
        {"$unwind": "$missed"},
        {"$group": {"_id": "$missed", "missed_pickups": {"$sum": 1}}},
    ]


async def _sales_managers_from_aggregation(
    scope_filter: Optional[Dict[str, Any]] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, int], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Sales aggregates: managers (no embedded leads), totals, by_status, by_project."""
    metrics_stages = _sales_metrics_stages()
    prefix: List[Dict[str, Any]] = [{"$match": scope_filter}] if scope_filter else []
    group_stage = {
        "$group": {
            "_id": "$rep_id",
            "total": {"$sum": 1},
            "hot": {"$sum": "$hot"},
            "warm": {"$sum": "$warm"},
            "cold": {"$sum": "$cold"},
            "rnr": {"$sum": "$rnr"},
            "site_visits": {"$sum": "$site_visits"},
            "deals_won": {"$sum": "$deals_won"},
            "deals_lost": {"$sum": "$deals_lost"},
            "deals_closed": {"$sum": "$deals_closed"},
            "contacted": {"$sum": "$contacted"},
            "negotiation": {"$sum": "$negotiation"},
            "last_active": {"$max": "$activity_dt"},
        }
    }

    main_rows = await db.leads.aggregate(prefix + metrics_stages + [group_stage]).to_list(None)

    # batch2 item 1: rows are keyed by assigned_user_id; resolve to each
    # user's CURRENT display name (dashboard_scope.resolve_owner_names) -
    # the id is authoritative, the name is display only.
    from crm.services.dashboard_scope import resolve_owner_names

    owner_ids = [r["_id"] for r in main_rows if r.get("_id")]
    names_by_id = await resolve_owner_names(owner_ids)

    managers: List[Dict[str, Any]] = []
    totals = {
        "total": 0,
        "hot": 0,
        "warm": 0,
        "cold": 0,
        "negotiation": 0,
        "rnr": 0,
        "site_visits": 0,
        "deals_won": 0,
        "deals_lost": 0,
        "deals_closed": 0,
    }

    for r in main_rows:
        owner_id = r["_id"] or ""
        name = names_by_id.get(owner_id) or "Unassigned"
        total = int(r.get("total", 0))
        deals_won = int(r.get("deals_won", 0))
        deals_lost = int(r.get("deals_lost", 0))
        deals = int(r.get("deals_closed", 0))
        conv = round((deals_won / total) * 100) if total > 0 else 0
        la = r.get("last_active")
        last_active = ""
        if isinstance(la, datetime):
            last_active = la.astimezone(timezone.utc).isoformat()
        negotiation = int(r.get("negotiation", 0))
        managers.append(
            {
                "name": name,
                "id": owner_id or None,
                "total": total,
                "hot": int(r.get("hot", 0)),
                "warm": int(r.get("warm", 0)),
                "cold": int(r.get("cold", 0)),
                "rnr": int(r.get("rnr", 0)),
                "site_visits": int(r.get("site_visits", 0)),
                "deals_won": deals_won,
                "deals_lost": deals_lost,
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
        totals["deals_won"] += deals_won
        totals["deals_lost"] += deals_lost
        totals["deals_closed"] += deals

    # batch2 item 1: two different owner_ids can both resolve to the same
    # display name (e.g. no owner id at all, and a deleted user's id both
    # fall back to "Unassigned") - merge those rows so the frontend never
    # sees two entries with the same name/key.
    _NUMERIC_KEYS = (
        "total", "hot", "warm", "cold", "rnr", "site_visits",
        "deals_won", "deals_lost", "deals_closed", "contacted", "negotiation",
    )
    merged_by_name: Dict[str, Dict[str, Any]] = {}
    for m in managers:
        existing = merged_by_name.get(m["name"])
        if not existing:
            merged_by_name[m["name"]] = m
            continue
        for k in _NUMERIC_KEYS:
            existing[k] += m[k]
        existing["conversion_rate"] = (
            round((existing["deals_won"] / existing["total"]) * 100) if existing["total"] > 0 else 0
        )
        if not existing.get("last_active") or (m.get("last_active") and m["last_active"] > existing["last_active"]):
            existing["last_active"] = m["last_active"]
        if not existing.get("id"):
            existing["id"] = m.get("id")
    managers = list(merged_by_name.values())

    missed_rows = await db.leads.aggregate(missed_pickups_pipeline(scope_filter)).to_list(None)
    missed_by_id = {r["_id"]: int(r["missed_pickups"]) for r in missed_rows if r.get("_id")}
    for m in managers:
        m["missed_pickups"] = missed_by_id.get(m.get("id"), 0) if m.get("id") else 0

    # SOP section 8: agents who are marked inactive but still own leads stay on the
    # scorecard, marked as inactive. Owners that are not a registered user get None.
    owner_ids = [m["id"] for m in managers if m.get("id")]
    active_by_id: Dict[str, bool] = {}
    if owner_ids:
        for u in await db.users.find({"id": {"$in": owner_ids}}, {"_id": 0, "id": 1, "is_active": 1}).to_list(len(owner_ids)):
            active_by_id[u["id"]] = u.get("is_active", True) is not False
    for m in managers:
        m["is_active"] = active_by_id.get(m.get("id")) if m.get("id") else None

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
    # NURTURE_LABELS only defines Hot/Warm — no Cold temperature in this CRM.
    cold_leads = 0
    vip_leads = cohort_counts["vip_leads"]
    qualified = cohort_counts["active_pipeline_leads"]
    open_leads = cohort_counts["open_leads"]
    lost = cohort_counts["lost_leads"]
    dormant_leads = cohort_counts["dormant_leads"]

    breakdown_facet = [
        {"$match": cohort_query},
        {
            "$facet": {
                "statuses": [
                    {
                        "$group": {
                            "_id": {"$toLower": {"$trim": {"input": {"$ifNull": ["$lead_status", "unknown"]}}}},
                            "count": {"$sum": 1},
                            "label": {"$first": "$lead_status"},
                        }
                    },
                    {"$sort": {"count": -1}},
                    {"$limit": 20},
                ],
                "sources": [
                    {"$group": {"_id": "$lead_source", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": 10},
                ],
                "locations": [
                    {"$group": {"_id": "$location", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": 10},
                ],
                "owners": [
                    # batch2 item 1: group by the authoritative assigned_user_id
                    # (Batch 1 #55), not name fields - resolved to a display
                    # name after the aggregation (see below), so a phantom
                    # name-drift row (e.g. "Roshini") can never appear here.
                    {"$group": {"_id": {"$ifNull": ["$assigned_user_id", ""]}, "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": 10},
                ],
            }
        },
    ]
    breakdown_rows, projects = await asyncio.gather(
        db.leads.aggregate(breakdown_facet).to_list(1),
        db.leads.aggregate(project_distribution_pipeline(merge_query_with_valid_projects(cohort_query))).to_list(50),
    )
    breakdown_doc = breakdown_rows[0] if breakdown_rows else {}
    statuses = breakdown_doc.get("statuses") or []
    sources = breakdown_doc.get("sources") or []
    locations = [l for l in (breakdown_doc.get("locations") or []) if l.get("_id")]
    owners = breakdown_doc.get("owners") or []
    # batch2 item 1: resolve assigned_user_id -> current display name.
    from crm.services.dashboard_scope import merge_owner_count_rows_by_name, resolve_owner_names

    owner_names = await resolve_owner_names([o["_id"] for o in owners if o.get("_id")])
    sales_owners_out = merge_owner_count_rows_by_name(owners, owner_names)

    return {
        "greeting": f"{get_time_greeting()}, {current_user['full_name'].split()[0]}",
        "total_leads": total_leads,
        "hot_leads": hot_leads,
        "warm_leads": warm_leads,
        "cold_leads": cold_leads,
        "vip_leads": vip_leads,
        "active_pipeline_leads": qualified,
        "qualified_leads": qualified,
        "open_leads": open_leads,
        "lost_leads": lost,
        "dormant_leads": dormant_leads,
        "operational": operational_counts,
        "lead_sources": [{"name": s["_id"] or "Unknown", "count": s["count"]} for s in sources],
        "locations": [{"name": l["_id"] or "Unknown", "count": l["count"]} for l in locations],
        "projects": [{"name": p["_id"] or "Unknown", "count": p["count"]} for p in projects],
        "sales_owners": sales_owners_out,
        "status_breakdown": [
            {"name": (s.get("label") or s["_id"] or "Unknown"), "count": s["count"]} for s in statuses
        ],
        "status_distribution": {"qualified": qualified, "open": open_leads, "lost": lost},
    }


@router.get("/analytics/sales-dashboard")
async def get_sales_dashboard_analytics(
    current_user: dict = Depends(get_current_user),
    quarter: Optional[str] = Query(None, description="current, all, or YYYY-Qn (e.g. 2026-Q1)"),
    days: Optional[int] = Query(None, ge=1),
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
):
    try:
        period_filter, period_label = resolve_sales_period_filter(
            quarter=quarter,
            days=days,
            created_from=created_from,
            created_to=created_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scope = sales_dashboard_scope_filter(current_user)
    query_base = merge_query(scope, period_filter) if period_filter else scope
    managers, totals, by_status, by_project = await _cached_sales_managers_from_aggregation(query_base or None)
    return {
        "managers": managers,
        "totals": totals,
        "by_status": by_status,
        "by_project": by_project,
        "period_label": period_label,
    }


@router.get("/analytics/sales-dashboard/ranking")
async def get_sales_dashboard_ranking(
    current_user: dict = Depends(get_current_user),
    quarter: Optional[str] = Query(None, description="current, all, or YYYY-Qn (e.g. 2026-Q1)"),
    days: Optional[int] = Query(None, ge=1),
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
):
    """Agent performance ranking for leads created in the selected period."""
    try:
        period_filter, period_label = resolve_sales_period_filter(
            quarter=quarter,
            days=days,
            created_from=created_from,
            created_to=created_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scope = sales_dashboard_scope_filter(current_user) or {}
    query_base = merge_query(scope, period_filter) if period_filter else scope

    managers, _, _, _ = await _cached_sales_managers_from_aggregation(query_base or None)
    ranked = [m for m in managers if m.get("name") != "Unassigned"]
    ranked.sort(key=lambda x: (-x["conversion_rate"], -x["deals_won"], x["name"]))

    return {
        "period_label": period_label,
        "managers": ranked,
    }


@router.get("/analytics/sales-dashboard/rep-leads")
async def get_sales_rep_leads(
    name: str = Query(..., min_length=1, description="Representative display name (must match dashboard row)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(150, ge=1, le=500),
    metric: Optional[str] = Query(
        None,
        description="Pipeline filter: contacted, rnr, site_visits, negotiation, deals_won, deals_lost",
    ),
    quarter: Optional[str] = Query(None, description="current, all, or YYYY-Qn (e.g. 2026-Q1)"),
    days: Optional[int] = Query(None, ge=1),
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Paginated leads for a sales rep; same assignment and period logic as sales dashboard."""
    if current_user.get("role") not in ("admin", "manager", "general_manager"):
        own = (current_user.get("full_name") or "").strip()
        if name.strip() != own:
            raise HTTPException(status_code=403, detail="Access denied")
    try:
        period_filter, _ = resolve_sales_period_filter(
            quarter=quarter,
            days=days,
            created_from=created_from,
            created_to=created_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        metric_filter = build_sales_metric_filter(metric)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scope = sales_dashboard_scope_filter(current_user)
    # batch2 item 1: match by the same authoritative assigned_user_id the
    # dashboard now groups by (Batch 1 #55), not the drifted name fields -
    # otherwise this drill-down could show a different lead set than the
    # count on the row the user clicked.
    from crm.services.dashboard_scope import resolve_sales_owner_ids

    if name.strip().lower() == "unassigned":
        owner_clause: Dict[str, Any] = {
            "$or": [
                {"assigned_user_id": None},
                {"assigned_user_id": ""},
                {"assigned_user_id": {"$exists": False}},
            ]
        }
    else:
        resolved_ids = await resolve_sales_owner_ids([name])
        if not resolved_ids:
            # Not a real user (e.g. a stale legacy name) - matches nothing,
            # same as the dashboard row it would have come from not existing.
            owner_clause = {"id": "__no_such_user__"}
        else:
            owner_clause = {"assigned_user_id": {"$in": resolved_ids}}
    match_expr = merge_query(
        scope,
        period_filter if period_filter else {},
        owner_clause,
        metric_filter if metric_filter else {},
    )
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

    return {
        "name": name,
        "total": total,
        "skip": skip,
        "limit": limit,
        "metric": metric,
        "leads": leads_out,
    }


@router.get("/analytics/site-visits")
async def get_site_visit_report(
    preset: Optional[str] = Query(
        None, description="week | month | quarter — overrides date_from/date_to when set"
    ),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD, IST calendar day, inclusive"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD, IST calendar day, inclusive"),
    sales_owner_id: Optional[str] = Query(None, description="Filter to one sales owner's visits"),
    current_user: dict = Depends(get_current_user),
):
    """#53/#54: Permanent site-visit completion report — totals by project.

    Reads the append-only `site_visit_events` log (survives later status changes),
    not the current lead status. Admin/manager/GM see org-wide (or one rep via
    `sales_owner_id`); reps are always scoped to their own visits.
    """
    from crm.constants.roles import is_org_editor

    effective_owner_id = sales_owner_id
    if not is_org_editor(current_user.get("role")):
        effective_owner_id = current_user.get("id")

    window = resolve_report_window(preset=preset, date_from=date_from, date_to=date_to)
    report = await build_site_visit_report(window=window, sales_owner_id=effective_owner_id)

    return {
        "preset": preset,
        "date_from": date_from,
        "date_to": date_to,
        "sales_owner_id": effective_owner_id,
        **report,
    }
