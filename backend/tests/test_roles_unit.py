"""Role ACL helpers for Escalation Queue + org editors."""

from crm.constants.roles import (
    can_access_escalations,
    can_access_sales_dashboard,
    can_filter_escalated_leads,
    can_see_rnr_call_panel,
    is_org_editor,
    normalize_role,
)


def test_escalation_roles_include_manager_and_gm():
    assert can_access_escalations("admin")
    assert can_access_escalations("manager")
    assert can_access_escalations("general_manager")
    assert can_access_escalations(" General_Manager ")
    assert not can_access_escalations("rep")
    assert not can_access_escalations("")


def test_org_editor_excludes_gm():
    assert is_org_editor("admin")
    assert is_org_editor("manager")
    assert not is_org_editor("general_manager")
    assert not is_org_editor("rep")


def test_normalize_role_default():
    assert normalize_role(None) == "rep"
    assert normalize_role("  ADMIN ") == "admin"


def test_escalated_filter_matches_escalation_access():
    # batch1 #8/#40: manager must be allowed, matching can_access_escalations.
    assert can_filter_escalated_leads("admin")
    assert can_filter_escalated_leads("manager")
    assert can_filter_escalated_leads("general_manager")
    assert not can_filter_escalated_leads("rep")


def test_sales_dashboard_and_rnr_panel_gm_only():
    # Unchanged by batch1 — separate from Escalation Queue access.
    assert can_access_sales_dashboard("admin")
    assert can_access_sales_dashboard("general_manager")
    assert not can_access_sales_dashboard("rep")
    assert can_see_rnr_call_panel("admin")
    assert not can_see_rnr_call_panel("rep")
