"""Unit tests for admin/manager lead nudge."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from crm.api.v1.endpoints import leads as leads_ep


@pytest.mark.asyncio
async def test_nudge_rep_forbidden(monkeypatch):
    monkeypatch.setattr(leads_ep, "db", MagicMock())
    with pytest.raises(HTTPException) as ei:
        await leads_ep.nudge_lead("lead-1", {"role": "presales", "id": "rep-1", "full_name": "Rep"})
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_nudge_admin_creates_notification_and_timeline(monkeypatch):
    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(
        return_value={
            "id": "lead-1",
            "first_name": "Priya",
            "last_name": "S",
            "assigned_user_id": "rep-9",
            "assigned_to_name": "Rep Nine",
        }
    )
    mock_db.notifications.find_one = AsyncMock(return_value=None)
    mock_db.leads.update_one = AsyncMock()
    monkeypatch.setattr(leads_ep, "db", mock_db)

    with patch.object(leads_ep, "create_notification", AsyncMock()) as notif:
        result = await leads_ep.nudge_lead(
            "lead-1",
            {"role": "admin", "id": "admin-1", "full_name": "Admin"},
        )

    assert result["ok"] is True
    assert result["deduped"] is False
    notif.assert_awaited()
    kwargs = notif.await_args.kwargs
    assert kwargs["title"] == "Nudge by Admin"
    assert kwargs["notification_type"] == "admin_nudge"
    assert kwargs["recipient_user_id"] == "rep-9"
    assert kwargs["lead_id"] == "lead-1"
    push = mock_db.leads.update_one.await_args.args[1]["$push"]["context_updates"]
    assert push["type"] == "nudge"
    assert push["description"] == "Nudge by Admin"
    set_fields = mock_db.leads.update_one.await_args.args[1]["$set"]
    assert set_fields["nudge_pending"] is True
    assert set_fields["last_nudged_by_user_id"] == "admin-1"
    assert "last_nudged_at_dt" in set_fields


@pytest.mark.asyncio
async def test_nudge_unassigned_400(monkeypatch):
    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value={"id": "lead-1", "first_name": "X"})
    monkeypatch.setattr(leads_ep, "db", mock_db)
    with patch.object(leads_ep, "resolve_user_id_by_full_name", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as ei:
            await leads_ep.nudge_lead("lead-1", {"role": "manager", "id": "m1", "full_name": "Mgr"})
    assert ei.value.status_code == 400
