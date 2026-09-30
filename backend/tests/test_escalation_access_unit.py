"""batch1 #8/#40: every backend gate for Escalation Queue access must agree —
admin, manager, general_manager allowed; rep denied.

Gates found (file:line):
  - crm/constants/roles.py:29 can_filter_escalated_leads
      -> crm/services/escalation_queue.py:173 assert_escalated_filter_allowed
      -> crm/api/v1/endpoints/leads.py:299 (GET /leads?escalated=true guard)
  - crm/constants/roles.py:25 can_access_escalations
      -> crm/api/v1/endpoints/notifications.py:139 (GET /api/escalations)
      -> crm/api/v1/endpoints/notifications.py:312 (mark escalation notification read)
  - frontend App.js EscalationAccessRoute (admin/manager/general_manager) - already correct
  - frontend DashboardLayout.js:88 canSeeEscalations - already correct

Before this fix, can_filter_escalated_leads excluded "manager" while every
other gate included it - a manager could open the Escalation Queue page but
got 403 the moment the page tried to list escalated leads.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from crm.constants.roles import can_access_escalations, can_filter_escalated_leads
from crm.services.escalation_queue import assert_escalated_filter_allowed


@pytest.mark.parametrize("role", ["admin", "manager", "general_manager"])
def test_assert_escalated_filter_allowed_for_admin_manager_gm(role):
    """The exact guard leads.py:299 calls for GET /leads?escalated=true."""
    assert_escalated_filter_allowed({"role": role})  # must not raise


def test_assert_escalated_filter_allowed_denies_rep():
    with pytest.raises(HTTPException) as exc:
        assert_escalated_filter_allowed({"role": "rep"})
    assert exc.value.status_code == 403


def test_assert_escalated_filter_allowed_denies_missing_role():
    with pytest.raises(HTTPException) as exc:
        assert_escalated_filter_allowed({})
    assert exc.value.status_code == 403


def test_escalation_gates_agree_for_every_role():
    """can_filter_escalated_leads (list filter) and can_access_escalations
    (GET /api/escalations, resolve notification) must return the same
    answer for every role - that agreement is the actual bug fix."""
    for role in ("admin", "manager", "general_manager", "rep", "", None):
        assert can_filter_escalated_leads(role) == can_access_escalations(role), (
            f"escalation gates disagree for role={role!r}"
        )
