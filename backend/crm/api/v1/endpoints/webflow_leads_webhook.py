"""Public Webflow enquiry form webhook (no JWT)."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from crm.core.state import logger
from crm.services.webflow_leads_service import process_form_submission, verify_webhook_secret

router = APIRouter(prefix="/webflow/leads", tags=["webflow-leads"])


@router.post("/webhook")
async def webflow_leads_webhook_receive(
    request: Request,
    token: Optional[str] = Query(default=None),
):
    """Receive Webflow form_submission events; ACK after auth so retries stay controlled."""
    header_secret = request.headers.get("x-webhook-secret") or request.headers.get(
        "X-Webhook-Secret"
    )

    if not verify_webhook_secret(token=token, header_secret=header_secret):
        logger.warning("Webflow enquiry webhook invalid or missing secret")
        return JSONResponse(
            status_code=401,
            content={"status": "error", "detail": "Invalid or missing webhook secret"},
        )

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        logger.warning("Webflow enquiry webhook malformed JSON")
        return {"status": "ok"}

    try:
        result = await process_form_submission(payload if isinstance(payload, dict) else {})
        logger.info(
            "Webflow enquiry webhook processed reason=%s lead_id=%s",
            result.get("reason"),
            result.get("lead_id"),
        )
    except Exception as e:
        logger.error("Webflow enquiry webhook error: %s", e, exc_info=True)

    return {"status": "ok"}
