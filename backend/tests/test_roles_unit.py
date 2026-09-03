"""Role ACL helpers for Escalation Queue + org editors."""

from crm.constants.roles import can_access_escalations, is_org_editor, normalize_role


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
