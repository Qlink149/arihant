"""Unit tests for WhatsApp inbox list helpers and scoped aggregation."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.services import whatsapp_service as wa


def test_lead_display_name_prefers_first_last():
    assert wa._lead_display_name({"first_name": "Raj", "last_name": "Singh"}) == "Raj Singh"
    assert wa._lead_display_name({"name": "Only Name"}) == "Only Name"
    assert wa._lead_display_name({"phone": "+91999"}) == "+91999"


def test_inbox_preview_truncates_and_humanizes():
    preview = wa._inbox_preview_text({"content": "Template: arihant_brochure_v1"})
    assert "brochure" in preview.lower() or "Brochure" in preview or "Project" in preview
    long = "x" * 200
    assert len(wa._inbox_preview_text({"content": long})) <= 120


def test_inbox_peer_phone_wati(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")
    assert wa._inbox_peer_phone("9894474820") == "919894474820"
    assert wa._inbox_peer_phone("+91 9894474820") == "919894474820"


@pytest.mark.asyncio
async def test_inbox_lead_scope_admin_is_org_wide():
    scope = await wa._inbox_lead_scope_filter({"id": "a1", "role": "admin", "full_name": "Admin"})
    assert scope == {}


@pytest.mark.asyncio
async def test_inbox_lead_scope_rep_includes_task_leads(monkeypatch):
    mock_cursor = MagicMock()

    async def _aiter():
        yield {"lead_id": "lead-task-1"}
        yield {"lead_id": "lead-task-1"}  # dedupe
        yield {"lead_id": "lead-task-2"}

    mock_cursor.__aiter__ = lambda self: _aiter()
    mock_db = MagicMock()
    mock_db.tasks.find = MagicMock(return_value=mock_cursor)
    monkeypatch.setattr(wa, "db", mock_db)

    scope = await wa._inbox_lead_scope_filter(
        {"id": "u1", "role": "rep", "full_name": "Rep One"}
    )
    assert "$or" in scope
    assert {"id": {"$in": ["lead-task-1", "lead-task-2"]}} in scope["$or"]


@pytest.mark.asyncio
async def test_get_whatsapp_inbox_filters_no_history_and_scopes_rep(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")

    leads = [
        {
            "id": "L1",
            "first_name": "Owned",
            "last_name": "Lead",
            "phone": "911111111111",
            "project": "ECR - Reserve 16",
            "assigned_to_name": "Rep One",
            "status": "Interested",
        },
        {
            "id": "L2",
            "first_name": "Silent",
            "last_name": "Lead",
            "phone": "912222222222",
            "project": "OMR",
            "assigned_to_name": "Rep One",
        },
        {
            "id": "L3",
            "first_name": "Other",
            "last_name": "Rep",
            "phone": "913333333333",
            "assigned_to_name": "Someone Else",
        },
    ]

    class FakeLeadCursor:
        def limit(self, _n):
            return self

        async def to_list(self, _n):
            # Scope filter already applied by service query; return owned + task only
            return [leads[0], leads[1]]

    class FakeAgg:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            yield {
                "_id": "911111111111",
                "last": {
                    "content": "Thanks boss",
                    "direction": "inbound",
                    "message_type": "text",
                    "created_at": "2026-07-20T10:00:00+00:00",
                    "created_at_dt": datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
                },
            }
            # L2 has no messages → excluded

    mock_db = MagicMock()
    mock_db.leads.find = MagicMock(return_value=FakeLeadCursor())
    mock_db.whatsapp_messages.aggregate = MagicMock(return_value=FakeAgg())
    mock_db.tasks.find = MagicMock(return_value=MagicMock(__aiter__=lambda self: iter([])))

    async def fake_scope(user):
        return {"assigned_user_id": user["id"]}

    monkeypatch.setattr(wa, "db", mock_db)
    monkeypatch.setattr(wa, "_inbox_lead_scope_filter", fake_scope)

    result = await wa.get_whatsapp_inbox(
        {"id": "u1", "role": "rep", "full_name": "Rep One"},
        limit=50,
        skip=0,
    )
    assert result["count"] == 1
    assert len(result["conversations"]) == 1
    conv = result["conversations"][0]
    assert conv["lead_id"] == "L1"
    assert conv["display_name"] == "Owned Lead"
    assert "Thanks" in conv["last_message_preview"]
    assert conv["last_direction"] == "inbound"


@pytest.mark.asyncio
async def test_get_whatsapp_inbox_admin_sees_all_with_history(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")

    leads = [
        {"id": "A", "first_name": "A", "phone": "911111111111", "project": "P1"},
        {"id": "B", "first_name": "B", "phone": "912222222222", "project": "P2"},
    ]

    class FakeLeadCursor:
        def limit(self, _n):
            return self

        async def to_list(self, _n):
            return leads

    class FakeAgg:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            yield {
                "_id": "911111111111",
                "last": {
                    "content": "Hi A",
                    "direction": "outbound",
                    "created_at": "2026-07-21T09:00:00+00:00",
                },
            }
            yield {
                "_id": "912222222222",
                "last": {
                    "content": "Hi B",
                    "direction": "inbound",
                    "created_at": "2026-07-21T10:00:00+00:00",
                },
            }

    mock_db = MagicMock()
    mock_db.leads.find = MagicMock(return_value=FakeLeadCursor())
    mock_db.whatsapp_messages.aggregate = MagicMock(return_value=FakeAgg())
    monkeypatch.setattr(wa, "db", mock_db)
    monkeypatch.setattr(wa, "_inbox_lead_scope_filter", AsyncMock(return_value={}))

    result = await wa.get_whatsapp_inbox({"id": "admin", "role": "admin"}, limit=50, skip=0)
    assert result["count"] == 2
    # Newest first (B at 10:00)
    assert result["conversations"][0]["lead_id"] == "B"
    assert result["conversations"][1]["lead_id"] == "A"
