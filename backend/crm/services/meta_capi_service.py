"""Meta Conversions API (CAPI) — QualifiedLead events.

Public entry point: ``send_qualified_lead_event(lead)``.

No automatic CRM trigger is wired yet. Call this from the admin test endpoint
(``POST /api/internal/meta-capi/test``) or invoke it manually once the client
finalizes when a lead counts as qualified.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from crm.core.state import (
    META_ACCESS_TOKEN,
    META_API_VERSION,
    META_DATASET_ID,
    META_TEST_EVENT_CODE,
    db,
    iso_utc_now,
    logger,
    utc_now,
)

EVENT_NAME = "QualifiedLead"
RESPONSE_BODY_MAX_CHARS = 4000
RETRY_DELAY_SECONDS = 2.0
HTTP_TIMEOUT_SECONDS = 30.0


def hash_field(value: Any) -> Optional[str]:
    """Trim, lowercase, SHA-256 hex. Return None if empty/null."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_phone(value: Any) -> Optional[str]:
    """Digits only (keep country code), SHA-256 hex. Return None if empty."""
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    return hashlib.sha256(digits.encode("utf-8")).hexdigest()


def _lead_phone(lead: dict) -> Any:
    phone = lead.get("phone")
    if phone is not None and str(phone).strip():
        return phone
    return lead.get("work_phone")


def build_payload(lead: dict, *, event_time: Optional[int] = None) -> Dict[str, Any]:
    """Build Meta CAPI request body for a QualifiedLead event.

    Omits any ``user_data`` key whose hashed value is null/empty.
    Includes ``test_event_code`` at the top level when ``META_TEST_EVENT_CODE`` is set.
    """
    if event_time is None:
        event_time = int(time.time())

    lead_id = str(lead.get("id") or "").strip() or "unknown"
    event_id = f"arihant_{lead_id}_{event_time}"

    user_data: Dict[str, List[str]] = {}
    em = hash_field(lead.get("email"))
    ph = hash_phone(_lead_phone(lead))
    fn = hash_field(lead.get("first_name"))
    ln = hash_field(lead.get("last_name"))
    ct = hash_field(lead.get("location"))  # no city field; map city → location

    if em:
        user_data["em"] = [em]
    if ph:
        user_data["ph"] = [ph]
    if fn:
        user_data["fn"] = [fn]
    if ln:
        user_data["ln"] = [ln]
    if ct:
        user_data["ct"] = [ct]

    body: Dict[str, Any] = {
        "data": [
            {
                "event_name": EVENT_NAME,
                "event_time": event_time,
                "action_source": "system_generated",
                "event_id": event_id,
                "user_data": user_data,
            }
        ],
        "access_token": META_ACCESS_TOKEN,
    }
    if META_TEST_EVENT_CODE:
        body["test_event_code"] = META_TEST_EVENT_CODE
    return body


