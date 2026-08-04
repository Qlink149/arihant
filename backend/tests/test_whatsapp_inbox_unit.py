"""Unit tests for peer-first WhatsApp inbox helpers and aggregation."""

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


def test_inbox_conversation_key():
    assert wa._inbox_conversation_key(lead_id="L1", peer="9199") == "lead:L1"
    assert wa._inbox_conversation_key(lead_id=None, peer="9199") == "peer:9199"


def test_is_mine_lead_by_user_id_and_name():
    user = {"id": "u1", "full_name": "Rep One"}
    assert wa._is_mine_lead({"assigned_user_id": "u1"}, user) is True
    assert wa._is_mine_lead({"assigned_to_name": "Rep One"}, user) is True
    assert wa._is_mine_lead({"assigned_to_name": "Someone Else"}, user) is False
    assert wa._is_mine_lead({}, user) is False


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


def _fake_peer_agg(pairs):
    class FakeAgg:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            for peer, last in pairs:
                yield {"_id": peer, "last": last}

    return FakeAgg()


@pytest.mark.asyncio
async def test_get_whatsapp_inbox_peer_first_excludes_silent_includes_unmatched(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")
    monkeypatch.setattr(wa, "WATI_CHANNEL_PHONE", "")

    last_owned = {
        "content": "Thanks boss",
        "direction": "inbound",
        "message_type": "text",
        "created_at": "2026-07-20T10:00:00+00:00",
        "created_at_dt": datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
        "_sort_dt": datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
    }
    last_unknown = {
        "content": "Who is this?",
        "direction": "inbound",
        "created_at": "2026-07-21T11:00:00+00:00",
        "created_at_dt": datetime(2026, 7, 21, 11, 0, tzinfo=timezone.utc),
        "_sort_dt": datetime(2026, 7, 21, 11, 0, tzinfo=timezone.utc),
    }

    async def fake_aggregate_peers(_cap=500):
        # Newest first — unknown then owned. Silent lead (9122…) has no peer row.
        return [
            ("919999999999", last_unknown),
            ("911111111111", last_owned),
        ]

    async def fake_resolve(peers):
        return {
            "911111111111": {
                "id": "L1",
                "first_name": "Owned",
                "last_name": "Lead",
                "phone": "911111111111",
                "project": "ECR - Reserve 16",
                "assigned_user_id": "u1",
                "assigned_to_name": "Rep One",
                "status": "Interested",
            }
        }

    async def fake_scope(_user):
        return {"assigned_user_id": "u1"}

    async def fake_in_scope(ids, _scope):
        return set(ids)  # L1 in scope

    async def fake_unread(_uid, peers):
        return {p: 0 for p in peers}

    async def fake_session(_phone):
        return True

    monkeypatch.setattr(wa, "_inbox_aggregate_peers", fake_aggregate_peers)
    monkeypatch.setattr(wa, "_resolve_leads_for_peers", fake_resolve)
    monkeypatch.setattr(wa, "_inbox_lead_scope_filter", fake_scope)
    monkeypatch.setattr(wa, "_inbox_in_scope_lead_ids", fake_in_scope)
    monkeypatch.setattr(wa, "_inbox_unread_counts", fake_unread)
    monkeypatch.setattr(wa, "_is_session_open", fake_session)

    result = await wa.get_whatsapp_inbox(
        {"id": "u1", "role": "rep", "full_name": "Rep One"},
        limit=50,
        skip=0,
    )
    assert result["count"] == 2
    assert result["has_more"] is False
    keys = [c["conversation_key"] for c in result["conversations"]]
    assert keys[0] == "peer:919999999999"
    assert result["conversations"][0]["is_unmatched"] is True
    assert result["conversations"][0]["display_name"] == "Unknown"
    assert result["conversations"][1]["lead_id"] == "L1"
    assert result["conversations"][1]["display_name"] == "Owned Lead"
    assert "Thanks" in result["conversations"][1]["last_message_preview"]


@pytest.mark.asyncio
async def test_get_whatsapp_inbox_hides_out_of_scope_matched(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")
    monkeypatch.setattr(wa, "WATI_CHANNEL_PHONE", "")

    last = {
        "content": "Hi other",
        "direction": "inbound",
        "created_at": "2026-07-21T10:00:00+00:00",
        "_sort_dt": datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc),
    }

    async def fake_aggregate_peers(_cap=500):
        return [("913333333333", last)]

    async def fake_resolve(_peers):
        return {
            "913333333333": {
                "id": "L3",
                "first_name": "Other",
                "phone": "913333333333",
                "assigned_user_id": "other",
            }
        }

    monkeypatch.setattr(wa, "_inbox_aggregate_peers", fake_aggregate_peers)
    monkeypatch.setattr(wa, "_resolve_leads_for_peers", fake_resolve)
    monkeypatch.setattr(wa, "_inbox_lead_scope_filter", AsyncMock(return_value={"assigned_user_id": "u1"}))
    monkeypatch.setattr(wa, "_inbox_in_scope_lead_ids", AsyncMock(return_value=set()))  # L3 out
    monkeypatch.setattr(wa, "_inbox_unread_counts", AsyncMock(return_value={"913333333333": 0}))
    monkeypatch.setattr(wa, "_is_session_open", AsyncMock(return_value=False))

    result = await wa.get_whatsapp_inbox(
        {"id": "u1", "role": "rep", "full_name": "Rep One"}, limit=50, skip=0
    )
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_get_whatsapp_inbox_admin_mine_and_unread_filters(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")
    monkeypatch.setattr(wa, "WATI_CHANNEL_PHONE", "")

    async def fake_aggregate_peers(_cap=500):
        return [
            (
                "911111111111",
                {
                    "content": "Hi A",
                    "direction": "outbound",
                    "created_at": "2026-07-21T09:00:00+00:00",
                    "_sort_dt": datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc),
                },
            ),
            (
                "912222222222",
                {
                    "content": "Hi B",
                    "direction": "inbound",
                    "created_at": "2026-07-21T10:00:00+00:00",
                    "_sort_dt": datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc),
                },
            ),
        ]

    async def fake_resolve(_peers):
        return {
            "911111111111": {
                "id": "A",
                "first_name": "A",
                "phone": "911111111111",
                "project": "P1",
                "assigned_user_id": "admin",
                "assigned_to_name": "Admin",
            },
            "912222222222": {
                "id": "B",
                "first_name": "B",
                "phone": "912222222222",
                "project": "P2",
                "assigned_user_id": "other",
                "assigned_to_name": "Other",
            },
        }

    monkeypatch.setattr(wa, "_inbox_aggregate_peers", fake_aggregate_peers)
    monkeypatch.setattr(wa, "_resolve_leads_for_peers", fake_resolve)
    monkeypatch.setattr(wa, "_inbox_lead_scope_filter", AsyncMock(return_value={}))
    monkeypatch.setattr(
        wa,
        "_inbox_in_scope_lead_ids",
        AsyncMock(side_effect=lambda ids, _s: set(ids)),
    )
    monkeypatch.setattr(
        wa,
        "_inbox_unread_counts",
        AsyncMock(return_value={"911111111111": 0, "912222222222": 2}),
    )
    monkeypatch.setattr(wa, "_is_session_open", AsyncMock(return_value=False))

    admin = {"id": "admin", "role": "admin", "full_name": "Admin"}

    all_rows = await wa.get_whatsapp_inbox(admin, limit=50, skip=0, filter_mode="all")
    assert all_rows["count"] == 2

    unread = await wa.get_whatsapp_inbox(admin, limit=50, skip=0, filter_mode="unread")
    assert unread["count"] == 1
    assert unread["conversations"][0]["lead_id"] == "B"
    assert unread["conversations"][0]["unread_count"] == 2

    mine = await wa.get_whatsapp_inbox(admin, limit=50, skip=0, filter_mode="mine")
    assert mine["count"] == 1
    assert mine["conversations"][0]["lead_id"] == "A"

    page = await wa.get_whatsapp_inbox(admin, limit=1, skip=0, filter_mode="all")
    assert len(page["conversations"]) == 1
    assert page["has_more"] is True
    assert page["count"] == 2


@pytest.mark.asyncio
async def test_mark_whatsapp_inbox_read(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")
    update = AsyncMock()
    mock_db = MagicMock()
    mock_db.whatsapp_thread_reads.update_one = update
    monkeypatch.setattr(wa, "db", mock_db)

    result = await wa.mark_whatsapp_inbox_read(
        {"id": "u1"}, peer_phone="9894474820"
    )
    assert result["success"] is True
    assert result["peer_phone"] == "919894474820"
    update.assert_awaited_once()
