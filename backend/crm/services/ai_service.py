"""
LLM chat integration (Groq by default; optional xAI): rotating API keys, retries, PII masking.

Environment (at least one key required for live AI):
  GROQ_API_KEY — Groq free tier (recommended)
  GROQ_MODEL — default llama-3.3-70b-versatile
  GROK_API_KEY_1, GROK_API_KEY_2, GROK_API_KEY_3 — legacy aliases (treated as Groq keys)
  GROK_MODEL — legacy model env (used when GROQ_MODEL unset)
  LLM_PROVIDER — groq (default) or xai
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
XAI_CHAT_URL = "https://api.x.ai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_XAI_MODEL = "grok-2-latest"

# --- PII masking (best-effort before sending text to LLM) ---

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}[\s.-]?\d{2,6}\b"
)
_PIN_RE = re.compile(r"\b\d{6}\b")
_LONG_DIGITS_RE = re.compile(r"\b\d{10,}\b")


def mask_pii_text(text: str) -> str:
    if not text:
        return ""
    s = str(text)
    s = _EMAIL_RE.sub("[EMAIL_REDACTED]", s)
    s = _LONG_DIGITS_RE.sub("[PHONE_REDACTED]", s)
    s = _PHONE_RE.sub("[PHONE_REDACTED]", s)
    s = _PIN_RE.sub("[PIN_REDACTED]", s)
    # Heuristic: lines that look like street addresses
    lines_out = []
    for line in s.splitlines():
        low = line.lower()
        if re.search(r"\b\d{1,4}\s+[a-z]+\s+(street|st\.|road|rd\.|avenue|ave|lane|ln|nagar|layout)\b", low):
            lines_out.append("[ADDRESS_REDACTED]")
        else:
            lines_out.append(line)
    return "\n".join(lines_out)


# --- API key rotation ---

def load_llm_api_keys() -> List[str]:
    seen: set[str] = set()
    keys: List[str] = []
    for env_name in (
        "GROQ_API_KEY",
        "GROQ_API_KEY_2",
        "GROQ_API_KEY_3",
        "GROK_API_KEY_1",
        "GROK_API_KEY_2",
        "GROK_API_KEY_3",
    ):
        k = os.environ.get(env_name, "").strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def load_grok_api_keys() -> List[str]:
    """Backward-compatible alias for load_llm_api_keys."""
    return load_llm_api_keys()


def _resolve_llm_config() -> Tuple[str, str, List[str]]:
    keys = load_llm_api_keys()
    provider = os.environ.get("LLM_PROVIDER", "groq").strip().lower()
    if provider == "xai":
        model = os.environ.get("GROK_MODEL", DEFAULT_XAI_MODEL)
        return XAI_CHAT_URL, model, keys
    model = (
        os.environ.get("GROQ_MODEL")
        or os.environ.get("GROK_MODEL")
        or DEFAULT_GROQ_MODEL
    )
    return GROQ_CHAT_URL, model, keys


def grok_keys_configured() -> bool:
    return bool(load_llm_api_keys())


_current_key_index = 0


def _next_key_index() -> None:
    global _current_key_index
    keys = load_llm_api_keys()
    if not keys:
        return
    _current_key_index = (_current_key_index + 1) % len(keys)


def _post_chat_sync(api_key: str, body: Dict[str, Any], chat_url: str) -> Tuple[int, str]:
    r = requests.post(
        chat_url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=120,
    )
    return r.status_code, r.text


def _should_rotate_on_status(status: int) -> bool:
    return status in (401, 403, 429) or status >= 500


def _extract_json_object(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.I)
    if m:
        raw = m.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise


class GroundedProfile(BaseModel):
    budget: str = "Not specified"
    configuration: str = "Not specified"
    possession_requirement: str = "Not specified"
    intent: str = "Not specified"

    @field_validator("budget", "configuration", "possession_requirement", "intent", mode="before")
    @classmethod
    def empty_to_not_specified(cls, v: Any) -> str:
        if v is None or (isinstance(v, str) and not v.strip()):
            return "Not specified"
        return str(v).strip()


class StrategicMove(BaseModel):
    title: str = ""
    rationale: str = ""
    priority: str = "medium"


class LeadGrokPayload(BaseModel):
    persona_summary: str = ""
    strategic_next_moves: List[StrategicMove] = Field(default_factory=list)
    grounded_profile: GroundedProfile = Field(default_factory=GroundedProfile)


def _repair_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure required keys exist after loose model JSON."""
    gp = data.get("grounded_profile") or {}
    if not isinstance(gp, dict):
        gp = {}
    for k in ("budget", "configuration", "possession_requirement", "intent"):
        v = gp.get(k)
        if v is None or (isinstance(v, str) and not str(v).strip()):
            gp[k] = "Not specified"
        else:
            gp[k] = str(v).strip()
    data["grounded_profile"] = gp
    moves = data.get("strategic_next_moves")
    if not isinstance(moves, list):
        data["strategic_next_moves"] = []
    else:
        cleaned = []
        for m in moves[:8]:
            if isinstance(m, dict):
                cleaned.append(
                    {
                        "title": str(m.get("title") or "")[:200],
                        "rationale": str(m.get("rationale") or "")[:2000],
                        "priority": str(m.get("priority") or "medium")[:20],
                    }
                )
        data["strategic_next_moves"] = cleaned
    if not isinstance(data.get("persona_summary"), str):
        data["persona_summary"] = str(data.get("persona_summary") or "")[:8000]
    return data


