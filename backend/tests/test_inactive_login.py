"""T17: inactive users cannot authenticate; admin is never locked out."""

from crm.constants.roles import user_may_authenticate


def test_inactive_rep_blocked():
    assert not user_may_authenticate({"role": "rep", "is_active": False})


def test_inactive_admin_allowed():
    assert user_may_authenticate({"role": "admin", "is_active": False})


def test_active_rep_allowed():
    assert user_may_authenticate({"role": "rep", "is_active": True})


def test_missing_is_active_defaults_allowed():
    assert user_may_authenticate({"role": "rep"})
