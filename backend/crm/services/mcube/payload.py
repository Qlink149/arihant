"""Extract and normalize MCUBE inbound payloads from varied transports."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import Request

from crm.constants.mcube import REDACT_PAYLOAD_KEYS


def lowercase_keys(payload: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (payload or {}).items():
        key = str(k).strip().lower()
        out[key] = v
    return out


def redact_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload or {})
    for k in list(out.keys()):
        if str(k).strip().lower() in REDACT_PAYLOAD_KEYS:
            out[k] = "[REDACTED]"
    return out


def _maybe_parse_data_wrapper(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Live MCUBE connector posts form field data=<json string>."""
    if not isinstance(payload, dict):
        return {}
    if "data" in payload and isinstance(payload["data"], str):
        raw = payload["data"].strip()
        if raw.startswith("{") or raw.startswith("["):
            try:
                inner = json.loads(raw)
                if isinstance(inner, dict):
                    return inner
            except json.JSONDecodeError:
                pass
    # Also handle nested data already parsed as dict
    if "data" in payload and isinstance(payload["data"], dict) and len(payload) <= 3:
        return payload["data"]
    return payload


async def extract_mcube_payload(request: Request) -> Dict[str, Any]:
    """
    Accept GET query, JSON body, form-urlencoded, multipart, or text/plain JSON.
    Always returns a flat dict with lowercase keys (empty dict on failure).
    """
    payload: Dict[str, Any] = {}
    try:
        content_type = (request.headers.get("content-type") or "").lower()
        if request.method.upper() == "GET":
            payload = dict(request.query_params)
        elif "application/json" in content_type:
            body = await request.json()
            payload = body if isinstance(body, dict) else {}
        elif (
            "application/x-www-form-urlencoded" in content_type
            or "multipart/form-data" in content_type
        ):
            form = await request.form()
            payload = {k: form.get(k) for k in form.keys()}
        else:
            raw = await request.body()
            text = (raw or b"").decode("utf-8", errors="replace").strip()
            if text.startswith("{"):
                try:
                    body = json.loads(text)
                    payload = body if isinstance(body, dict) else {}
                except json.JSONDecodeError:
                    payload = {}
            elif text:
                # Try query-string style body
                from urllib.parse import parse_qs

                parsed = parse_qs(text, keep_blank_values=True)
                payload = {k: (v[0] if isinstance(v, list) and v else "") for k, v in parsed.items()}
            # Merge query params as weak fallback when body empty
            if not payload and request.query_params:
                payload = dict(request.query_params)
    except Exception:
        payload = {}

    payload = _maybe_parse_data_wrapper(payload if isinstance(payload, dict) else {})
    # Merge query token-only params shouldn't overwrite body, but include missing keys from query
    if request.query_params:
        q = dict(request.query_params)
        for k, v in q.items():
            if k.lower() == "token":
                continue
            if k not in payload and str(k).lower() not in {str(x).lower() for x in payload.keys()}:
                payload[k] = v
    return lowercase_keys(payload)


def verify_mcube_webhook_secret(
    token: Optional[str] = None,
    header_secret: Optional[str] = None,
) -> bool:
    import hmac

    from crm.core.state import MCUBE_WEBHOOK_SECRET

    expected = (MCUBE_WEBHOOK_SECRET or "").strip()
    if not expected:
        return False
    candidates = []
    if token is not None:
        candidates.append(str(token).strip())
    if header_secret is not None:
        candidates.append(str(header_secret).strip())
    for candidate in candidates:
        if candidate and hmac.compare_digest(expected, candidate):
            return True
    return False
