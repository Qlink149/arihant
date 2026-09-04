"""Unit tests for nudge_pending set/clear and list filter."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crm.services.lead_search import build_leads_list_query
from crm.services.nudge_pending import actor_is_lead_assignee, clear_nudge_pending_if_assignee


def test_actor_is_lead_assignee():
    lead = {"assigned_user_id": "rep-1"}
    assert actor_is_lead_assignee(lead, {"id": "rep-1"}) is True
    assert actor_is_lead_assignee(lead, {"id": "admin-1"}) is False
    assert actor_is_lead_assignee(lead, {}) is False
    assert actor_is_lead_assignee({"assigned_user_id": ""}, {"id": "rep-1"}) is False


@pytest.mark.asyncio
async def test_clear_nudge_pending_assignee_clears(monkeypatch):
    mock_db = MagicMock()
    mock_db.leads.update_one = AsyncMock()
    with patch("crm.services.nudge_pending.db", mock_db):
        cleared = await clear_nudge_pending_if_assignee(
            "lead-1",
            {"id": "rep-1", "full_name": "Rep"},
            lead={"assigned_user_id": "rep-1", "nudge_pending": True},
        )
    assert cleared is True
    mock_db.leads.update_one.assert_awaited()
    filt, update = mock_db.leads.update_one.await_args.args
    assert filt == {"id": "lead-1", "nudge_pending": True}
    assert update["$set"]["nudge_pending"] is False


@pytest.mark.asyncio
async def test_clear_nudge_pending_non_assignee_noop(monkeypatch):
    mock_db = MagicMock()
    mock_db.leads.update_one = AsyncMock()
    with patch("crm.services.nudge_pending.db", mock_db):
        cleared = await clear_nudge_pending_if_assignee(
            "lead-1",
            {"id": "admin-1", "full_name": "Admin"},
            lead={"assigned_user_id": "rep-1", "nudge_pending": True},
        )
    assert cleared is False
    mock_db.leads.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_nudge_pending_already_false_noop(monkeypatch):
    mock_db = MagicMock()
    mock_db.leads.update_one = AsyncMock()
    with patch("crm.services.nudge_pending.db", mock_db):
        cleared = await clear_nudge_pending_if_assignee(
            "lead-1",
            {"id": "rep-1"},
            lead={"assigned_user_id": "rep-1", "nudge_pending": False},
        )
    assert cleared is False
    mock_db.leads.update_one.assert_not_awaited()


def test_build_leads_list_query_nudge_pending():
    q = build_leads_list_query({}, nudge_pending=True)
    assert {"nudge_pending": True} in (q.get("$and") or [q])


def test_build_leads_list_query_nudge_pending_false():
    q = build_leads_list_query({}, nudge_pending=False)
    assert {"nudge_pending": False} in (q.get("$and") or [q])
