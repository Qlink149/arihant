"""Tests for per-user saved Virtual Customer filter views."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from crm.services.lead_filter_views_service import (
    COLLECTION,
    LeadFilterViewCreate,
    LeadFilterViewFilters,
    LeadFilterViewUpdate,
    create_filter_view,
    delete_filter_view,
    list_filter_views,
    update_filter_view,
)


def _filters(**kwargs):
    base = LeadFilterViewFilters().model_dump()
    base.update(kwargs)
    return LeadFilterViewFilters(**base)


def _mock_db(collection=None):
    mock_db = MagicMock()
    mock_coll = collection or MagicMock()

    def getitem(name):
        if name == COLLECTION:
            return mock_coll
        return MagicMock()

    mock_db.__getitem__ = MagicMock(side_effect=getitem)
    return mock_db, mock_coll


def test_list_filter_views_sorted():
    async def _run():
        mock_coll = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=[{"id": "1", "name": "A"}])
        mock_coll.find.return_value = mock_cursor
        mock_db, _ = _mock_db(mock_coll)

        with patch("crm.services.lead_filter_views_service.db", mock_db):
            result = await list_filter_views("user-1")

        assert result == [{"id": "1", "name": "A"}]
        mock_coll.find.assert_called_once_with({"user_id": "user-1"}, {"_id": 0})

    asyncio.run(_run())


def test_create_filter_view_success():
    async def _run():
        mock_coll = MagicMock()
        mock_coll.count_documents = AsyncMock(return_value=0)
        mock_coll.find_one = AsyncMock(return_value=None)
        mock_coll.insert_one = AsyncMock()
        mock_db, _ = _mock_db(mock_coll)

        body = LeadFilterViewCreate(name="South Chennai", filters=_filters(locations=["Chennai"]))

        with patch("crm.services.lead_filter_views_service.db", mock_db):
            doc = await create_filter_view("user-1", body)

        assert doc["name"] == "South Chennai"
        assert doc["user_id"] == "user-1"
        assert doc["filters"]["locations"] == ["Chennai"]
        mock_coll.insert_one.assert_called_once()

    asyncio.run(_run())


def test_create_filter_view_rejects_duplicate_name():
    async def _run():
        mock_coll = MagicMock()
        mock_coll.count_documents = AsyncMock(return_value=1)
        mock_coll.find_one = AsyncMock(return_value={"id": "existing"})
        mock_db, _ = _mock_db(mock_coll)

        body = LeadFilterViewCreate(name="Dup", filters=_filters())

        with patch("crm.services.lead_filter_views_service.db", mock_db):
            with pytest.raises(HTTPException) as exc:
                await create_filter_view("user-1", body)

        assert exc.value.status_code == 409

    asyncio.run(_run())


def test_create_filter_view_max_limit():
    async def _run():
        mock_coll = MagicMock()
        mock_coll.count_documents = AsyncMock(return_value=20)
        mock_db, _ = _mock_db(mock_coll)

        body = LeadFilterViewCreate(name="One more", filters=_filters())

        with patch("crm.services.lead_filter_views_service.db", mock_db):
            with pytest.raises(HTTPException) as exc:
                await create_filter_view("user-1", body)

        assert exc.value.status_code == 400

    asyncio.run(_run())


def test_update_filter_view_not_found():
    async def _run():
        mock_coll = MagicMock()
        mock_coll.find_one = AsyncMock(return_value=None)
        mock_db, _ = _mock_db(mock_coll)

        with patch("crm.services.lead_filter_views_service.db", mock_db):
            with pytest.raises(HTTPException) as exc:
                await update_filter_view("user-1", "missing", LeadFilterViewUpdate(name="New"))

        assert exc.value.status_code == 404

    asyncio.run(_run())


def test_delete_filter_view_not_found():
    async def _run():
        mock_result = MagicMock(deleted_count=0)
        mock_coll = MagicMock()
        mock_coll.delete_one = AsyncMock(return_value=mock_result)
        mock_db, _ = _mock_db(mock_coll)

        with patch("crm.services.lead_filter_views_service.db", mock_db):
            with pytest.raises(HTTPException) as exc:
                await delete_filter_view("user-1", "missing")

        assert exc.value.status_code == 404

    asyncio.run(_run())
