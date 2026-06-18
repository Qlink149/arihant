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


def task_assignee_clause(user_id: str, full_name: str) -> dict:
    """Tasks where the user is the assignee (by id or display name)."""
    clauses: list[dict] = [{"assigned_user_id": user_id}]
    for field in ("assigned_to", "assigned_to_name"):
        clause = _name_field_clause(field, full_name)
        if clause:
            clauses.append(clause)
    return {"$or": clauses}


async def user_is_task_assignee_on_lead(lead_id: str, current_user: dict) -> bool:
    """True when the user has at least one task linked to this lead."""
    if not lead_id:
        return False
    uid = current_user.get("id")
    name = current_user.get("full_name") or ""
    if not uid:
        return False
    clause = task_assignee_clause(uid, name)
    doc = await db.tasks.find_one({"lead_id": lead_id, **clause}, {"_id": 1})
    return doc is not None


def user_can_access_lead(lead: dict, current_user: dict) -> bool:
    """Sync ownership check only; use resolve_lead_or_403 for task-delegated access."""
    if current_user.get("role") in ("admin", "manager"):
        return True
    return user_owns_lead(lead, current_user)


async def resolve_lead_or_403(lead_id: str, current_user: dict) -> dict:
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if current_user.get("role") in ("admin", "manager"):
        return lead
    if user_owns_lead(lead, current_user):
        return lead
    if await user_is_task_assignee_on_lead(lead_id, current_user):
        return lead
    raise HTTPException(status_code=403, detail="Access denied")


async def resolve_leads_base_filter(uid: str, name: str, current_user: dict) -> tuple[dict, bool]:
    """Always scope to the logged-in user's pipeline; is_manager is UI/metadata only."""
    rep_filter = rep_lead_filter(uid, name)
    is_manager = is_manager_user(current_user)
    return rep_filter, is_manager
