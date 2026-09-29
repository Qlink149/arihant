"""Unit tests for the Channel Partner lead-submission webhook."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.services import channel_partner_leads_service as cps


def test_verify_webhook_secret(monkeypatch):
    monkeypatch.setattr(cps, "CHANNEL_PARTNER_WEBHOOK_SECRET", "cp-secret")
    assert cps.verify_webhook_secret(token="cp-secret") is True
    assert cps.verify_webhook_secret(header_secret="cp-secret") is True
    assert cps.verify_webhook_secret(token="wrong") is False
    assert cps.verify_webhook_secret(token=None, header_secret=None) is False


def test_verify_webhook_secret_empty_env_fails_closed(monkeypatch):
    monkeypatch.setattr(cps, "CHANNEL_PARTNER_WEBHOOK_SECRET", "")
    assert cps.verify_webhook_secret(token="anything") is False


def test_resolve_project_all_three_forms():
    assert cps.resolve_channel_partner_project("Anna Nagar - Mira")["id"] == "mira"
    assert cps.resolve_channel_partner_project("Saligramam Melange")["id"] == "melange"
    # exact hidden-field spelling from the client's forms (no space before 16)
    assert cps.resolve_channel_partner_project("ECR - Reserve16")["id"] == "reserve-16"
    # spaced variant should resolve identically
    assert cps.resolve_channel_partner_project("ECR - Reserve 16")["id"] == "reserve-16"


def test_resolve_project_unknown_rejected():
    assert cps.resolve_channel_partner_project("Krsna") is None  # not one of the 3 CP forms
    assert cps.resolve_channel_partner_project("") is None
    assert cps.resolve_channel_partner_project(None) is None


def test_resolve_channel_partner_name_exact_and_case_insensitive():
    value, matched = cps.resolve_channel_partner_name("Home Konnect")
    assert (value, matched) == ("Home Konnect", True)
    value, matched = cps.resolve_channel_partner_name("home konnect")
    assert (value, matched) == ("Home Konnect", True)
    value, matched = cps.resolve_channel_partner_name("  propmart  ")
    assert (value, matched) == ("Propmart", True)


def test_resolve_channel_partner_name_unmatched_or_blank():
    value, matched = cps.resolve_channel_partner_name("Some New Agency")
    assert value == "Some New Agency"
    assert matched is False
    value, matched = cps.resolve_channel_partner_name("")
    assert (value, matched) == (None, False)
    value, matched = cps.resolve_channel_partner_name(None)
    assert (value, matched) == (None, False)


def _mock_cp_db():
    mock_db = MagicMock()
    mock_db.channel_partner_leads_logs.insert_one = AsyncMock()
    return mock_db


def _submission(**overrides):
    body = {
        "first_name": "Priya",
        "last_name": "Sharma",
        "email": "priya@example.com",
        "mob_number": "9876543210",
        "channel_partner": "Home Konnect",
        "project": "Saligramam Melange",
        "comments": "Interested in 3BHK",
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_unknown_project_rejected_400(monkeypatch):
    monkeypatch.setattr(cps, "db", _mock_cp_db())
    ingest = AsyncMock()
    monkeypatch.setattr(cps, "ingest_lead", ingest)

    result, status = await cps.process_channel_partner_submission(_submission(project="Some Other Project"))
    assert status == 400
    assert result["reason"] == "unknown_project"
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_first_name_rejected_400(monkeypatch):
    monkeypatch.setattr(cps, "db", _mock_cp_db())
    ingest = AsyncMock()
    monkeypatch.setattr(cps, "ingest_lead", ingest)

    result, status = await cps.process_channel_partner_submission(_submission(first_name=""))
    assert status == 400
    assert result["reason"] == "missing_required_field"
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_phone_rejected_400(monkeypatch):
    monkeypatch.setattr(cps, "db", _mock_cp_db())
    ingest = AsyncMock()
    monkeypatch.setattr(cps, "ingest_lead", ingest)

    result, status = await cps.process_channel_partner_submission(_submission(mob_number=""))
    assert status == 400
    assert result["reason"] == "missing_required_field"
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_last_name_still_succeeds(monkeypatch):
    monkeypatch.setattr(cps, "db", _mock_cp_db())
    monkeypatch.setattr(
        cps, "ingest_lead",
        AsyncMock(return_value=({"success": True, "lead_id": "L1", "deduped": False}, 201)),
    )

    result, status = await cps.process_channel_partner_submission(_submission(last_name=""))
    assert status == 201
    call_kwargs = cps.ingest_lead.await_args.kwargs
    assert call_kwargs["body"]["last_name"] == ""


@pytest.mark.asyncio
async def test_duplicate_phone_returns_409_and_never_creates(monkeypatch):
    """The core ask: an existing phone anywhere in the CRM must reject, not merge."""
    monkeypatch.setattr(cps, "db", _mock_cp_db())
    ingest = AsyncMock(return_value=({"success": False, "duplicate": True, "lead_id": "EXISTING1"}, 409))
    monkeypatch.setattr(cps, "ingest_lead", ingest)

    result, status = await cps.process_channel_partner_submission(_submission())
    assert status == 409
    assert result["status"] == "duplicate"
    assert "already exists" in result["message"].lower()
    # duplicate_policy="reject" must be requested — this is what makes it a hard reject.
    call_kwargs = ingest.await_args.kwargs
    assert call_kwargs["duplicate_policy"] == "reject"


@pytest.mark.asyncio
async def test_idempotent_10s_double_submit_returns_200(monkeypatch):
    monkeypatch.setattr(cps, "db", _mock_cp_db())
    monkeypatch.setattr(
        cps, "ingest_lead",
        AsyncMock(return_value=({"success": True, "lead_id": "L2", "deduped": True}, 200)),
    )

    result, status = await cps.process_channel_partner_submission(_submission())
    assert status == 200
    assert result["status"] == "ok"
    assert result["deduped"] is True


@pytest.mark.asyncio
async def test_unmatched_partner_still_creates_lead_flagged(monkeypatch):
    monkeypatch.setattr(cps, "db", _mock_cp_db())
    monkeypatch.setattr(
        cps, "ingest_lead",
        AsyncMock(return_value=({"success": True, "lead_id": "L3", "deduped": False}, 201)),
    )

    result, status = await cps.process_channel_partner_submission(
        _submission(channel_partner="Some Brand New Agency Nobody Listed")
    )
    assert status == 201
    call_kwargs = cps.ingest_lead.await_args.kwargs
    assert call_kwargs["api_key"]["channel_partner"] == "Some Brand New Agency Nobody Listed"
    assert call_kwargs["body"]["meta"]["channel_partner_unmatched"] is True


@pytest.mark.asyncio
async def test_blank_partner_still_creates_lead(monkeypatch):
    monkeypatch.setattr(cps, "db", _mock_cp_db())
    monkeypatch.setattr(
        cps, "ingest_lead",
        AsyncMock(return_value=({"success": True, "lead_id": "L4", "deduped": False}, 201)),
    )

    result, status = await cps.process_channel_partner_submission(_submission(channel_partner=""))
    assert status == 201
    call_kwargs = cps.ingest_lead.await_args.kwargs
    assert call_kwargs["api_key"]["channel_partner"] is None


@pytest.mark.asyncio
async def test_happy_path_all_three_projects(monkeypatch):
    monkeypatch.setattr(cps, "db", _mock_cp_db())
    monkeypatch.setattr(
        cps, "ingest_lead",
        AsyncMock(return_value=({"success": True, "lead_id": "L5", "deduped": False}, 201)),
    )

    for project_value, expected_id in (
        ("Anna Nagar - Mira", "mira"),
        ("ECR - Reserve16", "reserve-16"),
        ("Saligramam Melange", "melange"),
    ):
        result, status = await cps.process_channel_partner_submission(_submission(project=project_value))
        assert status == 201
        assert result["status"] == "created"
        call_kwargs = cps.ingest_lead.await_args.kwargs
        assert call_kwargs["api_key"]["id"] == f"channel-partner:{expected_id}"
        assert call_kwargs["api_key"]["project_id"] == expected_id
        assert call_kwargs["api_key"]["channel_partner"] == "Home Konnect"
        assert call_kwargs["api_key"]["comments"] == "Interested in 3BHK"
        assert call_kwargs["body"]["source"] == "channel partner"
        assert call_kwargs["body"]["phone"] == "9876543210"
        assert call_kwargs["duplicate_policy"] == "reject"


# ── Endpoint-level smoke tests (FastAPI TestClient, no live server/DB) ──────


def test_webhook_rejects_missing_secret(monkeypatch):
    from fastapi.testclient import TestClient
    from crm.main import app

    monkeypatch.setattr(cps, "CHANNEL_PARTNER_WEBHOOK_SECRET", "real-secret")
    client = TestClient(app)
    response = client.post(
        "/api/channel-partner/leads/webhook",
        json={"first_name": "X", "mob_number": "9000000000", "project": "Saligramam Melange"},
    )
    assert response.status_code == 401
    assert response.json()["reason"] == "unauthorized"


def test_webhook_accepts_json_and_returns_created(monkeypatch):
    from fastapi.testclient import TestClient
    from crm.main import app

    monkeypatch.setattr(cps, "CHANNEL_PARTNER_WEBHOOK_SECRET", "real-secret")
    monkeypatch.setattr(cps, "db", _mock_cp_db())
    monkeypatch.setattr(
        cps, "ingest_lead",
        AsyncMock(return_value=({"success": True, "lead_id": "L-JSON", "deduped": False}, 201)),
    )

    client = TestClient(app)
    response = client.post(
        "/api/channel-partner/leads/webhook?token=real-secret",
        json=_submission(),
    )
    assert response.status_code == 201
    assert response.json() == {"status": "created", "lead_id": "L-JSON"}


def test_webhook_accepts_form_encoded_body(monkeypatch):
    """The client's landing pages may post as a plain HTML form, not JSON."""
    from fastapi.testclient import TestClient
    from crm.main import app

    monkeypatch.setattr(cps, "CHANNEL_PARTNER_WEBHOOK_SECRET", "real-secret")
    monkeypatch.setattr(cps, "db", _mock_cp_db())
    monkeypatch.setattr(
        cps, "ingest_lead",
        AsyncMock(return_value=({"success": True, "lead_id": "L-FORM", "deduped": False}, 201)),
    )

    client = TestClient(app)
    response = client.post(
        "/api/channel-partner/leads/webhook?token=real-secret",
        data=_submission(),  # application/x-www-form-urlencoded
    )
    assert response.status_code == 201
    assert response.json()["lead_id"] == "L-FORM"


def test_webhook_returns_409_on_duplicate_via_header_secret(monkeypatch):
    from fastapi.testclient import TestClient
    from crm.main import app

    monkeypatch.setattr(cps, "CHANNEL_PARTNER_WEBHOOK_SECRET", "real-secret")
    monkeypatch.setattr(cps, "db", _mock_cp_db())
    monkeypatch.setattr(
        cps, "ingest_lead",
        AsyncMock(return_value=({"success": False, "duplicate": True, "lead_id": "EXIST"}, 409)),
    )

    client = TestClient(app)
    response = client.post(
        "/api/channel-partner/leads/webhook",
        headers={"X-Webhook-Secret": "real-secret"},
        json=_submission(),
    )
    assert response.status_code == 409
    assert response.json()["status"] == "duplicate"
