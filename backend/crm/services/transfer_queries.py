"""Shared MongoDB filters for lead transfer inbox/outbox queries.

Transfers are one-way (no acknowledgement state). Queries may be optionally time-bounded.
"""

from datetime import timedelta

from crm.core.platform_ops import is_platform_operator
from crm.core.state import utc_now
from crm.services.lead_search import escape_regex_literal


def _name_field_clause(field: str, full_name: str) -> dict:
    if not full_name or not str(full_name).strip():
        return {}
    pattern = escape_regex_literal(str(full_name).strip())
    return {field: {"$regex": f"^\\s*{pattern}\\s*$", "$options": "i"}}


def _incoming_rep_clauses(name: str, uid: str) -> list[dict]:
    clauses: list[dict] = [{"to_user_id": uid}]
    for field in ("to_rep", "to_name"):
        clause = _name_field_clause(field, name)
        if clause:
            clauses.append(clause)
    return clauses


def _outgoing_rep_clauses(name: str, uid: str) -> list[dict]:
    clauses: list[dict] = [{"from_user_id": uid}, {"transferred_by_user_id": uid}]
    for field in ("from_rep", "from_name", "transferred_by"):
        clause = _name_field_clause(field, name)
        if clause:
            clauses.append(clause)
    return clauses


def _since_filter(since_days: int | None) -> dict:
    if not since_days:
        return {}
    cutoff_dt = utc_now() - timedelta(days=int(since_days))
    return {"transferred_at_dt": {"$gte": cutoff_dt}}


def incoming_transfer_filter(name: str, uid: str, is_manager: bool, *, since_days: int | None = 90) -> dict:
    base = _since_filter(since_days)
    clauses = _incoming_rep_clauses(name, uid)
    if not base:
        return {"$or": clauses}
    return {"$and": [base, {"$or": clauses}]}


def outgoing_transfer_filter(name: str, uid: str, is_manager: bool, *, since_days: int | None = 90) -> dict:
    base = _since_filter(since_days)
    clauses = _outgoing_rep_clauses(name, uid)
    if not base:
        return {"$or": clauses}
    return {"$and": [base, {"$or": clauses}]}


def is_manager_user(current_user: dict, rep_lead_count: int | None = None) -> bool:
    """Role flag for UI/metadata only — does not widen My Dashboard data scope."""
    _ = rep_lead_count  # legacy callers may still pass count; ignored
    if is_platform_operator(current_user):
        return True
    role = (current_user.get("role") or "rep").lower()
    return role in ("admin", "manager")
