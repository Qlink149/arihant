"""Unit tests for WATI chat content extraction / humanization (no network)."""

from crm.services.whatsapp_service import (
    _extract_wati_content,
    _humanize_stored_content,
    _message_sort_ts,
    _outbound_template_content,
    _looks_like_media_template_error,
    _normalize_wati_message,
    _pdf_from_template_params,
    _decorate_history_messages,
)


def test_extract_prefers_plain_text():
    assert _extract_wati_content({"text": "Pricing", "type": "button"}) == "Pricing"


def test_extract_button_reply_when_text_empty():
    msg = {
        "text": "",
        "type": "button",
        "buttonReply": {"text": "Get Brochure"},
    }
    assert _extract_wati_content(msg) == "Get Brochure"


def test_extract_interactive_button_reply():
    msg = {
        "type": "interactive",
        "interactiveButtonReply": {"title": "Site Visit"},
    }
    assert _extract_wati_content(msg) == "Site Visit"


def test_extract_document_filename():
    msg = {
        "type": "document",
        "text": "",
        "data": {"fileName": "Vivriti Brochure.pdf"},
    }
    assert _extract_wati_content(msg) == "PDF document: Vivriti Brochure.pdf"


def test_extract_never_shows_numeric_type_brackets():
    assert _extract_wati_content({"type": 0}) == "WhatsApp message"
    assert _extract_wati_content({"type": 1, "text": None}) == "WhatsApp message"
    assert _extract_wati_content({"type": "message"}) == "Message"


def test_extract_broadcast_final_text():
    msg = {
        "eventType": "broadcastMessage",
        "eventDescription": 'Broadcast message with using "arihant_pricing_v1" template was received 20|07|2026',
        "finalText": "Hi rajendra,\n\nPricing starts from ₹13,000/sq.ft.",
        "statusString": "DELIVERED",
    }
    assert "Pricing starts from" in _extract_wati_content(msg)


def test_extract_template_name_friendly():
    msg = {"type": "template", "templateName": "arihant_brochure_v1", "text": ""}
    assert _extract_wati_content(msg) == "Project brochure"


def test_normalize_broadcast_message():
    doc = _normalize_wati_message(
        {
            "id": "bcast1",
            "eventType": "broadcastMessage",
            "eventDescription": 'Broadcast message with using "arihant_new_lead_ack_v1" template was received 16|07|2026',
            "finalText": "Hi rajendra,\n\nThank you for your interest.",
            "statusString": "DELIVERED",
            "created": "2026-07-16T08:39:24.591Z",
        },
        phone="919116914178",
    )
    assert doc["direction"] == "outbound"
    assert doc["message_type"] == "template"
    assert doc["template_name"] == "arihant_new_lead_ack_v1"
    assert "Thank you for your interest" in doc["content"]
    assert doc["wati_message_id"] == "bcast1"


def test_is_wati_system_event_ticket():
    from crm.services.whatsapp_service import _is_wati_system_event

    assert _is_wati_system_event({"eventType": "ticket", "type": 0}) is True
    assert _is_wati_system_event({"eventType": "broadcastMessage", "finalText": "Hi"}) is False
    assert _is_wati_system_event({"eventType": "message", "text": "Pricing", "owner": False}) is False


def test_humanize_legacy_template_prefix():
    assert _humanize_stored_content("Template: arihant_new_lead_ack_v1") == "New lead acknowledgment"
    assert _humanize_stored_content("Template: arihant_brochure_v1") == "Project brochure"


def test_humanize_legacy_brackets():
    assert _humanize_stored_content("[0]") == "WhatsApp message"
    assert _humanize_stored_content("[1]") == "WhatsApp message"
    assert _humanize_stored_content("[message]") == "WhatsApp message"
    assert _humanize_stored_content("[document message]") == "PDF document"


def test_humanize_leaves_real_text():
    assert _humanize_stored_content("Hi rajendra, pricing starts from") == "Hi rajendra, pricing starts from"


def test_outbound_template_content_with_pdf():
    content = _outbound_template_content(
        "arihant_brochure_v1",
        [{"name": "pdfLink", "value": "https://api.example.com/static/Vivriti%20Brochure.pdf"}],
    )
    assert content == "Project brochure: Vivriti Brochure.pdf"


def test_message_sort_ts_orders_mixed_formats():
    older = {"created_at": "2025-05-27T10:00:00.1234567Z"}
    newer = {"created_at": "2025-05-27T11:00:00Z"}
    assert _message_sort_ts(newer) > _message_sort_ts(older)


def test_looks_like_media_template_error():
    assert _looks_like_media_template_error({"status_code": 400, "error": "bad request"})
    assert _looks_like_media_template_error({"error": "Invalid media header parameter"})
    assert not _looks_like_media_template_error({"status_code": 403, "error": "forbidden"})


def test_normalize_button_reply_structured_fields():
    doc = _normalize_wati_message(
        {
            "whatsappMessageId": "wamid.abc",
            "owner": False,
            "waId": "919116914178",
            "type": "button",
            "text": "",
            "buttonReply": {"text": "Get Brochure"},
            "created": "2025-11-27T10:14:16.6268572Z",
        },
        phone="919116914178",
    )
    assert doc["content"] == "Get Brochure"
    assert doc["reply_label"] == "Get Brochure"
    assert doc["direction"] == "inbound"
    assert doc["wati_message_id"] == "wamid.abc"
    assert doc["created_at_dt"] is not None


def test_normalize_document_media_fields():
    doc = _normalize_wati_message(
        {
            "whatsappMessageId": "wamid.doc1",
            "owner": True,
            "type": "document",
            "data": {"fileName": "Vivriti Brochure.pdf"},
            "sourceUrl": "https://cdn.example.com/Vivriti%20Brochure.pdf",
            "created": "2025-11-27T10:14:16Z",
        },
        phone="919116914178",
    )
    assert doc["media_filename"] == "Vivriti Brochure.pdf"
    assert doc["media_url"] == "https://cdn.example.com/Vivriti%20Brochure.pdf"
    assert doc["message_type"] == "document"
    assert "Vivriti" in doc["content"]


def test_pdf_from_template_params():
    url, name = _pdf_from_template_params(
        [{"name": "pdfLink", "value": "https://api.example.com/static/Vivriti%20Brochure.pdf"}]
    )
    assert url.endswith("Vivriti%20Brochure.pdf")
    assert name == "Vivriti Brochure.pdf"


def test_friendly_wati_404():
    from crm.services.whatsapp_service import _friendly_wati_send_error

    msg = _friendly_wati_send_error(404, {"message": "Not Found"}, kind="message")
    assert "open WhatsApp chat" in msg
    assert "404" not in msg
    assert "WATI" not in msg.upper() or "WhatsApp" in msg


def test_friendly_wati_keeps_clear_text():
    from crm.services.whatsapp_service import _friendly_wati_send_error

    msg = _friendly_wati_send_error(400, {"error": "Invalid template parameter"}, kind="template")
    assert "Invalid template parameter" in msg
