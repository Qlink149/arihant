"""Shared MongoDB text search and query composition for lead list endpoints."""
import re
from typing import Any, Dict, List, Optional, Sequence


def escape_regex_literal(value: str) -> str:
    """Escape user/filter input for safe case-insensitive $regex matching."""
    return re.escape(value.strip())


def build_text_search_clause(term: Optional[str]) -> Dict[str, Any]:
    """Build $or / $expr clause matching common lead text fields."""
    if not term or not term.strip():
        return {}

    q = escape_regex_literal(term)
    return {
        "$or": [
            {"first_name": {"$regex": q, "$options": "i"}},
            {"last_name": {"$regex": q, "$options": "i"}},
            {"email": {"$regex": q, "$options": "i"}},
            {"phone": {"$regex": q, "$options": "i"}},
            {"normalized_phone": {"$regex": q, "$options": "i"}},
            {"work_phone": {"$regex": q, "$options": "i"}},
            {"normalized_work_phone": {"$regex": q, "$options": "i"}},
            {"lead_source": {"$regex": q, "$options": "i"}},
            {"original_source": {"$regex": q, "$options": "i"}},
            {"most_recent_source": {"$regex": q, "$options": "i"}},
            {"unit_size": {"$regex": q, "$options": "i"}},
            {"project": {"$regex": q, "$options": "i"}},
            {"assigned_to": {"$regex": q, "$options": "i"}},
            {"assigned_to_name": {"$regex": q, "$options": "i"}},
            {"presales_agent": {"$regex": q, "$options": "i"}},
            {
                "$expr": {
                    "$regexMatch": {
                        "input": {
                            "$trim": {
                                "input": {
                                    "$concat": [
                                        {"$ifNull": ["$first_name", ""]},
                                        " ",
                                        {"$ifNull": ["$last_name", ""]},
                                    ]
                                }
                            }
                        },
                        "regex": q,
                        "options": "i",
                    }
                }
            },
        ]
    }


def merge_query(base: Optional[Dict[str, Any]], *clauses: Dict[str, Any]) -> Dict[str, Any]:
    """Combine base filter and extra clauses with $and when needed."""
    parts: list[Dict[str, Any]] = []
    if base:
        parts.append(base)
    for clause in clauses:
        if clause:
            parts.append(clause)
    if not parts:
        return {}
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}


def case_insensitive_regex_filter(
    field: str, value: Optional[str], *, exact: bool = False
) -> Dict[str, Any]:
    """Build a single-field case-insensitive regex filter with escaped literal."""
    if not value or not value.strip():
        return {}
    pattern = escape_regex_literal(value)
    if exact:
        pattern = f"^{pattern}$"
    return {field: {"$regex": pattern, "$options": "i"}}


def case_insensitive_regex_or_filter(
    field: str,
    values: Optional[Sequence[str]],
    *,
    exact: bool = False,
) -> Dict[str, Any]:
    """Build $or clause for multiple case-insensitive regex matches on one field."""
    if not values:
        return {}
    clauses: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in values:
        if not raw or not str(raw).strip():
            continue
        key = str(raw).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        clause = case_insensitive_regex_filter(field, str(raw), exact=exact)
        if clause:
            clauses.append(clause)
    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$or": clauses}


def resolve_multi_filter_values(
    multi: Optional[Sequence[str]] = None,
    legacy: Optional[str] = None,
) -> List[str]:
    """Prefer explicit multi-value list; fall back to legacy single string."""
    if multi:
        return [str(v).strip() for v in multi if v and str(v).strip()]
    if legacy and str(legacy).strip():
        return [str(legacy).strip()]
    return []


def build_leads_list_query(
    base_filter: Optional[Dict[str, Any]] = None,
    *,
    temperature: Optional[str] = None,
    search: Optional[str] = None,
    project: Optional[str] = None,
    projects: Optional[Sequence[str]] = None,
    project_id: Optional[str] = None,
    budget: Optional[str] = None,
    budgets: Optional[Sequence[str]] = None,
    location: Optional[str] = None,
    locations: Optional[Sequence[str]] = None,
    intent: Optional[str] = None,
    vip: Optional[bool] = None,
    status: Optional[str] = None,
    statuses: Optional[Sequence[str]] = None,
    days_cutoff_iso: Optional[str] = None,
    created_at_from_iso: Optional[str] = None,
    created_at_to_iso: Optional[str] = None,
    updated_at_from_iso: Optional[str] = None,
    updated_at_to_iso: Optional[str] = None,
    sources: Optional[Sequence[str]] = None,
    source: Optional[str] = None,
    meta_qualified: Optional[bool] = None,
    site_visit_min: Optional[int] = None,
    site_visit_max: Optional[int] = None,
) -> Dict[str, Any]:
    """Compose a full leads query for list endpoints."""
    extra: list[Dict[str, Any]] = []

    project_values = resolve_multi_filter_values(projects, project)
    budget_values = resolve_multi_filter_values(budgets, budget)
    location_values = resolve_multi_filter_values(locations, location)
    status_values = resolve_multi_filter_values(statuses, status)
    source_values = resolve_multi_filter_values(sources, source)

    if project_id:
        extra.append({"project_id": project_id})
    if project_values:
        extra.append(case_insensitive_regex_or_filter("project", project_values))
    if temperature and temperature.lower() != "all":
        extra.append(case_insensitive_regex_filter("temperature", temperature, exact=True))
    if budget_values:
        extra.append(case_insensitive_regex_or_filter("budget", budget_values))
    if location_values:
        extra.append(case_insensitive_regex_or_filter("location", location_values))
    if source_values:
        extra.append(case_insensitive_regex_or_filter("lead_source", source_values))
    if meta_qualified is not None:
        extra.append({"meta_qualified": meta_qualified})
    if intent:
        extra.append({"intent": intent})
    if vip is not None:
        extra.append({"vip": vip})
    if status_values:
        extra.append(case_insensitive_regex_or_filter("lead_status", status_values, exact=True))
    if days_cutoff_iso:
        extra.append({"created_at": {"$gte": days_cutoff_iso}})
    if created_at_from_iso or created_at_to_iso:
        created_clause: Dict[str, Any] = {}
        if created_at_from_iso:
            created_clause["$gte"] = created_at_from_iso
        if created_at_to_iso:
            created_clause["$lte"] = created_at_to_iso
        extra.append({"created_at": created_clause})
    if updated_at_from_iso or updated_at_to_iso:
        updated_clause: Dict[str, Any] = {}
        if updated_at_from_iso:
            updated_clause["$gte"] = updated_at_from_iso
        if updated_at_to_iso:
            updated_clause["$lte"] = updated_at_to_iso
        extra.append({"updated_at": updated_clause})
    if site_visit_min is not None or site_visit_max is not None:
        sv_clause: Dict[str, Any] = {}
        if site_visit_min is not None:
            sv_clause["$gte"] = site_visit_min
        if site_visit_max is not None:
            sv_clause["$lte"] = site_visit_max
        extra.append({"site_visit_count": sv_clause})

    search_clause = build_text_search_clause(search)
    if search_clause:
        extra.append(search_clause)

    return merge_query(base_filter or {}, *extra)
