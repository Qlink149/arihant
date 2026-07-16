"""Rep/manager lead scope shared by My Dashboard, Virtual Customer, and lead ACL."""

from typing import Any, Optional

from fastapi import HTTPException

from crm.core.platform_ops import get_blocked_assignee_values
from crm.core.state import db
from crm.services.lead_search import escape_regex_literal
from crm.services.transfer_queries import is_manager_user
from crm.services.lead_view_grants import has_active_view_grant


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
    """All authenticated users can access all leads."""
    return True


async def resolve_lead_or_403(lead_id: str, current_user: dict) -> dict:
    """Edit access: admin/manager always; reps if they own the lead, are a task assignee,
    OR have an active view grant (minted when searching by phone/email in the search bar)."""
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if current_user.get("role") in ("admin", "manager"):
        return lead
    if user_owns_lead(lead, current_user):
        return lead
    if await user_is_task_assignee_on_lead(lead_id, current_user):
        return lead
    # Reps who found this lead via the search bar (exact phone/email lookup) get a
    # temporary 10-minute edit grant. This allows them to update the lead they searched.
    if await has_active_view_grant(lead_id=lead_id, user_id=current_user.get("id") or ""):
        return lead
    raise HTTPException(status_code=403, detail="Access denied")


async def resolve_lead_view_or_403(lead_id: str, current_user: dict) -> dict:
    """
    View access for read endpoints: any authenticated user can view any lead.
    All leads are visible org-wide in Virtual Customer.
    """
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


async def resolve_leads_base_filter(uid: str, name: str, current_user: dict) -> tuple[dict, bool]:
    """Always scope to the logged-in user's pipeline; is_manager is UI/metadata only."""
    rep_filter = rep_lead_filter(uid, name)
    is_manager = is_manager_user(current_user)
    return rep_filter, is_manager


_VIEW_AS_ALLOWED_ROLES = frozenset({"admin", "manager"})
_VIEW_AS_SUBJECT_ROLES = frozenset({"rep", "manager"})


def subject_user_dict(subject_id: str, subject_name: str, subject_role: str) -> dict:
    """Minimal user-shaped dict for lead_list_query scope helpers."""
    return {"id": subject_id, "full_name": subject_name, "role": subject_role}


async def resolve_dashboard_subject(
    current_user: dict,
    rep_user_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Resolve whose My Dashboard pipeline to load.

    Returns subject_id/name/role, viewer metadata, and viewing_as flag.
    """
    viewer_id = current_user.get("id") or ""
    viewer_name = (current_user.get("full_name") or "").strip()
    viewer_role = (current_user.get("role") or "rep").strip().lower()
    is_manager = is_manager_user(current_user)

    if not rep_user_id or rep_user_id.strip() == viewer_id:
        return {
            "subject_id": viewer_id,
            "subject_name": viewer_name,
            "subject_role": viewer_role,
            "viewer_id": viewer_id,
            "viewer_name": viewer_name,
            "viewing_as": False,
            "is_manager": is_manager,
        }

    if viewer_role not in _VIEW_AS_ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Access denied")

    target = await db.users.find_one(
        {"id": rep_user_id.strip()},
        {"_id": 0, "id": 1, "full_name": 1, "role": 1, "email": 1, "is_active": 1},
    )
    if not target:
        raise HTTPException(status_code=404, detail="Rep not found")
    if target.get("is_active") is False:
        raise HTTPException(status_code=400, detail="Rep is inactive")

    target_role = (target.get("role") or "rep").strip().lower()
    if target_role not in _VIEW_AS_SUBJECT_ROLES:
        raise HTTPException(status_code=400, detail="Cannot view dashboard for this user role")

    blocked = await get_blocked_assignee_values()
    email = (target.get("email") or "").strip().lower()
    name = (target.get("full_name") or "").strip().lower()
    if email in blocked or name in blocked:
        raise HTTPException(status_code=400, detail="Rep is not available")

    subject_name = (target.get("full_name") or "").strip()
    if not subject_name:
        raise HTTPException(status_code=400, detail="Rep has no display name")

    return {
        "subject_id": target["id"],
        "subject_name": subject_name,
        "subject_role": target_role,
        "viewer_id": viewer_id,
        "viewer_name": viewer_name,
        "viewing_as": True,
        "is_manager": is_manager,
    }


def dashboard_subject_meta(subject: dict[str, Any]) -> dict[str, Any]:
    """Response fragment for My Dashboard view-as metadata."""
    return {
        "rep_name": subject["subject_name"],
        "subject_user_id": subject["subject_id"],
        "viewer_name": subject["viewer_name"],
        "viewing_as": bool(subject.get("viewing_as")),
        "is_manager": bool(subject.get("is_manager")),
    }
