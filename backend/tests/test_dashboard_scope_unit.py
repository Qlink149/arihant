"""Unit tests for My Dashboard per-user scope (no database)."""
import asyncio
from unittest.mock import patch

import pytest

from crm.services.dashboard_scope import (
    rep_lead_filter,
    NO_MATCH_OWNER_ID,
    resolve_leads_base_filter,
    resolve_sales_owner_filter,
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


# batch2 item 1: dashboards must group/filter by assigned_user_id everywhere,
# then resolve to a display name only for showing to the user.


@pytest.mark.asyncio
async def test_resolve_owner_names_resolves_known_ids():
    from unittest.mock import AsyncMock, MagicMock
    from crm.services import dashboard_scope

    mock_db = MagicMock()

    class _FakeCursor:
        def __init__(self, docs):
            self._docs = docs

        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            for d in self._docs:
                yield d

    mock_db.users.find = MagicMock(
        return_value=_FakeCursor(
            [{"id": "uid-1", "full_name": "Alice"}, {"id": "uid-2", "full_name": "Bob"}]
        )
    )
    with patch("crm.services.dashboard_scope.db", mock_db):
        names = await dashboard_scope.resolve_owner_names(["uid-1", "uid-2", "uid-missing"])
    assert names == {"uid-1": "Alice", "uid-2": "Bob"}


@pytest.mark.asyncio
async def test_resolve_owner_names_empty_input():
    from crm.services import dashboard_scope

    assert await dashboard_scope.resolve_owner_names(None) == {}
    assert await dashboard_scope.resolve_owner_names([]) == {}
    assert await dashboard_scope.resolve_owner_names(["", "  "]) == {}


def test_merge_owner_count_rows_by_name_merges_duplicates():
    from crm.services.dashboard_scope import merge_owner_count_rows_by_name

    rows = [
        {"_id": "", "count": 3},
        {"_id": "uid-deleted", "count": 2},
        {"_id": "uid-alice", "count": 10},
    ]
    names = {"uid-alice": "Alice"}  # "" and uid-deleted both unresolved
    result = merge_owner_count_rows_by_name(rows, names)
    assert result == [
        {"name": "Alice", "count": 10},
        {"name": "Unassigned", "count": 5},
    ]


def test_merge_owner_count_rows_by_name_empty():
    from crm.services.dashboard_scope import merge_owner_count_rows_by_name

    assert merge_owner_count_rows_by_name([], {}) == []


@pytest.mark.asyncio
async def test_build_sales_owner_options_active_users_and_inactive_with_leads():
    from unittest.mock import AsyncMock, MagicMock
    from crm.services import dashboard_scope

    users = [
        {"id": "uid-active-1", "full_name": "Alice", "is_active": True},
        {"id": "uid-active-2", "full_name": "Bob", "is_active": True},
        {"id": "uid-inactive-with-leads", "full_name": "Gowtham j", "is_active": False},
        {"id": "uid-inactive-no-leads", "full_name": "Old Rep", "is_active": False},
    ]
    counts = [
        {"_id": "uid-active-1", "count": 10},
        {"_id": "uid-inactive-with-leads", "count": 4},
    ]
    mock_db = MagicMock()
    mock_users_cursor = MagicMock()
    mock_users_cursor.to_list = AsyncMock(return_value=users)
    mock_db.users.find = MagicMock(return_value=mock_users_cursor)
    mock_counts_cursor = MagicMock()
    mock_counts_cursor.to_list = AsyncMock(return_value=counts)
    mock_db.leads.aggregate = MagicMock(return_value=mock_counts_cursor)

    with patch("crm.services.dashboard_scope.db", mock_db):
        options = await dashboard_scope.build_sales_owner_options()

    by_name = {o["name"]: o for o in options}
    assert "Alice" in by_name and by_name["Alice"]["is_active"] is True and by_name["Alice"]["count"] == 10
    assert "Bob" in by_name and by_name["Bob"]["count"] == 0
    # Inactive but still owns leads - included, labelled inactive.
    assert "Gowtham j" in by_name
    assert by_name["Gowtham j"]["is_active"] is False
    assert by_name["Gowtham j"]["count"] == 4
    # Inactive with zero leads - excluded (nothing to filter by).
    assert "Old Rep" not in by_name
    # A legacy non-user name like "Roshini" can never appear - it's not in `users`.
    assert "Roshini" not in by_name


@pytest.mark.asyncio
async def test_build_sales_owner_options_no_users():
    from unittest.mock import AsyncMock, MagicMock
    from crm.services import dashboard_scope

    mock_db = MagicMock()
    mock_users_cursor = MagicMock()
    mock_users_cursor.to_list = AsyncMock(return_value=[])
    mock_db.users.find = MagicMock(return_value=mock_users_cursor)
    mock_counts_cursor = MagicMock()
    mock_counts_cursor.to_list = AsyncMock(return_value=[])
    mock_db.leads.aggregate = MagicMock(return_value=mock_counts_cursor)

    with patch("crm.services.dashboard_scope.db", mock_db):
        options = await dashboard_scope.build_sales_owner_options()
    assert options == []


# ---- an unresolved Sales Owner must match NOTHING, not drop the filter ----
@pytest.mark.asyncio
async def test_sales_owner_filter_none_when_nothing_selected():
    assert await resolve_sales_owner_filter(None) is None
    assert await resolve_sales_owner_filter([]) is None
    assert await resolve_sales_owner_filter(["", "  "]) is None


@pytest.mark.asyncio
async def test_sales_owner_filter_returns_ids_when_resolved():
    async def fake_resolve(name):
        return {"admin": "uid-admin"}.get(name.lower())

    with patch("crm.core.state.resolve_user_id_by_full_name", side_effect=fake_resolve):
        assert await resolve_sales_owner_filter(["Admin"]) == ["uid-admin"]
        assert await resolve_sales_owner_filter(["Admin", "Roshini"]) == ["uid-admin"]


@pytest.mark.asyncio
async def test_sales_owner_filter_matches_nothing_when_name_unresolved():
    async def fake_resolve(name):
        return None

    with patch("crm.core.state.resolve_user_id_by_full_name", side_effect=fake_resolve):
        assert await resolve_sales_owner_filter(["Roshini"]) == [NO_MATCH_OWNER_ID]


def test_no_match_owner_id_produces_an_empty_assigned_user_clause():
    from crm.services.lead_search import build_leads_list_query

    q = build_leads_list_query(sales_owners=[NO_MATCH_OWNER_ID])
    assert {"assigned_user_id": {"$in": [NO_MATCH_OWNER_ID]}} in (q.get("$and") or [q])