GROUNDING_SYSTEM = """You are a precise CRM analyst for a real-estate sales team.
You MUST respond with a single JSON object only (no markdown fences), matching this schema:
{
  "persona_summary": string,
  "strategic_next_moves": [ { "title": string, "rationale": string, "priority": "high"|"medium"|"low" } ],
  "grounded_profile": {
    "budget": string,
    "configuration": string,
    "possession_requirement": string,
    "intent": string
  }
}

Rules:
1) persona_summary: Summarize the buyer from the interaction transcript and safe CRM hints. Do not invent facts not supported by the transcript or hints.
2) strategic_next_moves: 2–4 concrete next steps for the sales rep based on the transcript. Be specific to stated objections, timing, or interests.
3) grounded_profile: For budget, configuration (e.g. 3BHK), possession_requirement, and intent — extract ONLY if the interaction transcript EXPLICITLY states them.
   If not explicit, use exactly the string "Not specified" for that field. No guessing from project names, stereotypes, or missing data.
4) Never output phone numbers, full addresses, or email addresses in any field."""


async def grok_chat_json(system: str, user: str, *, temperature: float = 0.0) -> Dict[str, Any]:
    chat_url, model, keys = _resolve_llm_config()
    if not keys:
        raise RuntimeError(
            "No GROQ_API_KEY or GROK_API_KEY_* environment variables configured"
        )

    global _current_key_index
    body = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }

    last_err: Optional[Exception] = None
    for attempt in range(len(keys)):
        api_key = keys[_current_key_index % len(keys)]
        try:
            status, text = await asyncio.to_thread(
                _post_chat_sync, api_key, body, chat_url
            )
        except requests.RequestException as e:
            last_err = e
            logger.warning("LLM request network error: %s", e)
            _next_key_index()
            continue

        if _should_rotate_on_status(status):
            logger.warning("LLM HTTP %s, rotating key index", status)
            _next_key_index()
            last_err = RuntimeError(f"LLM HTTP {status}: {text[:500]}")
            continue

        if status != 200:
            raise RuntimeError(f"LLM HTTP {status}: {text[:800]}")

        try:
            outer = json.loads(text)
            content = outer["choices"][0]["message"]["content"]
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Unexpected LLM response shape: {text[:500]}") from e

        try:
            return _extract_json_object(content)
        except json.JSONDecodeError as e:
            repair_user = (
                "The following was not valid JSON. Return ONLY corrected minified JSON, same schema as before.\n\n"
                + content[:12000]
            )
            repair_body = {
                "model": model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": "Return only valid JSON. No markdown."},
                    {"role": "user", "content": repair_user},
                ],
            }
            try:
                status2, text2 = await asyncio.to_thread(
                    _post_chat_sync, api_key, repair_body, chat_url
                )
                if status2 == 200:
                    outer2 = json.loads(text2)
                    content2 = outer2["choices"][0]["message"]["content"]
                    return _extract_json_object(content2)
            except Exception as e2:
                last_err = e2
            raise RuntimeError("LLM returned non-JSON content") from e

    if last_err:
        raise last_err
    raise RuntimeError("LLM request failed after key rotation")


async def generate_lead_insights(*, transcript: str, crm_hints: str) -> LeadGrokPayload:
    user_msg = (
        "## Interaction transcript (PII may be masked)\n"
        + transcript
        + "\n\n## CRM hints (for persona / strategy only; do NOT use for grounded_profile unless same fact appears in transcript)\n"
        + crm_hints
    )
    raw = await grok_chat_json(GROUNDING_SYSTEM, user_msg, temperature=0.0)
    raw = _repair_payload(raw)
    return LeadGrokPayload.model_validate(raw)
