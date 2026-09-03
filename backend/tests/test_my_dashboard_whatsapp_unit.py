"""Unit tests for My Dashboard WhatsApp health helper (#30)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from crm.services import whatsapp_service as wa


@pytest.mark.asyncio
async def test_dashboard_whatsapp_rep_scope_excludes_unmatched_and_out_of_scope(monkeypatch):
    last_mine = {
        "content": "Need help",
        "direction": "inbound",
        "created_at": "2026-09-03T08:00:00+00:00",
        "created_at_dt": datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc),
        "_has_customer_reply": True,
        "_has_outbound": True,
    }
    last_other = {
        "content": "Other thread",
        "direction": "inbound",
        "created_at": "2026-09-03T09:00:00+00:00",
        "created_at_dt": datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc),
        "_has_customer_reply": True,
        "_has_outbound": False,
    }
    last_unknown = {
        "content": "Who?",
        "direction": "inbound",
        "created_at": "2026-09-03T10:00:00+00:00",
        "created_at_dt": datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc),
        "_has_customer_reply": True,
        "_has_outbound": False,
    }

    async def fake_aggregate(_cap=500):
        return [
            ("919999999999", last_unknown),
            ("913333333333", last_other),
            ("911111111111", last_mine),
        ]

    async def fake_resolve(_peers):
        return {
            "911111111111": {
                "id": "L1",
                "first_name": "Mine",
                "phone": "911111111111",
                "assigned_user_id": "u1",
                "lead_status": "Interested",
            },
            "913333333333": {
                "id": "L2",
                "first_name": "Other",
                "phone": "913333333333",
                "assigned_user_id": "u2",
                "lead_status": "New",
            },
        }

    async def fake_in_scope(ids, scope):
        # Only L1 when scope is rep filter
        assert scope  # rep-scoped
        return {"L1"} if "L1" in ids else set()

    async def fake_unread(_uid, peers):
        return {p: (2 if p == "911111111111" else 0) for p in peers}

    monkeypatch.setattr(wa, "_inbox_aggregate_peers", fake_aggregate)
    monkeypatch.setattr(wa, "_resolve_leads_for_peers", fake_resolve)
    monkeypatch.setattr(wa, "_inbox_in_scope_lead_ids", fake_in_scope)
    monkeypatch.setattr(wa, "_inbox_unread_counts", fake_unread)
    monkeypatch.setattr(wa, "_peers_inbound_today", AsyncMock(return_value={"911111111111"}))
    monkeypatch.setattr(wa, "_count_inbound_today", AsyncMock(return_value=3))

    result = await wa.get_my_dashboard_whatsapp(
        subject_id="u1",
        subject_name="Rep One",
        org_wide=False,
        filter_mode="all",
    )

    assert result["org_wide"] is False
    assert result["tiles"]["unread_mine"] == 1
    assert result["tiles"]["awaiting_agent_reply"] == 1
    assert result["tiles"]["customer_replied_today"] == 3
    assert result["count"] == 1
    assert result["conversations"][0]["lead_id"] == "L1"
    assert result["conversations"][0]["unread_count"] == 2
    assert result["conversations"][0]["last_direction"] == "inbound"


@pytest.mark.asyncio
async def test_dashboard_whatsapp_org_wide_includes_all_matched(monkeypatch):
    last_a = {
        "content": "A",
        "direction": "inbound",
        "created_at": "2026-09-03T08:00:00+00:00",
        "_has_customer_reply": True,
        "_has_outbound": False,
    }
    last_b = {
        "content": "B",
        "direction": "outbound",
        "created_at": "2026-09-03T07:00:00+00:00",
        "_has_customer_reply": True,
        "_has_outbound": True,
    }

    async def fake_aggregate(_cap=500):
        return [("9111", last_a), ("9222", last_b)]

    async def fake_resolve(_peers):
        return {
            "9111": {"id": "LA", "first_name": "A", "phone": "9111", "assigned_user_id": "r1"},
            "9222": {"id": "LB", "first_name": "B", "phone": "9222", "assigned_user_id": "r2"},
        }

    async def fake_in_scope(ids, scope):
        assert scope == {}
        return set(ids)

    async def fake_unread(uid, peers):
        assert uid == "admin1"  # personal unread even in org-wide
        return {"9111": 1, "9222": 0}

    monkeypatch.setattr(wa, "_inbox_aggregate_peers", fake_aggregate)
    monkeypatch.setattr(wa, "_resolve_leads_for_peers", fake_resolve)
    monkeypatch.setattr(wa, "_inbox_in_scope_lead_ids", fake_in_scope)
    monkeypatch.setattr(wa, "_inbox_unread_counts", fake_unread)
    monkeypatch.setattr(wa, "_peers_inbound_today", AsyncMock(return_value={"9111"}))
    monkeypatch.setattr(wa, "_count_inbound_today", AsyncMock(return_value=1))

    result = await wa.get_my_dashboard_whatsapp(
        subject_id="admin1",
        subject_name="Admin",
        org_wide=True,
        filter_mode="needs_followup",
    )

    assert result["org_wide"] is True
    assert result["tiles"]["unread_mine"] == 1
    assert result["tiles"]["awaiting_agent_reply"] == 1
    assert result["count"] == 1
    assert result["conversations"][0]["lead_id"] == "LA"
    assert result["filter"] == "needs_followup"


@pytest.mark.asyncio
async def test_dashboard_whatsapp_not_contacted_filter(monkeypatch):
    last = {
        "content": "Hi",
        "direction": "inbound",
        "created_at": "2026-09-03T08:00:00+00:00",
        "_has_customer_reply": True,
        "_has_outbound": False,
    }

    async def fake_aggregate(_cap=500):
        return [("9111", last)]

    async def fake_resolve(_peers):
        return {"9111": {"id": "L1", "first_name": "X", "phone": "9111"}}

    monkeypatch.setattr(wa, "_inbox_aggregate_peers", fake_aggregate)
    monkeypatch.setattr(wa, "_resolve_leads_for_peers", fake_resolve)
    monkeypatch.setattr(wa, "_inbox_in_scope_lead_ids", AsyncMock(return_value={"L1"}))
    monkeypatch.setattr(wa, "_inbox_unread_counts", AsyncMock(return_value={"9111": 0}))
    monkeypatch.setattr(wa, "_peers_inbound_today", AsyncMock(return_value=set()))
    monkeypatch.setattr(wa, "_count_inbound_today", AsyncMock(return_value=0))

    result = await wa.get_my_dashboard_whatsapp(
        subject_id="u1",
        subject_name="Rep",
        org_wide=True,
        filter_mode="not_contacted",
    )
    assert result["count"] == 1

    result_replied = await wa.get_my_dashboard_whatsapp(
        subject_id="u1",
        subject_name="Rep",
        org_wide=True,
        filter_mode="replied",
    )
    assert result_replied["count"] == 1
