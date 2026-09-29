"""Public Channel Partner lead-submission webhook (no JWT).

Serves cp-leads-r16 / cp-leads-melange / cp-leads-mira. Accepts JSON or a
plain HTML form POST (application/x-www-form-urlencoded / multipart), since
these are simple landing pages, not a JS webhook client like Webflow/Zapier.

Unlike the Webflow/Zapier webhooks (which always ACK 200 so the vendor never
retry-storms), this endpoint returns real HTTP status codes — these are the
client's own forms and the visitor should see a validation/duplicate error.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from crm.core.state import logger
from crm.services.channel_partner_leads_service import (
    process_channel_partner_submission,
    verify_webhook_secret,
)

router = APIRouter(prefix="/channel-partner/leads", tags=["channel-partner-leads"])


async def _parse_body(request: Request) -> dict:
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        raw_body = await request.body()
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    if "form" in content_type:
        try:
            form = await request.form()
            return dict(form)
        except Exception:
            return {}
    # Unknown/missing content-type: try JSON, then form, best-effort.
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    try:
        form = await request.form()
        return dict(form)
    except Exception:
        return {}


@router.post("/webhook")
async def channel_partner_leads_webhook_receive(
    request: Request,
    token: Optional[str] = Query(default=None),
):
    header_secret = request.headers.get("x-webhook-secret") or request.headers.get("X-Webhook-Secret")

    if not verify_webhook_secret(token=token, header_secret=header_secret):
        logger.warning("Channel Partner leads webhook invalid or missing secret")
        return JSONResponse(
            status_code=401,
            content={"status": "error", "reason": "unauthorized"},
        )

    body = await _parse_body(request)
    client_ip = request.client.host if request.client else None

    try:
        result, status = await process_channel_partner_submission(body, ip=client_ip)
    except Exception as e:
        logger.error("Channel Partner leads webhook error: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "reason": "internal_error"})

    logger.info(
        "Channel Partner leads webhook processed status=%s lead_id=%s",
        result.get("status"),
        result.get("lead_id"),
    )
    return JSONResponse(status_code=status, content=result)
