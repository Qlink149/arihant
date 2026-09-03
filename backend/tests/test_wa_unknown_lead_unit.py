"""Unit tests for WhatsApp unknown-lead auto-create."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crm.services import whatsapp_service as wa


@pytest.mark.asyncio
async def test_create_whatsapp_unknown_lead_assigns_admin(monkeypatch):
    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value=None)
    mock_db.leads.insert_one = AsyncMock()
    mock_db.users.find_one = AsyncMock(
        return_value={
            "id": "admin-1",
            "full_name": "Admin",
            "email": "roshni@arihantspaces.com",
        }
    )
    monkeypatch.setattr(wa, "db", mock_db)

    with patch.object(wa, "create_notification", AsyncMock()) as notif:
        lead = await wa.create_whatsapp_unknown_lead("9876543210", "Priya Sharma", notify=True)

    assert lead is not None
    assert lead["lead_status"] == "New"
    assert lead["lead_source"] == "WhatsApp"
    assert lead["assigned_to"] == "Admin"
    assert lead["assigned_user_id"] == "admin-1"
    assert lead["first_name"] == "Priya"
    assert lead["last_name"] == "Sharma"
    descs = [c["description"] for c in lead["context_updates"]]
    assert "Lead created from WhatsApp inbound (WATI)" in descs
    assert "Assigned to Admin from WhatsApp inbound (WATI)" in descs
    notif.assert_awaited()


@pytest.mark.asyncio
async def test_create_whatsapp_unknown_lead_skips_bad_phone(monkeypatch):
    mock_db = MagicMock()
    monkeypatch.setattr(wa, "db", mock_db)
    assert await wa.create_whatsapp_unknown_lead("", "") is None
    assert await wa.create_whatsapp_unknown_lead("123", "") is None
    mock_db.leads.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_create_whatsapp_unknown_lead_idempotent(monkeypatch):
    existing = {"id": "existing", "normalized_phone": "9876543210"}
    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value=existing)
    monkeypatch.setattr(wa, "db", mock_db)
    lead = await wa.create_whatsapp_unknown_lead("9876543210", "X")
    assert lead["id"] == "existing"
    mock_db.leads.insert_one.assert_not_called()
