"""Unit tests for Webflow enquiry webhook helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.services import webflow_leads_service as wls


def test_verify_webhook_secret(monkeypatch):
    monkeypatch.setattr(wls, "WEBFLOW_WEBHOOK_SECRET", "wf-secret")
    assert wls.verify_webhook_secret(token="wf-secret") is True
    assert wls.verify_webhook_secret(header_secret="wf-secret") is True
    assert wls.verify_webhook_secret(token="wrong") is False
    assert wls.verify_webhook_secret(token=None, header_secret=None) is False


def test_verify_webhook_secret_empty_env(monkeypatch):
    monkeypatch.setattr(wls, "WEBFLOW_WEBHOOK_SECRET", "")
    assert wls.verify_webhook_secret(token="anything") is False


def test_project_from_form_name_all_five():
    assert wls.project_from_form_name("Melange Enquiry Form")["id"] == "melange"
    assert wls.project_from_form_name("Mira Enquiry Form")["id"] == "mira"
    assert wls.project_from_form_name("Reserve 16 Enquiry Form")["id"] == "reserve-16"
    assert wls.project_from_form_name("Vivriti Enquiry Form")["id"] == "vivriti"
    assert wls.project_from_form_name("Krsna Enquiry Form")["id"] == "krsna"
    assert wls.project_from_form_name("Unknown Form") is None


def test_project_from_project_name_melange_accent():
    assert wls.project_from_project_name_field("Melange")["id"] == "melange"
    assert wls.project_from_project_name_field("Mélange")["id"] == "melange"
    assert wls.project_from_project_name_field("Reserve 16")["id"] == "reserve-16"


def test_map_webflow_data_client_field_names():
    project = {"id": "melange", "name": "Mélange"}
    body = wls.map_webflow_data_to_intake(
        {
            "Project-Name": "Melange",
            "First-Name": "Priya",
            "Last-Name": "Sharma",
            "phone": "+91 98765 43210",
            "Cust-EMail": "priya@example.com",
            "Message": "Interested in 2BHK",
        },
        project=project,
        submission_id="sub1",
        form_id="form1",
        site_id="site1",
        form_name="Melange Enquiry Form",
    )
    assert body["first_name"] == "Priya"
    assert body["last_name"] == "Sharma"
    assert body["phone"] == "+91 98765 43210"
    assert body["email"] == "priya@example.com"
    assert body["consent"] is True
    assert body["source"] == "Mélange Website"
    assert body["meta"]["message"] == "Interested in 2BHK"
    assert body["meta"]["project_name"] == "Melange"
    assert body["meta"]["webflow_submission_id"] == "sub1"
    assert body["meta"]["webflow_form_name"] == "Melange Enquiry Form"


def test_map_webflow_data_label_variants():
    project = {"id": "mira", "name": "Mira"}
    body = wls.map_webflow_data_to_intake(
        {
            "First Name": "Asha",
            "Email": "asha@example.com",
            "Phone Number": "9999999999",
        },
        project=project,
        submission_id="s2",
    )
    assert body["first_name"] == "Asha"
    assert body["email"] == "asha@example.com"
    assert body["phone"] == "9999999999"
    assert body["source"] == "Mira Website"


@pytest.mark.asyncio
async def test_process_unmapped_form_skips_ingest(monkeypatch):
    mock_db = MagicMock()
    mock_db.webflow_leads_logs.find_one = AsyncMock(return_value=None)
    mock_db.webflow_leads_logs.update_one = AsyncMock()
    monkeypatch.setattr(wls, "db", mock_db)
    ingest = AsyncMock()
    monkeypatch.setattr(wls, "ingest_lead", ingest)

    result = await wls.process_form_submission(
        {
            "triggerType": "form_submission",
            "payload": {
                "name": "Unknown Enquiry Form",
                "id": "sub-x",
                "data": {"First-Name": "X", "phone": "1"},
            },
        }
    )
    assert result["reason"] == "unmapped_form"
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_already_processed(monkeypatch):
    mock_db = MagicMock()
    mock_db.webflow_leads_logs.find_one = AsyncMock(
        return_value={"submission_id": "sub1", "success": True, "lead_id": "L1"}
    )
    monkeypatch.setattr(wls, "db", mock_db)
    ingest = AsyncMock()
    monkeypatch.setattr(wls, "ingest_lead", ingest)

    result = await wls.process_form_submission(
        {
            "triggerType": "form_submission",
            "payload": {
                "name": "Mira Enquiry Form",
                "id": "sub1",
                "data": {"First-Name": "A", "Cust-EMail": "a@b.com"},
            },
        }
    )
    assert result["reason"] == "already_processed"
    assert result["lead_id"] == "L1"
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_happy_path_melange(monkeypatch):
    mock_db = MagicMock()
    mock_db.webflow_leads_logs.find_one = AsyncMock(return_value=None)
    mock_db.webflow_leads_logs.update_one = AsyncMock()
    monkeypatch.setattr(wls, "db", mock_db)
    monkeypatch.setattr(
        wls,
        "ingest_lead",
        AsyncMock(return_value=({"success": True, "lead_id": "L99", "deduped": False}, 201)),
    )

    result = await wls.process_form_submission(
        {
            "triggerType": "form_submission",
            "payload": {
                "name": "Melange Enquiry Form",
                "id": "sub-happy",
                "formId": "f1",
                "siteId": "s1",
                "data": {
                    "Project-Name": "Melange",
                    "First-Name": "Priya",
                    "Last-Name": "Sharma",
                    "phone": "9876543210",
                    "Cust-EMail": "priya@example.com",
                    "Message": "Call me",
                },
            },
        }
    )
    assert result["reason"] == "ingested"
    assert result["lead_id"] == "L99"
    assert result["project_id"] == "melange"
    wls.ingest_lead.assert_awaited_once()
    call_kwargs = wls.ingest_lead.await_args.kwargs
    assert call_kwargs["api_key"]["id"] == "webflow:melange"
    assert call_kwargs["body"]["email"] == "priya@example.com"
    assert call_kwargs["body"]["meta"]["message"] == "Call me"


@pytest.mark.asyncio
async def test_process_fallback_project_name_field(monkeypatch):
    mock_db = MagicMock()
    mock_db.webflow_leads_logs.find_one = AsyncMock(return_value=None)
    mock_db.webflow_leads_logs.update_one = AsyncMock()
    monkeypatch.setattr(wls, "db", mock_db)
    monkeypatch.setattr(
        wls,
        "ingest_lead",
        AsyncMock(return_value=({"success": True, "lead_id": "L2", "deduped": False}, 201)),
    )

    result = await wls.process_form_submission(
        {
            "triggerType": "form_submission",
            "payload": {
                "name": "Some Misc Form",
                "id": "sub-fb",
                "data": {
                    "Project-Name": "Krsna",
                    "First-Name": "Dev",
                    "phone": "9000000000",
                },
            },
        }
    )
    assert result["reason"] == "ingested"
    assert result["project_id"] == "krsna"
