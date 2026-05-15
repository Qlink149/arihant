import os
import re
import json
import uuid
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app_state import (
    db,
    logger,
    get_current_user,
    normalize_phone,
    WhatsAppMessage,
    GUPSHUP_TOKEN,
    GUPSHUP_API_KEY,
    GUPSHUP_APP_ID,
    GUPSHUP_SOURCE_PHONE,
    GUPSHUP_BASE_URL,
    GUPSHUP_PARTNER_URL,
    utc_now,
    iso_utc_now,
)


router = APIRouter()


def format_phone_for_gupshup(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if not digits.startswith("91") and len(digits) == 10:
        digits = "91" + digits
    elif digits.startswith("0"):
        digits = "91" + digits[1:]
    return digits


@router.get("/whatsapp/templates")
async def get_whatsapp_templates(current_user: dict = Depends(get_current_user)):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GUPSHUP_PARTNER_URL}/partner/app/{GUPSHUP_APP_ID}/templates",
                headers={"Authorization": f"Bearer {GUPSHUP_TOKEN}", "Content-Type": "application/json"},
                timeout=30.0,
            )

            if response.status_code == 200:
                data = response.json()
                return {"success": True, "templates": data.get("templates", data) if isinstance(data, dict) else data}
            else:
                alt_response = await client.get(
                    f"{GUPSHUP_BASE_URL}/wa/app/{GUPSHUP_APP_ID}/template",
                    headers={"apikey": GUPSHUP_API_KEY, "Content-Type": "application/json"},
                    timeout=30.0,
                )
                if alt_response.status_code == 200:
                    return {"success": True, "templates": alt_response.json()}
                return {"success": False, "error": f"Failed to fetch templates: {response.status_code}", "details": response.text}
    except Exception as e:
        logger.error(f"Error fetching templates: {str(e)}")
        return {"success": False, "error": str(e)}


@router.post("/whatsapp/send")
async def send_whatsapp_message(message: WhatsAppMessage, current_user: dict = Depends(get_current_user)):
    try:
        destination = format_phone_for_gupshup(message.destination)

        if not destination:
            raise HTTPException(status_code=400, detail="Invalid destination phone number")

        async with httpx.AsyncClient() as client:
            if message.message_type == "template" and message.template_id:
                template_data = {"id": message.template_id, "params": message.template_params or []}
                data = {"source": GUPSHUP_SOURCE_PHONE, "destination": destination, "template": json.dumps(template_data)}

                if message.media_url:
                    media_type = "image"
                    if message.media_url.endswith(".pdf"):
                        media_type = "document"
                    elif message.media_url.endswith((".mp4", ".mov")):
                        media_type = "video"

                    media_obj = {"link": message.media_url}
                    if message.media_filename:
                        media_obj["filename"] = message.media_filename

                    data["message"] = json.dumps({"type": media_type, media_type: media_obj})

                response = await client.post(
                    f"{GUPSHUP_BASE_URL}/sm/api/v1/template/msg",
                    headers={"apikey": GUPSHUP_API_KEY, "Content-Type": "application/x-www-form-urlencoded"},
                    data=data,
                    timeout=30.0,
                )
            else:
                message_obj = {"type": "text", "text": message.text or "Hello from Arihant Spaces!"}

                if message.message_type == "image" and message.media_url:
                    message_obj = {
                        "type": "image",
                        "originalUrl": message.media_url,
                        "previewUrl": message.media_url,
                        "caption": message.text or "",
                    }
                elif message.message_type == "document" and message.media_url:
                    message_obj = {"type": "file", "url": message.media_url, "filename": message.media_filename or "document.pdf"}

                data = {"channel": "whatsapp", "source": GUPSHUP_SOURCE_PHONE, "destination": destination, "message": json.dumps(message_obj)}

                response = await client.post(
                    f"{GUPSHUP_BASE_URL}/wa/api/v1/msg",
                    headers={"apikey": GUPSHUP_API_KEY, "Content-Type": "application/x-www-form-urlencoded"},
                    data=data,
                    timeout=30.0,
                )

            result = response.json() if response.headers.get("content-type", "").startswith("application/json") else {"raw": response.text}

            if 200 <= response.status_code < 300:
                now_dt = utc_now()
                now_iso = iso_utc_now()
                message_doc = {
                    "id": str(uuid.uuid4()),
                    "gupshup_message_id": result.get("messageId"),
                    "direction": "outbound",
                    "destination": destination,
                    "message_type": message.message_type,
                    "content": message.text or f"Template: {message.template_id}",
                    "status": result.get("status", "submitted"),
                    "sent_by": current_user["id"],
                    "sent_by_user_id": current_user["id"],
                    "created_at": now_iso,
                    "created_at_dt": now_dt,
                }
                await db.whatsapp_messages.insert_one(message_doc)

                return {"success": True, "status": result.get("status", "submitted"), "message_id": result.get("messageId"), "destination": destination}
            else:
                logger.error(f"Gupshup API error: {response.status_code} - {response.text}")
                return {"success": False, "error": result.get("message", "Failed to send message"), "status_code": response.status_code, "details": result}

    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/whatsapp/send-to-lead/{lead_id}")
