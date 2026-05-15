"""Unit tests for Grok AI service helpers (no live API calls)."""

import asyncio
import json

import pytest

from crm.services import ai_service


def test_mask_pii_masks_email_and_phone_like_sequences():
    raw = "Call me at 9876543210 or email john.doe@example.com for plot 12 on MG Road Chennai"
    out = ai_service.mask_pii_text(raw)
    assert "john.doe@example.com" not in out
    assert "[EMAIL_REDACTED]" in out
    assert "9876543210" not in out or "[PHONE_REDACTED]" in out


def test_mask_pii_address_heuristic():
    raw = "Meet at 12 Gandhi Street for site inspection"
    out = ai_service.mask_pii_text(raw)
    assert "[ADDRESS_REDACTED]" in out


def test_repair_payload_fills_not_specified():
    data = {"persona_summary": "x", "strategic_next_moves": [], "grounded_profile": {"budget": ""}}
    fixed = ai_service._repair_payload(data)
    assert fixed["grounded_profile"]["budget"] == "Not specified"


def test_extract_json_object_from_fence():
    raw = 'Here is JSON:\n```json\n{"a": 1}\n```'
    assert ai_service._extract_json_object(raw) == {"a": 1}


def test_load_grok_api_keys_empty_when_unset(monkeypatch):
    monkeypatch.delenv("GROK_API_KEY_1", raising=False)
    monkeypatch.delenv("GROK_API_KEY_2", raising=False)
    monkeypatch.delenv("GROK_API_KEY_3", raising=False)
    assert ai_service.load_grok_api_keys() == []


def test_grok_keys_configured(monkeypatch):
    monkeypatch.setenv("GROK_API_KEY_1", "test-key")
    assert ai_service.grok_keys_configured() is True


def test_grok_chat_json_raises_without_keys(monkeypatch):
    monkeypatch.delenv("GROK_API_KEY_1", raising=False)
    monkeypatch.delenv("GROK_API_KEY_2", raising=False)
    monkeypatch.delenv("GROK_API_KEY_3", raising=False)
    with pytest.raises(RuntimeError, match="No GROK_API_KEY"):
        asyncio.run(ai_service.grok_chat_json("sys", "user"))


def test_grok_chat_json_rotates_on_429(monkeypatch):
    monkeypatch.setenv("GROK_API_KEY_1", "k1")
    monkeypatch.setenv("GROK_API_KEY_2", "k2")
    calls = []

    def fake_post(api_key, body):
        calls.append(api_key)
        if api_key == "k1":
            return 429, "{}"
        return 200, json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"persona_summary":"p","strategic_next_moves":[],"grounded_profile":{"budget":"Not specified","configuration":"Not specified","possession_requirement":"Not specified","intent":"Not specified"}}'
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(ai_service, "_post_chat_sync", fake_post)
    ai_service._current_key_index = 0
    data = asyncio.run(ai_service.grok_chat_json("s", "u"))
    assert "persona_summary" in data
    assert len(calls) >= 2