def _truncate_response_body(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        try:
            text = json.dumps(raw, default=str)
        except Exception:
            text = str(raw)
        if len(text) > RESPONSE_BODY_MAX_CHARS:
            return text[:RESPONSE_BODY_MAX_CHARS] + "…[truncated]"
        return raw
    text = str(raw)
    if len(text) > RESPONSE_BODY_MAX_CHARS:
        return text[:RESPONSE_BODY_MAX_CHARS] + "…[truncated]"
    return text


async def _write_log(
    *,
    lead_id: str,
    event_id: str,
    response_status: Optional[int],
    response_body: Any,
    success: bool,
    error_message: Optional[str],
    user_data_keys: Optional[List[str]] = None,
) -> None:
    doc: Dict[str, Any] = {
        "lead_id": lead_id,
        "event_id": event_id,
        "event_name": EVENT_NAME,
        "response_status": response_status,
        "response_body": _truncate_response_body(response_body),
        "success": success,
        "error_message": (error_message[:500] if error_message else None),
        "created_at": iso_utc_now(),
        "created_at_dt": utc_now(),
    }
    if user_data_keys is not None:
        doc["user_data_keys"] = user_data_keys
    try:
        await db.meta_capi_logs.insert_one(doc)
    except Exception as e:
        logger.error("meta_capi_logs insert failed: %s", e)


def _events_url() -> str:
    version = (META_API_VERSION or "v21.0").strip().lstrip("/")
    dataset = (META_DATASET_ID or "").strip()
    return f"https://graph.facebook.com/{version}/{dataset}/events"


async def _post_once(url: str, payload: dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        return await client.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
        )


async def send_qualified_lead_event(lead: dict) -> dict:
    """Hash lead PII, POST QualifiedLead to Meta CAPI, audit-log the attempt.

    Never throws to the caller. On network error or HTTP 5xx, retries once after
    2 seconds. Failures are logged and returned as ``{success: False, ...}``.
    """
    lead_id = str((lead or {}).get("id") or "").strip() or "unknown"
    event_id = ""
    user_data_keys: List[str] = []

    try:
        if not META_DATASET_ID or not META_ACCESS_TOKEN:
            msg = "META_DATASET_ID or META_ACCESS_TOKEN not configured"
            logger.error("Meta CAPI skipped for lead %s: %s", lead_id, msg)
            await _write_log(
                lead_id=lead_id,
                event_id="",
                response_status=None,
                response_body=None,
                success=False,
                error_message=msg,
            )
            return {
                "success": False,
                "event_id": "",
                "response_status": None,
                "response_body": None,
                "error_message": msg,
            }

        payload = build_payload(lead or {})
        event_data = (payload.get("data") or [{}])[0]
        event_id = str(event_data.get("event_id") or "")
        user_data_keys = sorted((event_data.get("user_data") or {}).keys())
        url = _events_url()

        last_status: Optional[int] = None
        last_body: Any = None
        last_error: Optional[str] = None

        for attempt in range(2):
            try:
                resp = await _post_once(url, payload)
                last_status = resp.status_code
                try:
                    last_body = resp.json()
                except Exception:
                    last_body = resp.text

                if resp.status_code < 500:
                    success = 200 <= resp.status_code < 300
                    error_message = None if success else (
                        f"Meta CAPI HTTP {resp.status_code}"
                    )
                    if success:
                        logger.info(
                            "Meta CAPI QualifiedLead ok lead=%s event_id=%s status=%s",
                            lead_id,
                            event_id,
                            resp.status_code,
                        )
                    else:
                        logger.error(
                            "Meta CAPI QualifiedLead failed lead=%s event_id=%s status=%s body=%s",
                            lead_id,
                            event_id,
                            resp.status_code,
                            _truncate_response_body(last_body),
                        )
                    await _write_log(
                        lead_id=lead_id,
                        event_id=event_id,
                        response_status=last_status,
                        response_body=last_body,
                        success=success,
                        error_message=error_message,
                        user_data_keys=user_data_keys,
                    )
                    return {
                        "success": success,
                        "event_id": event_id,
                        "response_status": last_status,
                        "response_body": last_body,
                        "error_message": error_message,
                    }

                last_error = f"Meta CAPI HTTP {resp.status_code}"
                logger.warning(
                    "Meta CAPI 5xx lead=%s attempt=%s status=%s",
                    lead_id,
                    attempt + 1,
                    resp.status_code,
                )
            except httpx.HTTPError as e:
                last_status = None
                last_body = None
                last_error = f"Meta CAPI network error: {e}"
                logger.warning(
                    "Meta CAPI network error lead=%s attempt=%s: %s",
                    lead_id,
                    attempt + 1,
                    e,
                )

            if attempt == 0:
                await asyncio.sleep(RETRY_DELAY_SECONDS)

        logger.error(
            "Meta CAPI QualifiedLead final failure lead=%s event_id=%s: %s",
            lead_id,
            event_id,
            last_error,
        )
        await _write_log(
            lead_id=lead_id,
            event_id=event_id,
            response_status=last_status,
            response_body=last_body,
            success=False,
            error_message=last_error,
            user_data_keys=user_data_keys,
        )
        return {
            "success": False,
            "event_id": event_id,
            "response_status": last_status,
            "response_body": last_body,
            "error_message": last_error,
        }

    except Exception as e:
        msg = f"Meta CAPI unexpected error: {e}"
        logger.error("Meta CAPI unexpected error lead=%s: %s", lead_id, e, exc_info=True)
        try:
            await _write_log(
                lead_id=lead_id,
                event_id=event_id,
                response_status=None,
                response_body=None,
                success=False,
                error_message=msg,
                user_data_keys=user_data_keys or None,
            )
        except Exception:
            pass
        return {
            "success": False,
            "event_id": event_id,
            "response_status": None,
            "response_body": None,
            "error_message": msg,
        }
