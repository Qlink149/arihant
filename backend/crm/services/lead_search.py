"""Shared MongoDB text search and query composition for lead list endpoints."""
import re
from typing import Any, Dict, Optional


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


def case_insensitive_regex_filter(field: str, value: Optional[str]) -> Dict[str, Any]:
    """Build a single-field case-insensitive regex filter with escaped literal."""
    if not value or not value.strip():
        return {}
    return {field: {"$regex": escape_regex_literal(value), "$options": "i"}}


def build_leads_list_query(
    base_filter: Optional[Dict[str, Any]] = None,
    *,
    temperature: Optional[str] = None,
    search: Optional[str] = None,
    project: Optional[str] = None,
    project_id: Optional[str] = None,
    budget: Optional[str] = None,
    location: Optional[str] = None,
    intent: Optional[str] = None,
    vip: Optional[bool] = None,
    status: Optional[str] = None,
    days_cutoff_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Compose a full leads query for list endpoints."""
    extra: list[Dict[str, Any]] = []

    if project_id:
        extra.append({"project_id": project_id})
    if project:
        extra.append(case_insensitive_regex_filter("project", project))
    if temperature and temperature.lower() != "all":
        extra.append({"temperature": temperature})
    if budget:
        extra.append(case_insensitive_regex_filter("budget", budget))
    if location:
        extra.append(case_insensitive_regex_filter("location", location))
    if intent:
        extra.append({"intent": intent})
    if vip is not None:
        extra.append({"vip": vip})
    if status:
        extra.append({"lead_status": status})
    if days_cutoff_iso:
        extra.append({"created_at": {"$gte": days_cutoff_iso}})

    search_clause = build_text_search_clause(search)
    if search_clause:
        extra.append(search_clause)

    return merge_query(base_filter or {}, *extra)
