import json

from fastapi import APIRouter, Depends, Request

from crm.core.state import get_current_user, logger
from crm.models.schemas.whatsapp_schemas import WhatsAppMessage
from crm.services import whatsapp_service

router = APIRouter()


@router.get("/whatsapp/templates")
async def get_whatsapp_templates(current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.get_templates()


@router.post("/whatsapp/send")
async def send_whatsapp_message(message: WhatsAppMessage, current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.send_message(message, current_user)


@router.post("/whatsapp/send-to-lead/{lead_id}")
async def send_whatsapp_to_lead(lead_id: str, message: WhatsAppMessage, current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.send_to_lead(lead_id, message, current_user)


@router.get("/whatsapp/chat-history/{phone}")
async def get_chat_history(phone: str, current_user: dict = Depends(get_current_user), limit: int = 50):
    return await whatsapp_service.get_chat_history(phone, limit=limit)


@router.get("/whatsapp/lead-chat/{lead_id}")
async def get_lead_chat_history(lead_id: str, current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.get_lead_chat_history(lead_id)


@router.post("/integrations/gupshup/setup-webhook")
async def setup_gupshup_webhook(current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.setup_webhook(current_user)


@router.get("/integrations/gupshup/subscriptions")
async def get_gupshup_subscriptions(current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.get_subscriptions()


@router.get("/integrations/gupshup/webhook-status")
async def get_webhook_status(current_user: dict = Depends(get_current_user)):
    return await whatsapp_service.get_webhook_status()


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    try:
        raw_body = await request.body()
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            body_str = raw_body.decode("utf-8")
            logger.info(f"Webhook received non-JSON body: {body_str[:200]}")
            return {"status": "ok"}

        logger.info(f"Received webhook: {json.dumps(body)[:500]}")
        await whatsapp_service.process_webhook(body)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return {"status": "error", "message": str(e)}
