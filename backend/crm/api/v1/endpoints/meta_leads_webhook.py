"""Public Meta Lead Ads webhook (no JWT)."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from crm.core.state import logger
from crm.services.meta_lead_ads_service import (
    process_webhook_payload,
    verify_hub_token,
    verify_signature,
)

router = APIRouter(prefix="/meta/leads", tags=["meta-lead-ads"])


@router.get("/webhook")
async def meta_leads_webhook_verify(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
):
    """Meta subscription verification handshake."""
    if verify_hub_token(hub_mode, hub_verify_token) and hub_challenge is not None:
        return PlainTextResponse(content=str(hub_challenge), status_code=200)
    return PlainTextResponse(content="Forbidden", status_code=403)


@router.post("/webhook")
async def meta_leads_webhook_receive(request: Request):
    """Receive leadgen notifications; always ACK so Meta does not storm retries."""
    raw_body = await request.body()
    signature = request.headers.get("x-hub-signature-256") or request.headers.get(
        "X-Hub-Signature-256"
    )

    if not verify_signature(raw_body, signature):
        logger.warning("Meta leadgen webhook invalid signature")
        return JSONResponse(
            status_code=401,
            content={"status": "error", "detail": "Invalid signature"},
        )

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        logger.warning("Meta leadgen webhook malformed JSON")
        return {"status": "ok"}

    try:
        results = await process_webhook_payload(payload if isinstance(payload, dict) else {})
        logger.info("Meta leadgen webhook processed events=%s", len(results))
    except Exception as e:
        logger.error("Meta leadgen webhook error: %s", e, exc_info=True)

    return {"status": "ok"}
