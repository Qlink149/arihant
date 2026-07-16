"""Lead ACL helpers — ownership and role scope."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from crm.services.dashboard_scope import (
    rep_lead_filter,
    resolve_lead_or_403,
    resolve_lead_view_or_403,
    role_scope_filter,
    task_assignee_clause,
    user_owns_lead,
)


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


def test_task_assignee_clause_matches_id_and_name():
    clause = task_assignee_clause("uid-2", "Suresh")
    assert {"assigned_user_id": "uid-2"} in clause["$or"]


def test_resolve_lead_or_403_allows_task_assignee():
    asyncio.run(_resolve_lead_or_403_allows_task_assignee())


async def _resolve_lead_or_403_allows_task_assignee():
    lead = {"id": "lead-1", "assigned_user_id": "owner-id", "assigned_to": "Ravi"}
    user = {"id": "uid-2", "full_name": "Suresh", "role": "rep"}

    mock_leads = MagicMock()
    mock_leads.find_one = AsyncMock(return_value=lead)

    mock_tasks = MagicMock()
    mock_tasks.find_one = AsyncMock(return_value={"_id": "task-doc"})

    mock_db = MagicMock()
    mock_db.leads = mock_leads
    mock_db.tasks = mock_tasks

    with patch("crm.services.dashboard_scope.db", mock_db):
        result = await resolve_lead_or_403("lead-1", user)

    assert result["id"] == "lead-1"
    mock_tasks.find_one.assert_awaited_once()


def test_resolve_lead_or_403_denies_without_ownership_or_task():
    asyncio.run(_resolve_lead_or_403_denies_without_ownership_or_task())


async def _resolve_lead_or_403_denies_without_ownership_or_task():
    lead = {"id": "lead-1", "assigned_user_id": "owner-id", "assigned_to": "Ravi"}
    user = {"id": "uid-3", "full_name": "Stranger", "role": "rep"}

    mock_leads = MagicMock()
    mock_leads.find_one = AsyncMock(return_value=lead)

    mock_tasks = MagicMock()
    mock_tasks.find_one = AsyncMock(return_value=None)

    mock_db = MagicMock()
    mock_db.leads = mock_leads
    mock_db.tasks = mock_tasks

    mock_grants = MagicMock()
    mock_grants.find_one = AsyncMock(return_value=None)
    mock_db_grants = MagicMock()
    mock_db_grants.lead_view_grants = mock_grants

    with patch("crm.services.dashboard_scope.db", mock_db), patch("crm.services.lead_view_grants.db", mock_db_grants):
        with pytest.raises(HTTPException) as exc:
            await resolve_lead_or_403("lead-1", user)

    assert exc.value.status_code == 403


def test_resolve_lead_view_or_403_allows_any_authenticated_user():
    asyncio.run(_resolve_lead_view_or_403_allows_any_authenticated_user())


async def _resolve_lead_view_or_403_allows_any_authenticated_user():
    lead = {"id": "lead-1", "assigned_user_id": "owner-id", "assigned_to": "Ravi"}
    user = {"id": "uid-9", "full_name": "Viewer", "role": "rep"}

    mock_leads = MagicMock()
    mock_leads.find_one = AsyncMock(return_value=lead)

    mock_db_scope = MagicMock()
    mock_db_scope.leads = mock_leads

    with patch("crm.services.dashboard_scope.db", mock_db_scope):
        result = await resolve_lead_view_or_403("lead-1", user)

    assert result["id"] == "lead-1"
