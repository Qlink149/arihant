"""Tests for list-view lead projection and timeline trimming."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from crm.models.schemas.lead_schemas import LeadResponse
from crm.services import lead_service
from crm.services.lead_projections import LIST_LEAD_PROJECTION, trim_context_updates_for_list


def test_trim_context_updates_for_list_picks_newest_note():
    updates = [
        {"type": "note", "description": "Older", "timestamp": "2024-01-01T00:00:00Z"},
        {
            "type": "note",
            "description": "Newest note",
            "timestamp_dt": datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
        },
    ]
    trimmed = trim_context_updates_for_list(updates)
    assert len(trimmed) == 1
    assert trimmed[0]["description"] == "Newest note"
    assert trimmed[0]["timestamp_dt"] is not None


def test_trim_context_updates_for_list_empty_when_no_descriptions():
    updates = [{"type": "created", "description": "  "}]
    assert trim_context_updates_for_list(updates) == []


def test_minimal_lead_validates_as_lead_response():
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    lead = {
        "id": "l1",
        "first_name": "A",
        "last_name": "B",
        "created_at": now,
        "updated_at": now,
        "context_updates": [],
    }
    resp = LeadResponse(**lead)
    assert resp.id == "l1"


def test_list_leads_uses_projection_and_list_view():
    async def _run():
        now = datetime(2024, 1, 1, tzinfo=timezone.utc)
        raw_lead = {
            "id": "l1",
            "first_name": "A",
            "last_name": "B",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "context_updates": [
                {"type": "note", "description": "Only one", "timestamp": now.isoformat()},
            ],
        }

        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=[raw_lead])

        mock_db = MagicMock()
        mock_db.leads.count_documents = AsyncMock(return_value=1)
        mock_db.leads.find = MagicMock(return_value=mock_cursor)

        with patch.object(lead_service, "db", mock_db):
            with patch.object(lead_service, "build_leads_list_query", return_value={}):
                leads, total = await lead_service.list_leads(limit=10)

        mock_db.leads.find.assert_called_once()
        assert mock_db.leads.find.call_args[0][1] == LIST_LEAD_PROJECTION
        assert total == 1
        assert len(leads) == 1
        assert len(leads[0].context_updates) <= 1

    asyncio.run(_run())
