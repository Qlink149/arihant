import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.lead_view_grants import has_active_view_grant, upsert_view_grant


def test_upsert_view_grant_calls_update_and_returns_doc():
    asyncio.run(_test_upsert_view_grant_calls_update_and_returns_doc())


async def _test_upsert_view_grant_calls_update_and_returns_doc():
    mock_coll = MagicMock()
    mock_coll.update_one = AsyncMock(return_value=None)
    mock_coll.find_one = AsyncMock(
        return_value={
            "id": "g1",
            "lead_id": "lead-1",
            "user_id": "uid-1",
            "expires_at_dt": object(),
        }
    )

    mock_db = MagicMock()
    mock_db.lead_view_grants = mock_coll

    with patch("crm.services.lead_view_grants.db", mock_db):
        doc = await upsert_view_grant(lead_id="lead-1", user_id="uid-1", minutes=5)

    assert doc["lead_id"] == "lead-1"
    assert doc["user_id"] == "uid-1"
    mock_coll.update_one.assert_awaited_once()
    mock_coll.find_one.assert_awaited_once()


def test_has_active_view_grant_true_when_doc_exists():
    asyncio.run(_test_has_active_view_grant_true_when_doc_exists())


async def _test_has_active_view_grant_true_when_doc_exists():
    mock_coll = MagicMock()
    mock_coll.find_one = AsyncMock(return_value={"_id": "x"})
    mock_db = MagicMock()
    mock_db.lead_view_grants = mock_coll

    with patch("crm.services.lead_view_grants.db", mock_db):
        ok = await has_active_view_grant(lead_id="lead-1", user_id="uid-1")

    assert ok is True


def test_has_active_view_grant_false_when_missing():
    asyncio.run(_test_has_active_view_grant_false_when_missing())


async def _test_has_active_view_grant_false_when_missing():
    mock_coll = MagicMock()
    mock_coll.find_one = AsyncMock(return_value=None)
    mock_db = MagicMock()
    mock_db.lead_view_grants = mock_coll

    with patch("crm.services.lead_view_grants.db", mock_db):
        ok = await has_active_view_grant(lead_id="lead-1", user_id="uid-1")

    assert ok is False

