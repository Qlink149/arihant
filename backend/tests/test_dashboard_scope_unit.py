"""Unit tests for My Dashboard per-user scope (no database)."""
import asyncio
from unittest.mock import patch

import pytest

from crm.services.dashboard_scope import (
    rep_lead_filter,
    resolve_leads_base_filter,
    resolve_sales_owner_ids,
)
from crm.services.transfer_queries import is_manager_user


def test_rep_lead_filter_is_id_only():
    # batch1 #55: assigned_user_id is the single authoritative owner field -
    # no more id-or-name fallback (that fallback is exactly what caused My
    # Dashboard and Virtual Customer counts to disagree for #55).
    filt = rep_lead_filter("uid-1", "Jane Doe")
    assert filt == {"assigned_user_id": "uid-1"}


def test_rep_lead_filter_ignores_full_name():
    # full_name is kept in the signature for call-site compatibility only.
    assert rep_lead_filter("uid-1", "Anything At All") == {"assigned_user_id": "uid-1"}
    assert rep_lead_filter("uid-1", "") == {"assigned_user_id": "uid-1"}


@pytest.mark.asyncio
async def test_resolve_sales_owner_ids_resolves_known_names():
    async def fake_resolve(name):
        return {"jigar": "uid-jigar", "admin": "uid-admin"}.get(name.lower())

    with patch("crm.core.state.resolve_user_id_by_full_name", side_effect=fake_resolve):
        ids = await resolve_sales_owner_ids(["Jigar", "Admin"])
    assert ids == ["uid-jigar", "uid-admin"]


@pytest.mark.asyncio
async def test_resolve_sales_owner_ids_drops_unresolvable_legacy_name():
    """A name with no matching user account (e.g. "Roshini", which is not a
    real registered user) is dropped, not name-matched as a fallback."""
    async def fake_resolve(name):
        return {"admin": "uid-admin"}.get(name.lower())

    with patch("crm.core.state.resolve_user_id_by_full_name", side_effect=fake_resolve):
        ids = await resolve_sales_owner_ids(["Admin", "Roshini"])
    assert ids == ["uid-admin"]


@pytest.mark.asyncio
async def test_resolve_sales_owner_ids_dedupes_case_insensitive():
    async def fake_resolve(name):
        return "uid-admin"

    with patch("crm.core.state.resolve_user_id_by_full_name", side_effect=fake_resolve) as mock_resolve:
        ids = await resolve_sales_owner_ids(["Admin", "admin", " ADMIN "])
    assert ids == ["uid-admin"]
    assert mock_resolve.await_count == 1


@pytest.mark.asyncio
async def test_resolve_sales_owner_ids_empty_input():
    assert await resolve_sales_owner_ids(None) == []
    assert await resolve_sales_owner_ids([]) == []
    assert await resolve_sales_owner_ids(["", "   "]) == []


def test_is_manager_user_rep_with_zero_leads_is_not_manager():
    user = {"role": "rep", "email": "rep@example.com"}
    assert is_manager_user(user, rep_lead_count=0) is False


def test_is_manager_user_admin_is_manager():
    user = {"role": "admin", "email": "admin@example.com"}
    assert is_manager_user(user) is True


def test_is_manager_user_manager_role():
    user = {"role": "manager", "email": "mgr@example.com"}
    assert is_manager_user(user) is True


def test_resolve_leads_base_filter_always_rep_scope():
    admin = {"id": "a1", "full_name": "Admin User", "role": "admin", "email": "a@x.com"}
    base_filter, is_manager = asyncio.run(resolve_leads_base_filter("a1", "Admin User", admin))
    assert is_manager is True
    assert base_filter == rep_lead_filter("a1", "Admin User")
    assert base_filter != {}

    rep = {"id": "r1", "full_name": "Sales Rep", "role": "rep", "email": "r@x.com"}
    base_filter_rep, is_manager_rep = asyncio.run(resolve_leads_base_filter("r1", "Sales Rep", rep))
    assert is_manager_rep is False
    assert base_filter_rep == rep_lead_filter("r1", "Sales Rep")
