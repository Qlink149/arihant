"""Unit tests for Meta Lead Ads webhook helpers."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.services import meta_lead_ads_service as mls


def test_verify_hub_token(monkeypatch):
    monkeypatch.setattr(mls, "META_LEAD_VERIFY_TOKEN", "secret-token")
    assert mls.verify_hub_token("subscribe", "secret-token") is True
    assert mls.verify_hub_token("subscribe", "wrong") is False
    assert mls.verify_hub_token("unsubscribe", "secret-token") is False


def test_verify_signature(monkeypatch):
    monkeypatch.setattr(mls, "META_APP_SECRET", "appsecret")
    body = b'{"object":"page"}'
    sig = "sha256=" + hmac.new(b"appsecret", body, hashlib.sha256).hexdigest()
    assert mls.verify_signature(body, sig) is True
    assert mls.verify_signature(body, "sha256=deadbeef") is False
    assert mls.verify_signature(body, None) is False


def test_project_from_form_id_all_five(monkeypatch):
    monkeypatch.setattr(
        mls,
        "META_LEAD_FORM_PROJECT_MAP",
        {
            "2124096745052549": "reserve-16",
            "1874174036585908": "mira",
            "4309061012643289": "melange",
            "28059295887006740": "krsna",
            "1858929181319661": "vivriti",
        },
    )
    assert mls.project_from_form_id("1874174036585908")["id"] == "mira"
    assert mls.project_from_form_id("4309061012643289")["id"] == "melange"
    assert mls.project_from_form_id("999") is None


def test_map_field_data_full_name_and_phone():
    body = mls.map_field_data_to_intake(
        [
            {"name": "full_name", "values": ["Priya Sharma"]},
            {"name": "email", "values": ["priya@example.com"]},
            {"name": "phone_number", "values": ["+91 98765 43210"]},
        ],
        leadgen_id="lg1",
        form_id="4309061012643289",
    )
    assert body["first_name"] == "Priya"
    assert body["last_name"] == "Sharma"
    assert body["email"] == "priya@example.com"
    assert body["phone"] == "+91 98765 43210"
    assert body["consent"] is True
    assert body["source"] == "Facebook Lead Form"
    assert body["meta"]["leadgen_id"] == "lg1"


def test_extract_leadgen_events():
    payload = {
        "entry": [
            {
                "changes": [
                    {"field": "feed", "value": {}},
                    {
                        "field": "leadgen",
                        "value": {
                            "leadgen_id": "111",
                            "form_id": "4309061012643289",
                            "page_id": "383431805163700",
                        },
                    },
                ]
            }
        ]
    }
    ev = mls.extract_leadgen_events(payload)
    assert len(ev) == 1
    assert ev[0]["leadgen_id"] == "111"


@pytest.mark.asyncio
async def test_process_unmapped_form_skips_ingest(monkeypatch):
    monkeypatch.setattr(mls, "META_LEAD_FORM_PROJECT_MAP", {"1": "melange"})
    mock_db = MagicMock()
    mock_db.meta_lead_ads_logs.find_one = AsyncMock(return_value=None)
    mock_db.meta_lead_ads_logs.update_one = AsyncMock()
    monkeypatch.setattr(mls, "db", mock_db)
    ingest = AsyncMock()
    monkeypatch.setattr(mls, "ingest_lead", ingest)

    result = await mls.process_leadgen_event(
        {"leadgen_id": "lg-x", "form_id": "unmapped", "page_id": "p1"}
    )
    assert result["reason"] == "unmapped_form"
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_already_processed(monkeypatch):
    mock_db = MagicMock()
    mock_db.meta_lead_ads_logs.find_one = AsyncMock(
        return_value={"leadgen_id": "lg1", "success": True, "lead_id": "L1"}
    )
    monkeypatch.setattr(mls, "db", mock_db)
    ingest = AsyncMock()
    monkeypatch.setattr(mls, "ingest_lead", ingest)

    result = await mls.process_leadgen_event(
        {"leadgen_id": "lg1", "form_id": "4309061012643289"}
    )
    assert result["reason"] == "already_processed"
    assert result["lead_id"] == "L1"
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_happy_path_mira(monkeypatch):
    monkeypatch.setattr(
        mls,
        "META_LEAD_FORM_PROJECT_MAP",
        {"1874174036585908": "mira"},
    )
    mock_db = MagicMock()
    mock_db.meta_lead_ads_logs.find_one = AsyncMock(return_value=None)
    mock_db.meta_lead_ads_logs.update_one = AsyncMock()
    monkeypatch.setattr(mls, "db", mock_db)
    monkeypatch.setattr(
        mls,
        "fetch_lead_from_graph",
        AsyncMock(
            return_value={
                "form_id": "1874174036585908",
                "field_data": [
                    {"name": "first_name", "values": ["Asha"]},
                    {"name": "email", "values": ["asha@example.com"]},
                ],
            }
        ),
    )
    monkeypatch.setattr(
        mls,
        "ingest_lead",
        AsyncMock(return_value=({"success": True, "lead_id": "new-1", "deduped": False}, 201)),
    )

    result = await mls.process_leadgen_event(
        {
            "leadgen_id": "lg-mira",
            "form_id": "1874174036585908",
            "page_id": "383431805163700",
        }
    )
    assert result["success"] is True
    assert result["lead_id"] == "new-1"
    call_kwargs = mls.ingest_lead.await_args.kwargs
    assert call_kwargs["api_key"]["project_id"] == "mira"
    assert call_kwargs["body"]["first_name"] == "Asha"
