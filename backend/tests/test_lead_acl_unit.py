"""Lead ACL helpers — ownership and role scope."""

from crm.services.dashboard_scope import rep_lead_filter, role_scope_filter, user_owns_lead


def test_rep_lead_filter_includes_user_id():
    f = rep_lead_filter("uid-1", "Alice Rep")
    assert {"assigned_user_id": "uid-1"} in f["$or"]


def test_role_scope_filter_admin_is_empty():
    assert role_scope_filter({"role": "admin", "id": "a", "full_name": "Admin"}) == {}


def test_role_scope_filter_rep_is_scoped():
    scope = role_scope_filter({"role": "rep", "id": "uid-1", "full_name": "Alice"})
    assert "$or" in scope


def test_user_owns_lead_by_assigned_user_id():
    lead = {"assigned_user_id": "uid-1", "assigned_to": "Bob"}
    user = {"id": "uid-1", "full_name": "Alice"}
    assert user_owns_lead(lead, user) is True


def test_user_owns_lead_denied():
    lead = {"assigned_user_id": "other", "assigned_to": "Bob"}
    user = {"id": "uid-1", "full_name": "Alice"}
    assert user_owns_lead(lead, user) is False
