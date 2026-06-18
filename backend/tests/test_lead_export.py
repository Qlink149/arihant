"""Unit tests for lead CSV export service."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from crm.services.lead_export_service import (
    EXPORT_FIELD_CATALOG,
    EXPORT_JOBS,
    _field_value,
    _format_all_notes,
    _validate_fields,
    create_export_job,
    get_export_field_catalog,
    run_export_job,
)


def _mock_db(*, jobs=None, leads=None):
    mock_db = MagicMock()
    mock_jobs = jobs or MagicMock()
    mock_leads = leads or MagicMock()
    mock_db.leads = mock_leads

    def getitem(name):
        if name == EXPORT_JOBS:
            return mock_jobs
        return MagicMock()

    mock_db.__getitem__ = MagicMock(side_effect=getitem)
    return mock_db, mock_jobs, mock_leads


def test_get_export_field_catalog():
    catalog = get_export_field_catalog()
    assert len(catalog) == len(EXPORT_FIELD_CATALOG)
    assert catalog[0]["key"] == "external_id"
    assert any(f["default"] for f in catalog)


def test_validate_fields_rejects_empty():
    with pytest.raises(HTTPException) as exc:
        _validate_fields([])
    assert exc.value.status_code == 400


def test_validate_fields_preserves_catalog_order():
    selected = _validate_fields(["last_name", "first_name", "phone"])
    assert selected == ["first_name", "last_name", "phone"]


def test_field_value_formats_dates_and_notes():
    lead = {
        "first_name": "Ada",
        "created_at": "2024-05-27T06:04:39Z",
        "vip": True,
        "context_updates": [
            {
                "description": "First note",
                "timestamp": "2024-05-27T06:04:39Z",
            },
            {
                "description": "Second note",
                "timestamp": "2024-05-28T10:00:00Z",
            },
        ],
    }
    assert _field_value(lead, "first_name") == "Ada"
    assert "2024-05-27" in _field_value(lead, "created_at")
    assert _field_value(lead, "vip") == "Yes"
    assert _field_value(lead, "note_count") == 2
    assert "[2024-05-27] First note" in _format_all_notes(lead)
    assert "Second note" in _format_all_notes(lead)


def test_create_export_job_requires_admin():
    async def _run():
        with pytest.raises(HTTPException) as exc:
            await create_export_job({"role": "rep", "id": "u1"}, ["first_name"], {})
        assert exc.value.status_code == 403

    asyncio.run(_run())


def test_create_export_job_zero_leads():
    async def _run():
        mock_jobs = MagicMock()
        mock_jobs.create_index = AsyncMock()
        mock_jobs.find_one = AsyncMock(return_value=None)
        mock_leads = MagicMock()
        mock_leads.count_documents = AsyncMock(return_value=0)
        mock_db, _, _ = _mock_db(jobs=mock_jobs, leads=mock_leads)

        with patch("crm.services.lead_export_service.db", mock_db), patch(
            "crm.services.lead_export_service.cleanup_expired_exports",
            AsyncMock(),
        ), patch(
            "crm.services.lead_export_service.resolve_leads_list_query_base",
            AsyncMock(return_value={}),
        ), patch(
            "crm.services.lead_export_service.compose_leads_list_query",
            return_value={},
        ):
            with pytest.raises(HTTPException) as exc:
                await create_export_job(
                    {"role": "admin", "id": "admin1", "full_name": "Admin"},
                    ["first_name"],
                    {},
                )
            assert exc.value.status_code == 400

    asyncio.run(_run())


def test_run_export_job_writes_csv_and_completes():
    async def _run():
        leads = [
            {"first_name": "A", "last_name": "B", "phone": "1"},
            {"first_name": "C", "last_name": "D", "phone": "2"},
        ]

        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(side_effect=[leads, []])

        mock_jobs = MagicMock()
        mock_jobs.find_one = AsyncMock(
            return_value={
                "id": "job1",
                "fields": ["first_name", "last_name"],
                "query": {},
                "total_count": 2,
                "filename": "test.csv",
            }
        )
        mock_jobs.update_one = AsyncMock()
        mock_leads = MagicMock()
        mock_leads.find = MagicMock(return_value=mock_cursor)
        mock_db, _, _ = _mock_db(jobs=mock_jobs, leads=mock_leads)

        mock_bucket = MagicMock()
        mock_bucket.upload_from_stream = AsyncMock(return_value="507f1f77bcf86cd799439011")

        with patch("crm.services.lead_export_service.db", mock_db), patch(
            "crm.services.lead_export_service.AsyncIOMotorGridFSBucket",
            return_value=mock_bucket,
        ):
            await run_export_job("job1")

        assert mock_jobs.update_one.await_count >= 2
        completed_call = mock_jobs.update_one.await_args_list[-1]
        assert completed_call[0][1]["$set"]["status"] == "completed"
        mock_bucket.upload_from_stream.assert_awaited_once()

    asyncio.run(_run())
