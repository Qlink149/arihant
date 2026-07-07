"""Unit tests for My Dashboard view-as subject resolution."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from crm.services.dashboard_scope import resolve_dashboard_subject


def test_resolve_dashboard_subject_no_param_returns_self():
    admin = {"id": "a1", "full_name": "Admin User", "role": "admin", "email": "a@x.com"}
    subject = asyncio.run(resolve_dashboard_subject(admin, None))
    assert subject["subject_id"] == "a1"
    assert subject["subject_name"] == "Admin User"
    assert subject["viewing_as"] is False
    assert subject["is_manager"] is True


def test_resolve_dashboard_subject_same_id_as_viewer_is_self():
    rep = {"id": "r1", "full_name": "Rep One", "role": "rep", "email": "r@x.com"}
    subject = asyncio.run(resolve_dashboard_subject(rep, "r1"))
    assert subject["viewing_as"] is False
    assert subject["subject_id"] == "r1"


def test_resolve_dashboard_subject_rep_forbidden():
    rep = {"id": "r1", "full_name": "Rep One", "role": "rep", "email": "r@x.com"}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(resolve_dashboard_subject(rep, "r2"))
    assert exc.value.status_code == 403


async def _resolve_admin_viewing_rep():
    admin = {"id": "a1", "full_name": "Admin User", "role": "admin", "email": "a@x.com"}
    target = {
        "id": "r2",
        "full_name": "Sales Rep",
        "role": "rep",
        "email": "rep@x.com",
        "is_active": True,
    }
    with patch("crm.services.dashboard_scope.db") as mock_db:
        mock_db.users.find_one = AsyncMock(return_value=target)
        with patch(
            "crm.services.dashboard_scope.get_blocked_assignee_values",
            AsyncMock(return_value=set()),
        ):
            return await resolve_dashboard_subject(admin, "r2")


def test_resolve_dashboard_subject_admin_can_view_rep():
    subject = asyncio.run(_resolve_admin_viewing_rep())
    assert subject["viewing_as"] is True
    assert subject["subject_id"] == "r2"
    assert subject["subject_name"] == "Sales Rep"
    assert subject["viewer_name"] == "Admin User"


async def _resolve_missing_rep():
    admin = {"id": "a1", "full_name": "Admin User", "role": "admin", "email": "a@x.com"}
    with patch("crm.services.dashboard_scope.db") as mock_db:
        mock_db.users.find_one = AsyncMock(return_value=None)
        await resolve_dashboard_subject(admin, "missing")


def test_resolve_dashboard_subject_missing_rep_404():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(_resolve_missing_rep())
    assert exc.value.status_code == 404


async def _resolve_admin_target():
    admin = {"id": "a1", "full_name": "Admin User", "role": "admin", "email": "a@x.com"}
    target = {
        "id": "a2",
        "full_name": "Other Admin",
        "role": "admin",
        "email": "a2@x.com",
        "is_active": True,
    }
    with patch("crm.services.dashboard_scope.db") as mock_db:
        mock_db.users.find_one = AsyncMock(return_value=target)
        with patch(
            "crm.services.dashboard_scope.get_blocked_assignee_values",
            AsyncMock(return_value=set()),
        ):
            await resolve_dashboard_subject(admin, "a2")


def test_resolve_dashboard_subject_cannot_view_admin_role():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(_resolve_admin_target())
    assert exc.value.status_code == 400
