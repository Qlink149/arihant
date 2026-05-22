"""Unit tests for LLM AI service helpers (no live API calls)."""



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





def test_load_llm_api_keys_empty_when_unset(monkeypatch):

    for name in (

        "GROQ_API_KEY",

        "GROQ_API_KEY_2",

        "GROQ_API_KEY_3",

        "GROK_API_KEY_1",

        "GROK_API_KEY_2",

        "GROK_API_KEY_3",

    ):

        monkeypatch.delenv(name, raising=False)

    assert ai_service.load_llm_api_keys() == []





def _clear_all_llm_keys(monkeypatch):
    for name in (
        "GROQ_API_KEY",
        "GROQ_API_KEY_2",
        "GROQ_API_KEY_3",
        "GROK_API_KEY_1",
        "GROK_API_KEY_2",
        "GROK_API_KEY_3",
    ):
        monkeypatch.setenv(name, "")


def test_load_llm_api_keys_groq_primary(monkeypatch):
    _clear_all_llm_keys(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    assert ai_service.load_llm_api_keys() == ["gsk-test"]





def test_grok_keys_configured(monkeypatch):

    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    assert ai_service.grok_keys_configured() is True





def test_resolve_llm_config_defaults_to_groq(monkeypatch):
    _clear_all_llm_keys(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("GROK_MODEL", raising=False)
    url, model, keys = ai_service._resolve_llm_config()
    assert url == ai_service.GROQ_CHAT_URL
    assert model == ai_service.DEFAULT_GROQ_MODEL
    assert keys == ["k"]





def test_resolve_llm_config_respects_grok_model_env(monkeypatch):

    monkeypatch.setenv("GROQ_API_KEY", "k")

    monkeypatch.setenv("GROK_MODEL", "llama-3.3-70b-versatile")

    url, model, _ = ai_service._resolve_llm_config()

    assert url == ai_service.GROQ_CHAT_URL

    assert model == "llama-3.3-70b-versatile"





def test_grok_chat_json_raises_without_keys(monkeypatch):

    for name in (

        "GROQ_API_KEY",

        "GROQ_API_KEY_2",

        "GROQ_API_KEY_3",

        "GROK_API_KEY_1",

        "GROK_API_KEY_2",

        "GROK_API_KEY_3",

    ):

        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="No GROQ_API_KEY"):

        asyncio.run(ai_service.grok_chat_json("sys", "user"))





def test_grok_chat_json_rotates_on_429(monkeypatch):

    monkeypatch.setenv("GROQ_API_KEY", "k1")

    monkeypatch.setenv("GROQ_API_KEY_2", "k2")

    calls = []



    def fake_post(api_key, body, chat_url):

        calls.append((api_key, chat_url))

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

    assert all(url == ai_service.GROQ_CHAT_URL for _, url in calls)