async def send_whatsapp_to_lead(lead_id: str, message: WhatsAppMessage, current_user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if not message.destination:
        message.destination = lead.get("phone", "")

    result = await send_whatsapp_message(message, current_user)

    if result.get("success"):
        now_dt = utc_now()
        now_iso = iso_utc_now()
        context_update = {
            "type": "whatsapp",
            "timestamp": now_iso,
            "timestamp_dt": now_dt,
            "description": message.text or "WhatsApp template message sent",
            "agent": current_user["full_name"],
            "actor_user_id": current_user["id"],
            "message_id": result.get("message_id"),
        }

        await db.leads.update_one(
            {"id": lead_id},
            {"$push": {"context_updates": context_update}, "$set": {"updated_at": now_iso, "updated_at_dt": now_dt}},
        )

    return result


@router.get("/whatsapp/chat-history/{phone}")
async def get_chat_history(phone: str, current_user: dict = Depends(get_current_user), limit: int = 50):
    normalized = format_phone_for_gupshup(phone)
    messages = (
        await db.whatsapp_messages.find({"$or": [{"destination": normalized}, {"source": normalized}]}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
        .to_list(limit)
    )
    return {"phone": normalized, "messages": messages, "count": len(messages)}


@router.get("/whatsapp/lead-chat/{lead_id}")
async def get_lead_chat_history(lead_id: str, current_user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    phone = format_phone_for_gupshup(lead.get("phone", ""))
    if not phone:
        return {"messages": [], "error": "Lead has no phone number"}

    return await get_chat_history(phone, current_user)


async def get_gupshup_app_token() -> str:
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(
                f"{GUPSHUP_PARTNER_URL}/partner/app/{GUPSHUP_APP_ID}/token",
                headers={"Authorization": GUPSHUP_TOKEN, "Content-Type": "application/json"},
                timeout=30.0,
            )
            if response.status_code == 200:
                data = response.json()
                token = data.get("token", data.get("access_token", ""))
                if isinstance(data, dict) and not token:
                    token = str(data) if not isinstance(data, str) else data
                logger.info("Got Gupshup app token successfully")
                return token
            else:
                logger.error(f"Failed to get app token: {response.status_code} - {response.text}")
                return ""
    except Exception as e:
        logger.error(f"Error getting app token: {str(e)}")
        return ""


@router.post("/integrations/gupshup/setup-webhook")
async def setup_gupshup_webhook(current_user: dict = Depends(get_current_user)):
    app_url = os.environ.get("REACT_APP_BACKEND_URL", "") or "https://crm-sales-next.preview.emergentagent.com"
    webhook_url = f"{app_url}/api/whatsapp/webhook"
    results = []

    try:
        app_token = await get_gupshup_app_token()

        async with httpx.AsyncClient() as http_client:
            for auth_token in [app_token, GUPSHUP_TOKEN, f"Bearer {GUPSHUP_TOKEN}", GUPSHUP_API_KEY]:
                if not auth_token:
                    continue

                sub_data = {"modes": "MESSAGE", "tag": "arihant_crm_messages", "url": webhook_url, "version": 3, "showOnUI": True}

                response = await http_client.post(
                    f"{GUPSHUP_PARTNER_URL}/partner/app/{GUPSHUP_APP_ID}/subscription",
                    headers={"Authorization": auth_token, "Content-Type": "application/x-www-form-urlencoded", "accept": "application/json"},
                    data=sub_data,
                    timeout=30.0,
                )

                try:
                    result_data = response.json()
                except Exception:
                    result_data = {"raw": response.text}

                results.append(
                    {
                        "method": "subscription_api_v3",
                        "auth_type": "app_token"
                        if auth_token == app_token
                        else "partner_token"
                        if auth_token == GUPSHUP_TOKEN
                        else "bearer_token"
                        if "Bearer" in str(auth_token)
                        else "api_key",
                        "status_code": response.status_code,
                        "response": result_data,
                    }
                )

                if response.status_code == 200:
                    now_dt = utc_now()
                    now_iso = iso_utc_now()
                    await db.webhook_configs.update_one(
                        {"app_id": GUPSHUP_APP_ID},
                        {
                            "$set": {
                                "app_id": GUPSHUP_APP_ID,
                                "webhook_url": webhook_url,
                                "mode": "MESSAGE",
                                "version": 3,
                                "status": "active",
                                "configured_at": now_iso,
                                "configured_at_dt": now_dt,
                                "configured_by": current_user["full_name"],
                                "response": result_data,
                            }
                        },
                        upsert=True,
                    )

                    failed_data = {"modes": "FAILED", "tag": "arihant_crm_failed", "url": webhook_url, "version": 3, "showOnUI": True}
                    await http_client.post(
                        f"{GUPSHUP_PARTNER_URL}/partner/app/{GUPSHUP_APP_ID}/subscription",
                        headers={"Authorization": auth_token, "Content-Type": "application/x-www-form-urlencoded", "accept": "application/json"},
                        data=failed_data,
                        timeout=30.0,
                    )

                    return {"success": True, "message": "Webhook subscription created successfully", "webhook_url": webhook_url, "details": results}

            return {
                "success": False,
                "message": "Could not set up webhook via Subscription API. Please check credentials.",
                "webhook_url": webhook_url,
                "instruction": "You may need to set the callback URL manually in the Gupshup Partner Portal or verify your partner token has subscription permissions.",
                "attempts": results,
            }

    except Exception as e:
        logger.error(f"Error setting up Gupshup webhook: {str(e)}")
        return {"success": False, "error": str(e), "webhook_url": webhook_url, "attempts": results}


@router.get("/integrations/gupshup/subscriptions")
async def get_gupshup_subscriptions(current_user: dict = Depends(get_current_user)):
    try:
        app_token = await get_gupshup_app_token()
        async with httpx.AsyncClient() as http_client:
            for auth_token in [app_token, GUPSHUP_TOKEN]:
                if not auth_token:
                    continue
                response = await http_client.get(
                    f"{GUPSHUP_PARTNER_URL}/partner/app/{GUPSHUP_APP_ID}/subscription",
                    headers={"Authorization": auth_token, "accept": "application/json"},
                    timeout=30.0,
                )
                if response.status_code == 200:
                    return {"success": True, "subscriptions": response.json()}
        return {"success": False, "error": "Failed to fetch subscriptions"}
    except Exception as e:
        logger.error(f"Error fetching subscriptions: {str(e)}")
        return {"success": False, "error": str(e)}


@router.get("/integrations/gupshup/webhook-status")
async def get_webhook_status(current_user: dict = Depends(get_current_user)):
    config = await db.webhook_configs.find_one({"app_id": GUPSHUP_APP_ID}, {"_id": 0})
    recent_messages = await db.whatsapp_messages.count_documents({"direction": "inbound"})
    return {
        "configured": config is not None,
        "config": config,
        "inbound_messages_received": recent_messages,
        "webhook_endpoint": "/api/whatsapp/webhook",
        "gupshup_app_id": GUPSHUP_APP_ID,
        "source_phone": GUPSHUP_SOURCE_PHONE,
    }


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

        if "entry" in body and isinstance(body.get("entry"), list):
            await handle_v3_webhook(body)
        else:
            await handle_v2_webhook(body)

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return {"status": "error", "message": str(e)}


async def handle_v3_webhook(body: dict):
    try:
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                contacts = value.get("contacts", [])

                contact_map = {}
                for contact in contacts:
                    wa_id = contact.get("wa_id", "")
                    contact_map[wa_id] = contact.get("profile", {}).get("name", "")

                for msg in messages:
                    sender = msg.get("from", "")
                    sender_name = contact_map.get(sender, "Unknown")
                    msg_type = msg.get("type", "text")
                    msg_id = msg.get("id", "")

                    content = ""
                    if msg_type == "text":
                        content = msg.get("text", {}).get("body", "")
                    elif msg_type == "image":
                        content = msg.get("image", {}).get("caption", "[Image]")
                    elif msg_type == "document":
                        content = msg.get("document", {}).get("caption", "[Document]")
                    elif msg_type == "location":
                        loc = msg.get("location", {})
                        content = f"[Location: {loc.get('latitude')}, {loc.get('longitude')}]"
                    elif msg_type == "button":
                        content = msg.get("button", {}).get("text", "[Button response]")
                    elif msg_type == "interactive":
                        interactive = msg.get("interactive", {})
                        if "button_reply" in interactive:
                            content = interactive["button_reply"].get("title", "[Interactive]")
                        elif "list_reply" in interactive:
                            content = interactive["list_reply"].get("title", "[Interactive]")
                    else:
                        content = f"[{msg_type} message]"

                    now_dt = utc_now()
                    now_iso = iso_utc_now()
                    message_doc = {
                        "id": str(uuid.uuid4()),
                        "gupshup_message_id": msg_id,
                        "direction": "inbound",
                        "source": sender,
                        "destination": GUPSHUP_SOURCE_PHONE,
                        "message_type": msg_type,
                        "content": content,
                        "sender_name": sender_name,
                        "status": "received",
                        "raw_payload": body,
                        "created_at": now_iso,
                        "created_at_dt": now_dt,
                    }
                    await db.whatsapp_messages.insert_one(message_doc)
                    logger.info(f"V3 inbound message stored from {sender}: {content[:50]}")

                    normalized_sender = normalize_phone(sender)
                    lead = await db.leads.find_one({"normalized_phone": normalized_sender}, {"_id": 0})
                    if lead:
                        context_update = {
                            "type": "whatsapp",
                            "timestamp": now_iso,
                            "timestamp_dt": now_dt,
                            "description": f"Incoming WhatsApp: {content[:100]}",
                            "agent": sender_name or "Customer",
                            "direction": "inbound",
                        }
                        await db.leads.update_one(
                            {"id": lead["id"]},
                            {"$push": {"context_updates": context_update}, "$set": {"updated_at": now_iso, "updated_at_dt": now_dt}},
                        )

                statuses = value.get("statuses", [])
                for status_update in statuses:
                    gs_id = status_update.get("gs_id", "")
                    status_val = status_update.get("status", "")
                    if gs_id:
                        st_iso = iso_utc_now()
                        st_dt = utc_now()
                        await db.whatsapp_messages.update_one(
                            {"gupshup_message_id": gs_id},
                            {"$set": {"status": status_val, "updated_at": st_iso, "updated_at_dt": st_dt}},
                        )
    except Exception as e:
        logger.error(f"V3 webhook handler error: {str(e)}")


async def handle_v2_webhook(body: dict):
    try:
        event_type = body.get("type", "")

        if event_type == "message":
            payload = body.get("payload", {})
            sender = payload.get("sender", {}).get("phone", "") or payload.get("source", "")
            message_text = ""
            message_type = payload.get("type", "text")

            inner_payload = payload.get("payload", {})
            if isinstance(inner_payload, dict):
                message_text = inner_payload.get("text", inner_payload.get("body", ""))
            elif isinstance(inner_payload, str):
                message_text = inner_payload

            if not message_text and message_type == "text":
                message_text = payload.get("text", "")

            now_dt = utc_now()
            now_iso = iso_utc_now()
            message_doc = {
                "id": str(uuid.uuid4()),
                "gupshup_message_id": body.get("messageId", payload.get("id", "")),
                "direction": "inbound",
                "source": sender,
                "destination": GUPSHUP_SOURCE_PHONE,
                "message_type": message_type,
                "content": message_text or f"[{message_type} message]",
                "sender_name": payload.get("sender", {}).get("name", ""),
                "status": "received",
                "raw_payload": body,
                "created_at": now_iso,
                "created_at_dt": now_dt,
            }
            await db.whatsapp_messages.insert_one(message_doc)
            logger.info(f"V2 inbound message stored from {sender}: {message_text[:50]}")

            normalized_sender = normalize_phone(sender)
            lead = await db.leads.find_one({"normalized_phone": normalized_sender}, {"_id": 0})
            if lead:
                context_update = {
                    "type": "whatsapp",
                    "timestamp": now_iso,
                    "timestamp_dt": now_dt,
                    "description": f"Incoming WhatsApp: {message_text[:100]}" if message_text else "Incoming WhatsApp message",
                    "agent": "Customer",
                    "direction": "inbound",
                }
                await db.leads.update_one(
                    {"id": lead["id"]},
                    {"$push": {"context_updates": context_update}, "$set": {"updated_at": now_iso, "updated_at_dt": now_dt}},
                )

        elif event_type in ["message-event", "enqueued", "failed", "sent", "delivered", "read"]:
            message_id = body.get("messageId", body.get("payload", {}).get("gsId"))
            status_val = body.get("type", body.get("payload", {}).get("type", "unknown"))
            if message_id:
                st_iso = iso_utc_now()
                st_dt = utc_now()
                await db.whatsapp_messages.update_one(
                    {"gupshup_message_id": message_id},
                    {"$set": {"status": status_val, "updated_at": st_iso, "updated_at_dt": st_dt}},
                )
    except Exception as e:
        logger.error(f"V2 webhook handler error: {str(e)}")

