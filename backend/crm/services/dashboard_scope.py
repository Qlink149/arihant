"""Rep/manager lead scope shared by My Dashboard, Virtual Customer, and lead ACL."""

from typing import Any, List, Optional, Sequence

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
    """Leads assigned to the current user.

    batch1 #55: assigned_user_id is the single authoritative owner field.
    The previous id-OR-name-field fallback made this disagree with the
    Virtual Customer Sales Owner filter (name-based) whenever a lead's
    assigned_to_name/assigned_to/presales_agent had drifted from its real
    assigned_user_id - e.g. production has leads with assigned_user_id =
    Admin's id but assigned_to_name = "Roshini" (My Dashboard "All Leads"
    counted them for Admin via the name-drift fallback; Virtual Customer's
    old name-only filter did not - 16,787 vs 13,384). Audited production
    before this change: every real user account except Admin has zero
    name-vs-id drift, and only 1 lead in the whole database has no
    assigned_user_id at all (and it has no name fields either) - so
    dropping the name fallback causes no visibility loss for any current
    user; it only removes the mismatch.

    ``full_name`` is kept in the signature for call-site compatibility but
    is no longer used for matching.
    """
    return {"assigned_user_id": user_id}


async def resolve_sales_owner_ids(names: Optional[Sequence[str]]) -> List[str]:
    """batch1 #55: resolve Sales Owner filter display names to the
    authoritative assigned_user_id of the matching user account, for use in
    an ``{"assigned_user_id": {"$in": [...]}}`` filter.

    A name that does not match any current user account (e.g. a stale
    legacy value like "Roshini", which is not itself a registered user) is
    dropped rather than falling back to name matching - reintroducing that
    fallback is exactly what caused the Virtual Customer filter to disagree
    with My Dashboard. This is a deliberate, disclosed side effect: filtering
    by such a name now returns zero leads instead of a name-matched set.
    """
    from crm.core.state import resolve_user_id_by_full_name

    ids: List[str] = []
    seen: set[str] = set()
    for raw in names or []:
        name = str(raw or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        uid = await resolve_user_id_by_full_name(name)
        if uid:
            ids.append(uid)
    return ids


async def resolve_owner_names(ids: Optional[Sequence[str]]) -> dict[str, str]:
    """batch2 item 1: bulk assigned_user_id -> current display name lookup.

    For dashboards/aggregations that must GROUP by the authoritative
    assigned_user_id (see Batch 1 #55) but still need a human name to show.
    The id is the grouping key; the returned name is display only and is
    always the user's CURRENT full_name, so a rename is reflected everywhere
    immediately rather than being frozen in old lead documents.
    """
    id_list = [str(i).strip() for i in (ids or []) if i and str(i).strip()]
    id_list = list(dict.fromkeys(id_list))
    if not id_list:
        return {}
    out: dict[str, str] = {}
    async for u in db.users.find({"id": {"$in": id_list}}, {"_id": 0, "id": 1, "full_name": 1}):
        name = (u.get("full_name") or "").strip()
        if name:
            out[u["id"]] = name
    return out


def merge_owner_count_rows_by_name(
    rows: Sequence[dict], names_by_id: dict[str, str]
) -> List[dict]:
    """batch2 item 1: turn ``[{"_id": assigned_user_id_or_empty, "count": n}]``
    rows into ``[{"name": ..., "count": ...}]`` sorted by count desc, merging
    any ids that resolve to the same display name (e.g. no owner id at all
    and a deleted user's id both fall back to "Unassigned") so the result
    never contains a duplicate name."""
    by_name: dict[str, int] = {}
    for row in rows:
        name = names_by_id.get(row.get("_id") or "") or "Unassigned"
        by_name[name] = by_name.get(name, 0) + int(row.get("count") or 0)
    return sorted(
        ({"name": n, "count": c} for n, c in by_name.items()),
        key=lambda x: -x["count"],
    )


async def build_sales_owner_options() -> List[dict]:
    """batch2 item 1: Sales Owner filter dropdown options, sourced from the
    ``users`` collection (the authoritative id-based owner definition) - not
    the legacy ``presales_agent`` name field, so a stale/non-user value like
    "Roshini" can never appear as an option.

    Every active user is included. An inactive user is included only if they
    still own at least one lead (by assigned_user_id) - otherwise their
    leads would become unreachable through this filter - and is labelled
    ``is_active: False`` so the UI can show it's a former user.
    """
    users = await db.users.find({}, {"_id": 0, "id": 1, "full_name": 1, "is_active": 1}).to_list(1000)
    count_rows = await db.leads.aggregate(
        [
            {"$match": {"assigned_user_id": {"$nin": [None, ""]}}},
            {"$group": {"_id": "$assigned_user_id", "count": {"$sum": 1}}},
        ]
    ).to_list(None)
    counts_by_id = {r["_id"]: int(r.get("count") or 0) for r in count_rows}

    options: List[dict] = []
    for u in users:
        name = (u.get("full_name") or "").strip()
        if not name:
            continue
        uid = u.get("id")
        count = counts_by_id.get(uid, 0)
        is_active = u.get("is_active") is not False
        if not is_active and count == 0:
            continue  # former user with no leads - nothing to filter by
        options.append({"name": name, "count": count, "id": uid, "is_active": is_active})

    options.sort(key=lambda o: (not o["is_active"], -o["count"], o["name"].lower()))
    return options


def role_scope_filter(current_user: dict) -> dict:
    """Mongo filter: {} for admin/manager (org-wide); rep/GM use assignment filter."""
    from crm.constants.roles import is_org_editor

    if is_org_editor(current_user.get("role")):
        return {}
    return rep_lead_filter(current_user["id"], current_user.get("full_name") or "")


def sales_dashboard_scope_filter(current_user: dict) -> dict:
    """Org-wide for admin/manager/GM; reps still see only their pipeline."""
    from crm.constants.roles import can_access_sales_dashboard, is_org_editor

    role = current_user.get("role")
    if is_org_editor(role) or can_access_sales_dashboard(role):
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
    from crm.constants.roles import is_org_editor

    # admin/manager edit org-wide; general_manager is like rep (own / task / grant).
    if is_org_editor(current_user.get("role")):
        return lead
    if user_owns_lead(lead, current_user):
        return lead
    if await user_is_task_assignee_on_lead(lead_id, current_user):
        return lead
    # Reps/GM who found this lead via the search bar (exact phone/email lookup) get a
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
