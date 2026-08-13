"""Public Zapier Meta Instant Form webhook (no JWT)."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from crm.core.state import logger
from crm.services.zapier_leads_service import process_zapier_lead, verify_webhook_secret

router = APIRouter(prefix="/zapier/leads", tags=["zapier-meta-leads"])


@router.post("/webhook")
async def zapier_leads_webhook_receive(
    request: Request,
    token: Optional[str] = Query(default=None),
):
    """Receive Zapier Meta lead POSTs; ACK after auth so retries stay controlled."""
    header_secret = request.headers.get("x-webhook-secret") or request.headers.get(
        "X-Webhook-Secret"
    )

    if not verify_webhook_secret(token=token, header_secret=header_secret):
        logger.warning("Zapier Meta lead webhook invalid or missing secret")
        return JSONResponse(
            status_code=401,
            content={"status": "error", "detail": "Invalid or missing webhook secret"},
        )

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        logger.warning("Zapier Meta lead webhook malformed JSON")
        return {"status": "ok"}

    try:
        result = await process_zapier_lead(payload if isinstance(payload, dict) else {})
        logger.info(
            "Zapier Meta lead webhook processed reason=%s lead_id=%s",
            result.get("reason"),
            result.get("lead_id"),
        )
    except Exception as e:
        logger.error("Zapier Meta lead webhook error: %s", e, exc_info=True)

    return {"status": "ok"}
