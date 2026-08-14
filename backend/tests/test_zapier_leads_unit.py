"""Unit tests for Zapier Meta Instant Form webhook helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.services import zapier_leads_service as zls


def test_verify_webhook_secret(monkeypatch):
    monkeypatch.setattr(zls, "ZAPIER_WEBHOOK_SECRET", "zap-secret")
    assert zls.verify_webhook_secret(token="zap-secret") is True
    assert zls.verify_webhook_secret(header_secret="zap-secret") is True
    assert zls.verify_webhook_secret(token="wrong") is False
    assert zls.verify_webhook_secret(token=None, header_secret=None) is False


def test_verify_webhook_secret_empty_env(monkeypatch):
    monkeypatch.setattr(zls, "ZAPIER_WEBHOOK_SECRET", "")
    assert zls.verify_webhook_secret(token="anything") is False


def test_project_from_form_id_all_five(monkeypatch):
    monkeypatch.setattr(
        zls,
        "META_LEAD_FORM_PROJECT_MAP",
        {
            "2124096745052549": "reserve-16",
            "1874174036585908": "mira",
            "4309061012643289": "melange",
            "28059295887006740": "krsna",
            "1858929181319661": "vivriti",
        },
    )
    assert zls.project_from_form_id("4309061012643289")["id"] == "melange"
    assert zls.project_from_form_id("2124096745052549")["id"] == "reserve-16"
    assert zls.project_from_form_id("999") is None
    assert zls.project_from_form_id(None) is None


def test_map_zap_optional_blanks():
    body = zls.map_zap_payload_to_intake(
        {
            "Form ID": "4309061012643289",
            "Phone Number": "+919790942415",
            "First Name": "",
            "Last Name": "",
            "Email": "",
            "Budget": "",
            "Site Visit Preference": "",
        },
        leadgen_id="lg1",
        form_id="4309061012643289",
    )
    assert body["first_name"] == "Unknown"
    assert body["last_name"] == ""
    assert body["phone"] == "+919790942415"
    assert body["email"] is None
    assert "budget" not in body
    assert "schedule_visit" not in body
    assert body["source"] == "Facebook Lead Form"
    assert body["meta"]["via"] == "zapier"
    assert body["meta"]["leadgen_id"] == "lg1"


def test_map_zap_client_field_names():
    body = zls.map_zap_payload_to_intake(
        {
            "Created At": "2026-08-13T10:00:00+05:30",
            "Lead ID": "123",
            "Form ID": "2124096745052549",
            "First Name": "Manish",
            "Last Name": "Thakkar",
            "Email": "ruling.piping-5n@icloud.com",
            "Phone Number": "+918754025211",
            "Budget": "1.5 Cr",
            "Site Visit Preference": "Weekend",
        },
        leadgen_id="123",
        form_id="2124096745052549",
    )
    assert body["first_name"] == "Manish"
    assert body["last_name"] == "Thakkar"
    assert body["email"] == "ruling.piping-5n@icloud.com"
    assert body["phone"] == "+918754025211"
    assert body["budget"] == "1.5 Cr"
    assert body["schedule_visit"] == "Weekend"
    assert body["meta"]["created_at"] == "2026-08-13T10:00:00+05:30"


def test_map_zap_duplicate_full_name_split():
    body = zls.map_zap_payload_to_intake(
        {
            "Form ID": "1874174036585908",
            "First Name": "Iyda Robert",
            "Last Name": "Iyda Robert",
            "Phone Number": "916382848893",
        },
        leadgen_id="lg-dup",
        form_id="1874174036585908",
    )
    assert body["first_name"] == "Iyda"
    assert body["last_name"] == "Robert"


@pytest.mark.asyncio
async def test_process_unmapped_form_skips_ingest(monkeypatch):
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {"1": "melange"})
    mock_db = MagicMock()
    mock_db.zapier_leads_logs.find_one = AsyncMock(return_value=None)
    mock_db.zapier_leads_logs.update_one = AsyncMock()
    monkeypatch.setattr(zls, "db", mock_db)
    ingest = AsyncMock()
    monkeypatch.setattr(zls, "ingest_lead", ingest)

    result = await zls.process_zapier_lead(
        {"Lead ID": "lg-x", "Form ID": "unmapped", "Phone Number": "1"}
    )
    assert result["reason"] == "unmapped_form"
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_missing_email_and_phone(monkeypatch):
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {"4309061012643289": "melange"})
    mock_db = MagicMock()
    mock_db.zapier_leads_logs.find_one = AsyncMock(return_value=None)
    mock_db.zapier_leads_logs.update_one = AsyncMock()
    monkeypatch.setattr(zls, "db", mock_db)
    ingest = AsyncMock()
    monkeypatch.setattr(zls, "ingest_lead", ingest)

    result = await zls.process_zapier_lead(
        {"Lead ID": "lg-empty", "Form ID": "4309061012643289", "First Name": "X"}
    )
    assert result["reason"] == "missing_email_and_phone"
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_already_processed(monkeypatch):
    mock_db = MagicMock()
    mock_db.zapier_leads_logs.find_one = AsyncMock(
        return_value={"leadgen_id": "lg1", "success": True, "lead_id": "L1"}
    )
    monkeypatch.setattr(zls, "db", mock_db)
    ingest = AsyncMock()
    monkeypatch.setattr(zls, "ingest_lead", ingest)

    result = await zls.process_zapier_lead(
        {"Lead ID": "lg1", "Form ID": "4309061012643289", "Email": "a@b.com"}
    )
    assert result["reason"] == "already_processed"
    assert result["lead_id"] == "L1"
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_happy_path_melange(monkeypatch):
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {"4309061012643289": "melange"})
    mock_db = MagicMock()
    mock_db.zapier_leads_logs.find_one = AsyncMock(return_value=None)
    mock_db.zapier_leads_logs.update_one = AsyncMock()
    monkeypatch.setattr(zls, "db", mock_db)
    monkeypatch.setattr(
        zls,
        "ingest_lead",
        AsyncMock(return_value=({"success": True, "lead_id": "L99", "deduped": False}, 201)),
    )

    result = await zls.process_zapier_lead(
        {
            "Lead ID": "lg-happy",
            "Form ID": "4309061012643289",
            "First Name": "Latha",
            "Last Name": "Ramalingam",
            "Email": "latharam1964@gmail.com",
            "Phone Number": "+919790942415",
        }
    )
    assert result["reason"] == "ingested"
    assert result["lead_id"] == "L99"
    assert result["project_id"] == "melange"
    zls.ingest_lead.assert_awaited_once()
    call_kwargs = zls.ingest_lead.await_args.kwargs
    assert call_kwargs["api_key"]["id"] == "zapier-meta:melange"
    assert call_kwargs["body"]["email"] == "latharam1964@gmail.com"
    assert call_kwargs["body"]["source"] == "Facebook Lead Form"
