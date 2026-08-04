"""Unit tests for Meta Conversions API (QualifiedLead) service."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from crm.services import meta_capi_service as capi


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_hash_field_empty_and_null():
    assert capi.hash_field(None) is None
    assert capi.hash_field("") is None
    assert capi.hash_field("   ") is None


def test_hash_field_trims_lowercases():
    assert capi.hash_field("  Foo@Example.COM ") == _sha256("foo@example.com")


def test_hash_phone_empty():
    assert capi.hash_phone(None) is None
    assert capi.hash_phone("") is None
    assert capi.hash_phone("+ -") is None


def test_hash_phone_keeps_country_code_strips_non_digits():
    assert capi.hash_phone("+91 98944-74820") == _sha256("919894474820")


def test_build_payload_omits_null_user_data_and_sets_event_id(monkeypatch):
    monkeypatch.setattr(capi, "META_ACCESS_TOKEN", "tok_abc")
    monkeypatch.setattr(capi, "META_TEST_EVENT_CODE", "")

    lead = {
        "id": "lead-1",
        "email": "A@B.com",
        "phone": "+91 99999 88888",
        "first_name": "Raj",
        "last_name": "",
        "location": None,
    }
    body = capi.build_payload(lead, event_time=1700000000)

    assert body["access_token"] == "tok_abc"
    assert "test_event_code" not in body
    event = body["data"][0]
    assert event["event_name"] == "QualifiedLead"
    assert event["event_time"] == 1700000000
    assert event["action_source"] == "system_generated"
    assert event["event_id"] == "arihant_lead-1_1700000000"
    assert set(event["user_data"].keys()) == {"em", "ph", "fn"}
    assert "ln" not in event["user_data"]
    assert "ct" not in event["user_data"]
    assert event["user_data"]["em"] == [_sha256("a@b.com")]
    assert event["user_data"]["ph"] == [_sha256("919999988888")]
    assert event["user_data"]["fn"] == [_sha256("raj")]


def test_build_payload_maps_location_to_ct_and_includes_test_code(monkeypatch):
    monkeypatch.setattr(capi, "META_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(capi, "META_TEST_EVENT_CODE", "TEST12345")

    lead = {
        "id": "L2",
        "first_name": "A",
        "last_name": "B",
        "location": " Chennai ",
        "work_phone": "919111122222",
    }
    body = capi.build_payload(lead, event_time=1)
    assert body["test_event_code"] == "TEST12345"
    ud = body["data"][0]["user_data"]
    assert ud["ct"] == [_sha256("chennai")]
    assert ud["ph"] == [_sha256("919111122222")]  # phone empty → work_phone


def _mock_response(status_code: int, payload=None, text: str = ""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if payload is not None:
        resp.json = MagicMock(return_value=payload)
        resp.text = text or str(payload)
    else:
        resp.json = MagicMock(side_effect=ValueError("not json"))
        resp.text = text
    return resp


@pytest.mark.asyncio
async def test_send_qualified_lead_event_success_writes_log(monkeypatch):
    monkeypatch.setattr(capi, "META_DATASET_ID", "dataset1")
    monkeypatch.setattr(capi, "META_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(capi, "META_API_VERSION", "v21.0")
    monkeypatch.setattr(capi, "META_TEST_EVENT_CODE", "")

    insert = AsyncMock()
    mock_db = MagicMock()
    mock_db.meta_capi_logs.insert_one = insert
    monkeypatch.setattr(capi, "db", mock_db)

    meta_body = {"events_received": 1}
    monkeypatch.setattr(
        capi,
        "_post_once",
        AsyncMock(return_value=_mock_response(200, meta_body)),
    )

    lead = {
        "id": "lead-ok",
        "email": "ok@example.com",
        "first_name": "Ok",
        "last_name": "Lead",
        "phone": "919876543210",
    }
    result = await capi.send_qualified_lead_event(lead)

    assert result["success"] is True
    assert result["response_status"] == 200
    assert result["event_id"].startswith("arihant_lead-ok_")
    assert result["error_message"] is None
    insert.assert_awaited_once()
    logged = insert.await_args.args[0]
    assert logged["success"] is True
    assert logged["lead_id"] == "lead-ok"
    assert logged["event_name"] == "QualifiedLead"
    assert "email" not in logged
    assert "phone" not in logged


@pytest.mark.asyncio
async def test_send_qualified_lead_event_5xx_retries_once(monkeypatch):
    monkeypatch.setattr(capi, "META_DATASET_ID", "dataset1")
    monkeypatch.setattr(capi, "META_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(capi, "META_API_VERSION", "v21.0")
    monkeypatch.setattr(capi, "RETRY_DELAY_SECONDS", 0)

    insert = AsyncMock()
    mock_db = MagicMock()
    mock_db.meta_capi_logs.insert_one = insert
    monkeypatch.setattr(capi, "db", mock_db)

    post = AsyncMock(
        side_effect=[
            _mock_response(503, {"error": "busy"}),
            _mock_response(200, {"events_received": 1}),
        ]
    )
    monkeypatch.setattr(capi, "_post_once", post)

    result = await capi.send_qualified_lead_event({"id": "lead-retry", "first_name": "R"})

    assert result["success"] is True
    assert post.await_count == 2
    insert.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_qualified_lead_event_network_error_does_not_throw(monkeypatch):
    monkeypatch.setattr(capi, "META_DATASET_ID", "dataset1")
    monkeypatch.setattr(capi, "META_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(capi, "RETRY_DELAY_SECONDS", 0)

    insert = AsyncMock()
    mock_db = MagicMock()
    mock_db.meta_capi_logs.insert_one = insert
    monkeypatch.setattr(capi, "db", mock_db)

    post = AsyncMock(side_effect=httpx.ConnectError("boom"))
    monkeypatch.setattr(capi, "_post_once", post)

    result = await capi.send_qualified_lead_event({"id": "lead-net", "first_name": "N"})

    assert result["success"] is False
    assert result["error_message"]
    assert "network" in result["error_message"].lower()
    assert post.await_count == 2
    insert.assert_awaited_once()
    assert insert.await_args.args[0]["success"] is False


@pytest.mark.asyncio
async def test_send_qualified_lead_event_missing_config_does_not_throw(monkeypatch):
    monkeypatch.setattr(capi, "META_DATASET_ID", "")
    monkeypatch.setattr(capi, "META_ACCESS_TOKEN", "")

    insert = AsyncMock()
    mock_db = MagicMock()
    mock_db.meta_capi_logs.insert_one = insert
    monkeypatch.setattr(capi, "db", mock_db)

    result = await capi.send_qualified_lead_event({"id": "lead-cfg"})

    assert result["success"] is False
    assert "not configured" in (result["error_message"] or "").lower()
    insert.assert_awaited_once()
