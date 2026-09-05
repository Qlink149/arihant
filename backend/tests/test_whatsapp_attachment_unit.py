"""Unit tests for WhatsApp agent attach-and-send (no real WATI / no file blobs)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.services import whatsapp_service as wa


def test_validate_attachment_accepts_pdf():
    assert wa._validate_attachment_upload("brochure.pdf", "application/pdf", 1024) is None


def test_validate_attachment_accepts_image_ext():
    assert wa._validate_attachment_upload("photo.jpg", "image/jpeg", 2048) is None
    assert wa._validate_attachment_upload("shot.PNG", "image/png", 100) is None


def test_validate_attachment_rejects_bad_ext():
    err = wa._validate_attachment_upload("virus.exe", "application/octet-stream", 100)
    assert err and "Unsupported" in err


def test_validate_attachment_rejects_oversize():
    err = wa._validate_attachment_upload(
        "big.pdf", "application/pdf", wa._ATTACHMENT_MAX_BYTES + 1
    )
    assert err and "too large" in err.lower()


def test_validate_attachment_rejects_empty():
    err = wa._validate_attachment_upload("empty.pdf", "application/pdf", 0)
    assert err and "Empty" in err


def test_attachment_message_type():
    assert wa._attachment_message_type("a.pdf", "application/pdf") == "document"
    assert wa._attachment_message_type("a.docx", "application/octet-stream") == "document"
    assert wa._attachment_message_type("a.jpg", "image/jpeg") == "image"


@pytest.mark.asyncio
async def test_send_attachment_session_closed(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")
    monkeypatch.setattr(wa, "WATI_API_TOKEN", "test-token")

    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(
        return_value={"id": "L1", "phone": "919999000001", "first_name": "Test"}
    )
    monkeypatch.setattr(wa, "db", mock_db)
    monkeypatch.setattr(wa, "_is_session_open", AsyncMock(return_value=False))

    upload = MagicMock()
    upload.filename = "doc.pdf"
    upload.content_type = "application/pdf"
    upload.read = AsyncMock(return_value=b"%PDF-1.4 fake")

    result = await wa.send_attachment_to_lead(
        "L1", upload, {"id": "u1", "full_name": "Agent"}, caption=None
    )
    assert result["success"] is False
    assert "session" in result["error"].lower()


@pytest.mark.asyncio
async def test_send_attachment_rejects_bad_type_before_wati(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")
    monkeypatch.setattr(wa, "WATI_API_TOKEN", "test-token")

    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(
        return_value={"id": "L1", "phone": "919999000001", "first_name": "Test"}
    )
    monkeypatch.setattr(wa, "db", mock_db)
    send_file = AsyncMock()
    monkeypatch.setattr(wa, "_wati_send_session_file", send_file)
    monkeypatch.setattr(wa, "_is_session_open", AsyncMock(return_value=True))

    upload = MagicMock()
    upload.filename = "bad.exe"
    upload.content_type = "application/octet-stream"
    upload.read = AsyncMock(return_value=b"MZ")

    result = await wa.send_attachment_to_lead(
        "L1", upload, {"id": "u1", "full_name": "Agent"}
    )
    assert result["success"] is False
    assert "Unsupported" in result["error"]
    send_file.assert_not_called()


@pytest.mark.asyncio
async def test_send_attachment_success_metadata_only(monkeypatch):
    monkeypatch.setattr(wa, "WHATSAPP_PROVIDER", "wati")
    monkeypatch.setattr(wa, "WATI_API_TOKEN", "test-token")

    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(
        return_value={"id": "L1", "phone": "919999000001", "first_name": "Test"}
    )
    mock_db.leads.update_one = AsyncMock()
    monkeypatch.setattr(wa, "db", mock_db)
    monkeypatch.setattr(wa, "_is_session_open", AsyncMock(return_value=True))
    monkeypatch.setattr(wa, "_wati_ensure_contact", AsyncMock())

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "ok": True,
        "message": {"whatsappMessageId": "wamid-attach-1"},
    }
    monkeypatch.setattr(
        wa, "_wati_send_session_file", AsyncMock(return_value=fake_resp)
    )

    upserted = {}

    async def _capture_upsert(doc):
        upserted.update(doc)

    monkeypatch.setattr(wa, "_upsert_whatsapp_message", _capture_upsert)

    upload = MagicMock()
    upload.filename = "floorplan.pdf"
    upload.content_type = "application/pdf"
    upload.read = AsyncMock(return_value=b"%PDF-1.4 content")

    result = await wa.send_attachment_to_lead(
        "L1",
        upload,
        {"id": "u1", "full_name": "Agent"},
        caption="Floor plan",
    )
    assert result["success"] is True
    assert result["media_filename"] == "floorplan.pdf"
    assert result["message_type"] == "document"
    # Metadata only — never store file bytes or fake media blob fields
    assert "media_url" not in upserted
    assert upserted.get("media_filename") == "floorplan.pdf"
    assert upserted.get("content") == "Floor plan"
    assert b"%PDF" not in str(upserted).encode()
    assert "Binary" not in str(type(upserted.get("content")))
