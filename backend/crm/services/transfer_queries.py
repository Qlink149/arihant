"""Shared MongoDB filters for lead transfer inbox/outbox queries.

Transfers are one-way (no acknowledgement state). Queries may be optionally time-bounded.
"""

from datetime import timedelta

from crm.core.platform_ops import is_platform_operator
from crm.core.state import db, utc_now
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


async def still_owned_lead_ids(uid: str, name: str) -> list[str]:
    """#50: lead ids currently assigned to this user (id or case-insensitive name match)."""
    from crm.services.dashboard_scope import rep_lead_filter

    cursor = db.leads.find(rep_lead_filter(uid, name), {"_id": 0, "id": 1})
    ids: list[str] = []
    async for doc in cursor:
        lid = (doc.get("id") or "").strip()
        if lid:
            ids.append(lid)
    return ids


def still_owned_filter(owned_lead_ids: list[str]) -> dict:
    """#50: constrain a transfer filter to leads still assigned to the current user.

    Uses a precomputed lead-id list (two-step filter) instead of an N+1 lookup.
    An empty list must never widen to "match everything" — it should match nothing.
    """
    return {"lead_id": {"$in": owned_lead_ids or ["__none__"]}}


async def incoming_transfer_filter_still_owned(
    name: str, uid: str, is_manager: bool, *, since_days: int | None = 90
) -> dict:
    """#50: Received transfers where the lead is still assigned to the current user.

    Historical inbound transfers stay visible elsewhere (e.g. full transfer history);
    this is specifically for the "Received" tile/tab which should reflect current
    ownership, not leads that were transferred in and then moved on again.
    """
    base = incoming_transfer_filter(name, uid, is_manager, since_days=since_days)
    owned_ids = await still_owned_lead_ids(uid, name)
    return {"$and": [base, still_owned_filter(owned_ids)]}


def is_manager_user(current_user: dict, rep_lead_count: int | None = None) -> bool:
    """Role flag for UI/metadata only — does not widen My Dashboard data scope."""
    _ = rep_lead_count  # legacy callers may still pass count; ignored
    if is_platform_operator(current_user):
        return True
    role = (current_user.get("role") or "rep").lower()
    return role in ("admin", "manager")
