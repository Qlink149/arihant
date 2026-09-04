"""Public multi-tenant lead intake endpoint (API key auth, no JWT)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from crm.core.state import logger
from crm.services.api_key_service import resolve_api_key, touch_api_key_last_used
from crm.services.lead_intake_service import (
    IntakeRateLimitError,
    IntakeValidationError,
    contact_fingerprint,
    ingest_lead,
    write_intake_log,
)

router = APIRouter(prefix="/v1/leads", tags=["lead-intake"])


def _client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    if request.client:
        return request.client.host
    return None


def _payload_keys(body: Any) -> Optional[list]:
    if isinstance(body, dict):
        return sorted(str(k) for k in body.keys())
    return None


@router.post("/intake")
async def lead_intake(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Any:
    """Accept a website form lead. Auth: ``X-API-Key`` (multi-tenant)."""
    ip = _client_ip(request)

    api_key = await resolve_api_key(x_api_key)
    if not api_key:
        await write_intake_log(
            project_name="",
            project_id=None,
            api_key_id=None,
            ip=ip,
            success=False,
            reason="invalid_api_key",
            lead_id=None,
            http_status=401,
        )
        return JSONResponse(
            status_code=401,
            content={"success": False, "detail": "Invalid or missing API key"},
        )

    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        await write_intake_log(
            project_name=api_key.get("project_name") or "",
            project_id=api_key.get("project_id"),
            api_key_id=api_key.get("id"),
            ip=ip,
            success=False,
            reason="malformed_json",
            lead_id=None,
            http_status=400,
        )
        return JSONResponse(
            status_code=400,
            content={"success": False, "detail": "Malformed JSON body"},
        )

    if not isinstance(body, dict) or not body:
        await write_intake_log(
            project_name=api_key.get("project_name") or "",
            project_id=api_key.get("project_id"),
            api_key_id=api_key.get("id"),
            ip=ip,
            success=False,
            reason="empty_body",
            lead_id=None,
            http_status=400,
        )
        return JSONResponse(
            status_code=400,
            content={"success": False, "detail": "Request body is required"},
        )

    keys = _payload_keys(body)
    fingerprint = contact_fingerprint(body)

    try:
        result, status = await ingest_lead(body=body, api_key=api_key, ip=ip)
        # Touch last_used after successful auth path (including validation failures? only success)
        await touch_api_key_last_used(api_key["id"])
        return JSONResponse(status_code=status, content=result)
    except IntakeValidationError as e:
        await write_intake_log(
            project_name=api_key.get("project_name") or "",
            project_id=api_key.get("project_id"),
            api_key_id=api_key.get("id"),
            ip=ip,
            success=False,
            reason="validation_error",
            lead_id=None,
            http_status=422,
            payload_keys=keys,
            contact_fingerprint=fingerprint,
        )
        await touch_api_key_last_used(api_key["id"])
        return JSONResponse(
            status_code=422,
            content={"success": False, "detail": e.errors},
        )
    except IntakeRateLimitError:
        await write_intake_log(
            project_name=api_key.get("project_name") or "",
            project_id=api_key.get("project_id"),
            api_key_id=api_key.get("id"),
            ip=ip,
            success=False,
            reason="rate_limited",
            lead_id=None,
            http_status=429,
            payload_keys=keys,
            contact_fingerprint=fingerprint,
        )
        return JSONResponse(
            status_code=429,
            content={"success": False, "detail": "Rate limit exceeded"},
        )
    except Exception as e:
        logger.error("lead intake failed: %s", e, exc_info=True)
        await write_intake_log(
            project_name=api_key.get("project_name") or "",
            project_id=api_key.get("project_id"),
            api_key_id=api_key.get("id"),
            ip=ip,
            success=False,
            reason="internal_error",
            lead_id=None,
            http_status=500,
            error_type=type(e).__name__,
            error_message=str(e)[:300],
            payload_keys=keys,
            contact_fingerprint=fingerprint,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": "Internal server error"},
        )
