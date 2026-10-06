"""WATI contact name must be the customer's, never the sending agent's / system user."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.services import whatsapp_service as wa
from crm.models.schemas.whatsapp_schemas import WhatsAppMessage

AGENT = {"id": "u1", "full_name": "Harish Marlecha"}
LEAD = {"id": "L1", "phone": "9999000001", "first_name": "Sony", "last_name": "Vengayil"}


def _setup(monkeypatch, lead):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")
    monkeypatch.setattr(wa, "WATI_API_TOKEN", "test-token")
    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value=lead)
    mock_db.leads.update_one = AsyncMock()
    monkeypatch.setattr(wa, "db", mock_db)
    ensure = AsyncMock()
    monkeypatch.setattr(wa, "_wati_ensure_contact", ensure)
    monkeypatch.setattr(wa, "_wati_send_template", AsyncMock(side_effect=RuntimeError("stop after contact step")))
    return ensure


def test_wati_contact_name_helper():
    assert wa._wati_contact_name(LEAD) == "Sony Vengayil"
    assert wa._wati_contact_name({"name": "Solo"}) == "Solo"
    assert wa._wati_contact_name({}) == ""
    assert wa._wati_contact_name(None) == ""


@pytest.mark.asyncio
async def test_send_to_lead_uses_lead_name_not_agent(monkeypatch):
    ensure = _setup(monkeypatch, LEAD)
    msg = WhatsAppMessage(destination="9999000001", template_name="t", template_parameters=[])
    await wa.send_to_lead("L1", msg, AGENT)
    ensure.assert_awaited_once()
    assert ensure.await_args.args[1] == "Sony Vengayil"


@pytest.mark.asyncio
async def test_send_without_lead_name_skips_add_contact(monkeypatch):
    ensure = _setup(monkeypatch, None)
    msg = WhatsAppMessage(destination="9999000001", template_name="t", template_parameters=[])
    await wa.send_message(msg, AGENT)
    ensure.assert_not_awaited()


@pytest.mark.asyncio
async def test_lead_ack_does_not_name_contact_after_system_user(monkeypatch):
    ensure = _setup(monkeypatch, LEAD)
    await wa.send_lead_ack("L1", LEAD)
    assert all(c.args[1] == "Sony Vengayil" for c in ensure.await_args_list)
    assert "System Auto-Ack" not in [c.args[1] for c in ensure.await_args_list]
