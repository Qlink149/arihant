"""MCUBE Classic inbound webhooks (no JWT)."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse

from crm.core.state import MCUBE_ALLOWLIST_ENFORCE, MCUBE_ALLOWED_IPS, MCUBE_ENABLED
from crm.services.mcube.events import insert_mcube_event
from crm.services.mcube.payload import extract_mcube_payload, verify_mcube_webhook_secret
from crm.services.mcube.process import process_mcube_event_doc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/telephony/mcube", tags=["mcube-telephony"])


def _client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    if request.client:
        return request.client.host
    return None


def _check_ip_allowlist(request: Request) -> Optional[JSONResponse]:
    if not MCUBE_ALLOWED_IPS:
        return None
    ip = _client_ip(request) or ""
    allowed = ip in MCUBE_ALLOWED_IPS
    if not allowed:
        logger.warning("MCUBE webhook IP not in allowlist ip=%s enforce=%s", ip, MCUBE_ALLOWLIST_ENFORCE)
        if MCUBE_ALLOWLIST_ENFORCE:
            return JSONResponse(status_code=403, content={"status": "error", "detail": "IP not allowed"})
    return None


async def _handle_inbound(request: Request, background_tasks: BackgroundTasks, token: Optional[str]):
    header_secret = request.headers.get("x-webhook-secret") or request.headers.get("X-Webhook-Secret")
    if not verify_mcube_webhook_secret(token=token, header_secret=header_secret):
        logger.warning("MCUBE inbound webhook invalid or missing secret")
        return JSONResponse(
            status_code=401,
            content={"status": "error", "detail": "Invalid or missing webhook secret"},
        )

    blocked = _check_ip_allowlist(request)
    if blocked is not None:
        return blocked

    try:
        payload = await extract_mcube_payload(request)
        event = await insert_mcube_event(
            raw_payload=payload,
            source_ip=_client_ip(request),
            http_method=request.method,
            content_type=request.headers.get("content-type") or "",
            direction="inbound",
        )
        if MCUBE_ENABLED:
            background_tasks.add_task(process_mcube_event_doc, event)
        else:
            # Still mark processed as ignored so cron does not loop forever when disabled
            from crm.services.mcube.events import mark_event_processed

            background_tasks.add_task(mark_event_processed, event["id"], error="mcube_disabled_ignored")
        return {"status": "ok", "event_id": event.get("id"), "enabled": MCUBE_ENABLED}
    except Exception as e:
        logger.error("MCUBE inbound webhook error: %s", e)
        return {"status": "ok"}


@router.api_route("/inbound", methods=["GET", "POST"])
async def mcube_inbound_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    token: Optional[str] = Query(default=None),
):
    """
    MCUBE Classic On Call / On Hangup push.
    Ingest durable event first, always ACK 200 after auth (WhatsApp/Webflow pattern).
    """
    return await _handle_inbound(request, background_tasks, token)
