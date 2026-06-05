"""Rep/manager lead scope shared by My Dashboard, Virtual Customer, and lead ACL."""

from fastapi import HTTPException

from crm.core.state import db
from crm.services.lead_search import escape_regex_literal
from crm.services.transfer_queries import is_manager_user


def _name_field_clause(field: str, full_name: str) -> dict:
    if not full_name or not str(full_name).strip():
        return {}
    pattern = escape_regex_literal(str(full_name).strip())
    return {field: {"$regex": f"^{pattern}$", "$options": "i"}}


def rep_lead_filter(user_id: str, full_name: str) -> dict:
    """Leads assigned to the current user (exact id or case-insensitive name match)."""
    clauses: list[dict] = [{"assigned_user_id": user_id}]
    for field in ("assigned_to_name", "assigned_to", "presales_agent"):
        clause = _name_field_clause(field, full_name)
        if clause:
            clauses.append(clause)
    return {"$or": clauses}


def role_scope_filter(current_user: dict) -> dict:
    """Mongo filter: {} for admin/manager (org-wide), rep assignment filter otherwise."""
    if current_user.get("role") in ("admin", "manager"):
        return {}
    return rep_lead_filter(current_user["id"], current_user.get("full_name") or "")


def user_owns_lead(lead: dict, current_user: dict) -> bool:
    uid = current_user["id"]
    name = current_user.get("full_name") or ""
    candidates = {
        lead.get("assigned_user_id"),
        lead.get("assigned_to"),
        lead.get("assigned_to_name"),
        lead.get("presales_agent"),
    }
    return uid in candidates or name in candidates


async def resolve_lead_or_403(lead_id: str, current_user: dict) -> dict:
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if current_user.get("role") in ("admin", "manager"):
        return lead
    if not user_owns_lead(lead, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
    return lead


async def resolve_leads_base_filter(uid: str, name: str, current_user: dict) -> tuple[dict, bool]:
    """Always scope to the logged-in user's pipeline; is_manager is UI/metadata only."""
    rep_filter = rep_lead_filter(uid, name)
    is_manager = is_manager_user(current_user)
    return rep_filter, is_manager
