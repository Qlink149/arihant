import hashlib
import hmac
import json
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from crm.core.state import get_current_user, logger, WHATSAPP_PROVIDER
from crm.services.dashboard_scope import resolve_lead_or_403
from crm.models.schemas.whatsapp_schemas import WhatsAppMessage
from crm.services import whatsapp_service

router = APIRouter()


async def _verify_gupshup_signature(request: Request) -> None:
    """
    Verify Gupshup HMAC x-hub-signature-256 header.
    Only called when WHATSAPP_PROVIDER != 'wati'.
    """
    x_hub_signature = request.headers.get("x-hub-signature-256")
    if not x_hub_signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")

    secret = os.getenv("WHATSAPP_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    body = await request.body()
    request.state.raw_body = body
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, x_hub_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@router.get("/whatsapp/templates")
async def get_whatsapp_templates(current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.get_templates()


@router.post("/whatsapp/send")
async def send_whatsapp_message(message: WhatsAppMessage, current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.send_message(message, current_user)


@router.post("/whatsapp/send-to-lead/{lead_id}")
async def send_whatsapp_to_lead(lead_id: str, message: WhatsAppMessage, current_user: dict = Depends(get_current_user)):
    await resolve_lead_or_403(lead_id, current_user)
    return await whatsapp_service.send_to_lead(lead_id, message, current_user)


@router.post("/whatsapp/send-brochure/{lead_id}")
async def send_brochure_to_lead(lead_id: str, current_user: dict = Depends(get_current_user)):
    """Send the project brochure (template + PDF) to the lead via WATI."""
    await resolve_lead_or_403(lead_id, current_user)
    return await whatsapp_service.send_brochure(lead_id, current_user)


@router.post("/whatsapp/send-pricing/{lead_id}")
async def send_pricing_to_lead(lead_id: str, current_user: dict = Depends(get_current_user)):
    """Send project pricing info via template to the lead."""
    await resolve_lead_or_403(lead_id, current_user)
    return await whatsapp_service.send_pricing(lead_id, current_user)


@router.post("/whatsapp/send-site-visit-request/{lead_id}")
async def send_site_visit_request_to_lead(lead_id: str, current_user: dict = Depends(get_current_user)):
    """Send site visit request acknowledgment to the lead."""
    await resolve_lead_or_403(lead_id, current_user)
    return await whatsapp_service.send_site_visit_request(lead_id, current_user)


@router.post("/whatsapp/send-site-visit-done/{lead_id}")
async def send_site_visit_done_to_lead(lead_id: str, current_user: dict = Depends(get_current_user)):
    """Send site visit completed thank you to the lead."""
    await resolve_lead_or_403(lead_id, current_user)
    return await whatsapp_service.send_site_visit_done(lead_id, current_user)


@router.get("/whatsapp/chat-history/{phone}")
async def get_chat_history(phone: str, current_user: dict = Depends(get_current_user), limit: int = 50):
    return await whatsapp_service.get_chat_history(phone, limit=limit)


@router.get("/whatsapp/lead-chat/{lead_id}")
async def get_lead_chat_history(lead_id: str, current_user: dict = Depends(get_current_user)):
    await resolve_lead_or_403(lead_id, current_user)
    return await whatsapp_service.get_lead_chat_history(lead_id)


@router.post("/whatsapp/lead-chat/{lead_id}/sync")
async def sync_lead_chat_history(lead_id: str, current_user: dict = Depends(get_current_user)):
    """Pull gaps from WATI into Mongo, then return DB-first history."""
    await resolve_lead_or_403(lead_id, current_user)
    return await whatsapp_service.sync_lead_chat_history(lead_id)


# ─── Gupshup integration stubs (deprecated) ───────────────────────────────────
# These routes are left in place so any stale frontend/scripts don't 404.
# They return a deprecation notice and are not actively used.

@router.post("/integrations/gupshup/setup-webhook")
async def setup_gupshup_webhook(current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.setup_webhook(current_user)


@router.get("/integrations/gupshup/subscriptions")
async def get_gupshup_subscriptions(current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.get_subscriptions()


@router.get("/integrations/gupshup/webhook-status")
async def get_webhook_status(current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.get_webhook_status()


# ─── Webhook (public — no auth on WATI path) ──────────────────────────────────

@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    """
    Receive WhatsApp webhook events.

    Auth behaviour:
      provider=wati     → no HMAC check (WATI does not send x-hub-signature-256)
      provider=disabled → still accepts POSTs (for smoke testing); ignores payload
      provider=gupshup  → enforces Gupshup HMAC signature
    """
    try:
        # WATI and disabled both skip HMAC — only gupshup enforces it
        if WHATSAPP_PROVIDER == "gupshup":
            await _verify_gupshup_signature(request)
            raw_body = getattr(request.state, "raw_body", None) or await request.body()
        else:
            raw_body = await request.body()

        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            body_str = raw_body.decode("utf-8", errors="replace")
            logger.info(f"Webhook received non-JSON body: {body_str[:200]}")
            return {"status": "ok"}

        logger.info(f"Webhook received [{WHATSAPP_PROVIDER}]: {json.dumps(body)[:500]}")
        await whatsapp_service.process_webhook(body)
        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return {"status": "ok"}  # Always 200 to webhook senders
