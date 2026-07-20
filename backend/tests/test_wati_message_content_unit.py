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


def test_pick_primary_prefers_wamid():
    from crm.services.whatsapp_service import _pick_primary_and_local_wati_ids

    primary, local = _pick_primary_and_local_wati_ids(
        {"wati_message_id": "6a5e23bb7c133f561da48287"},
        {"wati_message_id": "wamid.HBgMOTE5ABC"},
    )
    assert primary == "wamid.HBgMOTE5ABC"
    assert local == "6a5e23bb7c133f561da48287"


def test_dedupe_history_collapses_webhook_and_sync_twins():
    from crm.services.whatsapp_service import _dedupe_history_messages

    messages = [
        {
            "wati_message_id": "6a5e23bb7c133f561da48287",
            "direction": "inbound",
            "content": "Thanks",
            "created_at": "2026-07-20T13:33:47.752000+00:00",
            "status": "sent",
        },
        {
            "wati_message_id": "wamid.HBgMOTE5ABC",
            "direction": "inbound",
            "content": "Thanks",
            "created_at": "2026-07-20T13:33:47.752078+00:00",
            "status": "received",
            "sender_name": "Rajendra",
        },
    ]
    out = _dedupe_history_messages(messages)
    assert len(out) == 1
    assert out[0]["wati_message_id"].startswith("wamid.")
    assert out[0]["sender_name"] == "Rajendra"


def test_dedupe_keeps_distinct_same_text_messages():
    from crm.services.whatsapp_service import _dedupe_history_messages

    messages = [
        {
            "wati_message_id": "6a5e25afef5b53b99936d568",
            "wati_local_id": "6a5e25afef5b53b99936d568",
            "direction": "outbound",
            "content": "CRM test hey ignore",
            "created_at": "2026-07-20T13:42:07.641Z",
        },
        {
            "wati_message_id": "6a5e25b1360e2ff5d69525fa",
            "wati_local_id": "6a5e25b1360e2ff5d69525fa",
            "direction": "outbound",
            "content": "CRM test hey ignore",
            "created_at": "2026-07-20T13:42:09.316Z",
        },
        {
            "wati_message_id": "6a5e25b2360e2ff5d6952614",
            "wati_local_id": "6a5e25b2360e2ff5d6952614",
            "direction": "outbound",
            "content": "CRM test hey ignore",
            "created_at": "2026-07-20T13:42:10.444Z",
        },
    ]
    out = _dedupe_history_messages(messages)
    assert len(out) == 3


def test_ids_suggest_same_message_rules():
    from crm.services.whatsapp_service import _ids_suggest_same_message

    assert _ids_suggest_same_message(
        {"wati_message_id": "wamid.ABC"},
        {"wati_message_id": "6alocal"},
    )
    assert not _ids_suggest_same_message(
        {"wati_message_id": "6aaa", "wati_local_id": "6aaa"},
        {"wati_message_id": "6bbb", "wati_local_id": "6bbb"},
    )


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


def test_wati_session_send_ok_and_id():
    from crm.services.whatsapp_service import (
        _wati_session_send_ok,
        _wati_session_send_message_id,
    )

    result = {
        "ok": True,
        "result": "success",
        "message": {
            "whatsappMessageId": "wamid.ABC",
            "localMessageId": "local-1",
            "statusString": "SENT",
        },
    }
    assert _wati_session_send_ok(200, result) is True
    assert _wati_session_send_message_id(result) == "wamid.ABC"
    assert _wati_session_send_ok(200, {"result": False, "info": "message text can not be empty"}) is False
    assert _wati_session_send_ok(404, {}) is False


def test_infer_media_type_and_proxy_path():
    from crm.services.whatsapp_service import (
        _infer_media_type_from_path,
        _is_wati_media_path,
        _crm_media_proxy_path,
        _media_display_name,
        _normalize_wati_message,
        _decorate_history_messages,
    )

    assert _is_wati_media_path("data/images/abc.jpg")
    assert _infer_media_type_from_path("data/images/abc.jpg") == "image"
    assert _infer_media_type_from_path("data/audio/x.ogg") == "audio"
    assert _infer_media_type_from_path("data/document/x.pdf") == "document"
    assert _media_display_name("data/images/18b8ac2b.jpg") == "18b8ac2b.jpg"
    assert "fileName=" in _crm_media_proxy_path("data/images/abc.jpg")

    doc = _normalize_wati_message(
        {
            "id": "img1",
            "owner": False,
            "type": "image",
            "text": "",
            "data": "data/images/18b8ac2b-f06f-4836-bfc8-b2ae1c996253.jpg",
            "created": "2026-07-20T15:12:00Z",
        },
        phone="919116914178",
    )
    assert doc["message_type"] == "image"
    assert doc["media_url"].startswith("/whatsapp/media?fileName=")

    decorated = _decorate_history_messages(
        [
            {
                "direction": "inbound",
                "message_type": "document",
                "content": "Image: data/images/x.jpg",
                "media_filename": "data/images/x.jpg",
                "created_at": "2026-07-20T15:12:00Z",
            }
        ]
    )
    assert decorated[0]["message_type"] == "image"
    assert decorated[0]["media_url"].startswith("/whatsapp/media?fileName=")
