"""Rep/manager lead scope shared by My Dashboard and overview drill-down on Virtual Customer."""

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


async def resolve_leads_base_filter(uid: str, name: str, current_user: dict) -> tuple[dict, bool]:
    """Always scope to the logged-in user's pipeline; is_manager is UI/metadata only."""
    rep_filter = rep_lead_filter(uid, name)
    is_manager = is_manager_user(current_user)
    return rep_filter, is_manager
