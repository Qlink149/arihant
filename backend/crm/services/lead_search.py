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


def build_exact_phone_lookup_queries(raw: str) -> List[Dict[str, Any]]:
    """
    Ordered Mongo filters for full-phone exact lookup.

    1) Exact match on the typed value against phone / work_phone
    2) Fallback: normalized last-10 digits on normalized_phone / phone digit forms

    Used by /leads/exact-lookup so reps can grant view access without changing
    the scoped regex list search behaviour.
    """
    from crm.utils.helpers import normalize_phone

    term = (raw or "").strip()
    if not term:
        return []

    queries: List[Dict[str, Any]] = []
    typed_exact = {
        "$or": [
            case_insensitive_regex_filter("phone", term, exact=True),
            case_insensitive_regex_filter("work_phone", term, exact=True),
        ]
    }
    # Drop empty $or arms if somehow empty (should not happen for non-empty term)
    typed_exact["$or"] = [c for c in typed_exact["$or"] if c]
    if typed_exact["$or"]:
        queries.append(typed_exact)

    digits = re.sub(r"\D", "", term)
    normalized = normalize_phone(term)
    fallback_or: List[Dict[str, Any]] = []
    if normalized and len(normalized) == 10:
        fallback_or.append({"normalized_phone": normalized})
        fallback_or.append(case_insensitive_regex_filter("phone", normalized, exact=True))
        fallback_or.append(case_insensitive_regex_filter("work_phone", normalized, exact=True))
        # Common stored forms: +<normalized>, 0<normalized>
        fallback_or.append(case_insensitive_regex_filter("phone", f"+{normalized}", exact=True))
        fallback_or.append(case_insensitive_regex_filter("work_phone", f"+{normalized}", exact=True))
    if digits and digits != normalized:
        fallback_or.append(case_insensitive_regex_filter("phone", digits, exact=True))
        fallback_or.append(case_insensitive_regex_filter("work_phone", digits, exact=True))
        fallback_or.append(case_insensitive_regex_filter("phone", f"+{digits}", exact=True))
        fallback_or.append(case_insensitive_regex_filter("work_phone", f"+{digits}", exact=True))

    # Deduplicate identical filter dicts while preserving order
    seen: set[str] = set()
    unique_fallback: List[Dict[str, Any]] = []
    for clause in fallback_or:
        key = repr(clause)
        if key in seen:
            continue
        seen.add(key)
        unique_fallback.append(clause)
    if unique_fallback:
        queries.append({"$or": unique_fallback})
    return queries


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


def build_project_match_filter(values: Optional[Sequence[str]]) -> Dict[str, Any]:
    """
    Match leads by project name against scalar `project` and/or `projects[]` array.

    Each selected value matches if either field contains it (case-insensitive regex).
    """
    if not values:
        return {}
    per_value: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in values:
        if not raw or not str(raw).strip():
            continue
        key = str(raw).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        if key == "all":
            continue
        pattern = escape_regex_literal(str(raw).strip())
        per_value.append(
            {
                "$or": [
                    {"project": {"$regex": pattern, "$options": "i"}},
                    {"projects": {"$regex": pattern, "$options": "i"}},
                ]
            }
        )
    if not per_value:
        return {}
    if len(per_value) == 1:
        return per_value[0]
    return {"$or": per_value}


_SALES_OWNER_FIELDS = ("assigned_to", "assigned_to_name", "presales_agent")


def build_sales_owners_filter(values: Optional[Sequence[str]]) -> Dict[str, Any]:
    """
    Match leads whose sales owner is any of the given names.

    Checks assigned_to, assigned_to_name, and presales_agent (exact, case-insensitive)
    because older imports store the owner in different fields.
    """
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
        for field in _SALES_OWNER_FIELDS:
            clause = case_insensitive_regex_filter(field, str(raw).strip(), exact=True)
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
    re_enquiry: Optional[bool] = None,
    status: Optional[str] = None,
    statuses: Optional[Sequence[str]] = None,
    days_cutoff_iso: Optional[str] = None,
    created_at_from_iso: Optional[str] = None,
    created_at_to_iso: Optional[str] = None,
    updated_at_from_iso: Optional[str] = None,
    updated_at_to_iso: Optional[str] = None,
    sources: Optional[Sequence[str]] = None,
    source: Optional[str] = None,
    sales_owners: Optional[Sequence[str]] = None,
    sales_owner: Optional[str] = None,
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
    sales_owner_values = resolve_multi_filter_values(sales_owners, sales_owner)

    if project_id:
        extra.append({"$or": [{"project_id": project_id}, {"project_ids": project_id}]})
    if project_values:
        project_clause = build_project_match_filter(project_values)
        if project_clause:
            extra.append(project_clause)
    if temperature and temperature.lower() != "all":
        extra.append(case_insensitive_regex_filter("temperature", temperature, exact=True))
    if budget_values:
        extra.append(case_insensitive_regex_or_filter("budget", budget_values))
    if location_values:
        # #51: exact match (case-insensitive) — avoid substring false positives
        # e.g. "Chennai" matching "Chennai Suburbs" or vice versa.
        extra.append(case_insensitive_regex_or_filter("location", location_values, exact=True))
    if source_values:
        extra.append(case_insensitive_regex_or_filter("lead_source", source_values))
    if sales_owner_values:
        owner_clause = build_sales_owners_filter(sales_owner_values)
        if owner_clause:
            extra.append(owner_clause)
    if meta_qualified is not None:
        extra.append({"meta_qualified": meta_qualified})
    if intent:
        extra.append({"intent": intent})
    if vip is not None:
        extra.append({"vip": vip})
    if re_enquiry is not None:
        extra.append({"re_enquiry": re_enquiry})
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
