"""Unit tests for WhatsApp pricing send with optional project override."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.services import whatsapp_service as wa
from crm.services.lead_project_fields import label_for_project_key


MULTI_PROJECT_LEAD = {
    "id": "L1",
    "phone": "919999000001",
    "first_name": "Parag",
    "projects": ["Saligramam Melange", "ECR - Reserve 16"],
    "project": "Saligramam Melange; ECR - Reserve 16",
}


def test_label_for_project_key_prefers_lead_name():
    lead = {"projects": ["Saligramam Melange", "ECR - Reserve 16"]}
    assert label_for_project_key(lead, "reserve-16") == "ECR - Reserve 16"
    assert label_for_project_key(lead, "melange") == "Saligramam Melange"


@pytest.mark.asyncio
async def test_send_pricing_without_override_uses_primary_project(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")

    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value=MULTI_PROJECT_LEAD.copy())
    monkeypatch.setattr(wa, "db", mock_db)

    captured = {}

    async def fake_send_to_lead(lead_id, msg, current_user):
        captured["msg"] = msg
        return {"success": True}

    monkeypatch.setattr(wa, "send_to_lead", fake_send_to_lead)

    result = await wa.send_pricing("L1", {"id": "u1"})
    assert result["success"] is True
    params = {p["name"]: p["value"] for p in captured["msg"].template_parameters}
    assert params["2"] == "Saligramam Melange"
    assert "12,800" in params["3"]


@pytest.mark.asyncio
async def test_send_pricing_with_reserve16_override(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")

    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value=MULTI_PROJECT_LEAD.copy())
    monkeypatch.setattr(wa, "db", mock_db)

    captured = {}

    async def fake_send_to_lead(lead_id, msg, current_user):
        captured["msg"] = msg
        return {"success": True}

    monkeypatch.setattr(wa, "send_to_lead", fake_send_to_lead)

    result = await wa.send_pricing("L1", {"id": "u1"}, project="reserve-16")
    assert result["success"] is True
    params = {p["name"]: p["value"] for p in captured["msg"].template_parameters}
    assert params["2"] == "ECR - Reserve 16"
    assert "3,500" in params["3"]


@pytest.mark.asyncio
async def test_send_pricing_unpriced_project_returns_error(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")

    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value=MULTI_PROJECT_LEAD.copy())
    monkeypatch.setattr(wa, "db", mock_db)

    result = await wa.send_pricing("L1", {"id": "u1"}, project="krsna")
    assert result["success"] is False
    assert "not configured" in result["error"].lower()


@pytest.mark.asyncio
async def test_send_pricing_disabled_provider(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "disabled")
    result = await wa.send_pricing("L1", {"id": "u1"})
    assert result["success"] is False
