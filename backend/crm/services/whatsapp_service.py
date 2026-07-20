"""
WhatsApp service — WATI provider (production-safe)

Provider dispatch via WHATSAPP_PROVIDER env var:
  disabled  → all functions return soft errors, nothing crashes (default)
  wati      → routes to WATI v3/v1 API helpers below

Gupshup dead-code is preserved at the bottom for rollback reference but is
never called while WHATSAPP_PROVIDER != 'gupshup'.

DB shape is additive: new docs gain 'wati_message_id'; old 'gupshup_message_id'
docs continue to display correctly in history.
"""

import json
import os
import uuid
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import HTTPException

from crm.core.state import (
    # WATI (active)
    WHATSAPP_PROVIDER,
    WATI_API_ENDPOINT,
    WATI_API_TOKEN,
    WATI_CHANNEL_PHONE,
    WATI_BASE_URL,
    PROJECT_BROCHURE_MAP,
    PROJECT_PRICING_MAP,
    resolve_lead_project_key,

    # Gupshup (legacy dead-code)
    GUPSHUP_API_KEY,
    GUPSHUP_APP_ID,
    GUPSHUP_BASE_URL,
    GUPSHUP_PARTNER_URL,
    GUPSHUP_SOURCE_PHONE,
    GUPSHUP_TOKEN,
    db,
    logger,
)
from crm.models.schemas.whatsapp_schemas import WhatsAppMessage
from crm.utils.helpers import format_phone_for_gupshup, iso_utc_now, normalize_phone, utc_now


# ═══════════════════════════════════════════════════════════════════════════════
# WATI helpers (private)
# ═══════════════════════════════════════════════════════════════════════════════

def _wati_headers() -> dict:
    """Return WATI Bearer auth headers."""
    return {
        "Authorization": f"Bearer {WATI_API_TOKEN}",
        "Content-Type": "application/json",
    }


def _wati_phone(raw: str) -> str:
    """
    Normalise phone to digits-only with country code for WATI.
    91-9894474820  →  919894474820
    +91 9894474820 →  919894474820
    """
    digits = "".join(c for c in raw if c.isdigit())
    # If starts with 0, drop leading zero and prepend 91 (India)
    if digits.startswith("0") and len(digits) == 11:
        digits = "91" + digits[1:]
    # If 10 digits assume India
    if len(digits) == 10:
        digits = "91" + digits
    return digits


async def _wati_ensure_contact(phone: str, name: str) -> None:
    """
    Create or update a WATI contact before first outbound message.
    Soft-fails on error — send will still be attempted.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{WATI_API_ENDPOINT}/api/v1/addContact/{phone}",
                headers=_wati_headers(),
                json={
                    "name": name or phone,
                    "customParams": [{"name": "source", "value": "ArihantCRM"}],
                },
                timeout=15.0,
            )
            if resp.status_code == 200:
                logger.info(f"WATI contact ensured for {phone}")
            else:
                logger.warning(f"WATI addContact {phone} returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"WATI addContact soft-fail for {phone}: {e}")


async def _wati_send_text(phone: str, text: str) -> dict:
    """
    Send a session text message via WATI v3.
    Only valid when a 24-hour session window is open (inbound from customer < 24h ago).
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{WATI_API_ENDPOINT}/api/ext/v3/conversations/messages/text",
            headers=_wati_headers(),
            json={"target": phone, "text": text},
            timeout=30.0,
        )
        return resp


async def _wati_send_template(
    phone: str,
    template_name: str,
    parameters: list,
    broadcast_name: str = "arihant_crm",
) -> dict:
    """
    Send a WATI template message (works outside session window).
    parameters: list of {name, value} dicts, e.g. [{"name": "name", "value": "John"}]
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{WATI_API_ENDPOINT}/api/v1/sendTemplateMessage",
            params={"whatsappNumber": phone},
            headers=_wati_headers(),
            json={
                "template_name": template_name,
                "broadcast_name": broadcast_name,
                "channel_number": WATI_CHANNEL_PHONE,
                "parameters": parameters,
            },
            timeout=30.0,
        )
        return resp


async def _wati_send_file_via_url(phone: str, file_url: str, filename: str = "document.pdf") -> dict:
    """Send a file (brochure PDF) via URL to an active WATI session."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{WATI_API_ENDPOINT}/api/ext/v3/conversations/messages/fileViaUrl",
            headers=_wati_headers(),
            json={"target": phone, "url": file_url, "fileName": filename},
            timeout=30.0,
        )
        return resp


async def _wati_get_history(phone: str, page_size: int = 50) -> list:
    """
    Fetch message history from WATI v1 getMessages — keyed by phone number and
    works regardless of conversation state (the v3 conversations lookup only
    resolves OPEN conversations and returns nothing otherwise). Maps to the
    shape the frontend already expects: {direction, content, created_at, status}.
    Falls back to DB-only history on any error.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{WATI_API_ENDPOINT}/api/v1/getMessages/{phone}",
                params={"pageNumber": 1, "pageSize": page_size},
                headers=_wati_headers(),
                timeout=30.0,
            )
            if resp.status_code != 200:
                logger.warning(f"WATI get history {phone} returned {resp.status_code}")
                return []

            data = resp.json()
            # v1 shape: {"messages": {"items": [...]}} — some tenants return a plain list
            raw_messages = []
            if isinstance(data, dict):
                msgs = data.get("messages")
                if isinstance(msgs, dict):
                    raw_messages = msgs.get("items", []) or []
                elif isinstance(msgs, list):
                    raw_messages = msgs
            mapped = []
            for m in raw_messages:
                mapped.append({
                    "id": m.get("id", str(uuid.uuid4())),
                    "wati_message_id": m.get("whatsappMessageId") or m.get("id"),
                    "direction": "inbound" if not m.get("owner", True) else "outbound",
                    "content": m.get("text") or f"[{m.get('type', 'message')}]",
                    "message_type": m.get("type", "text"),
                    "status": (m.get("statusString") or m.get("status") or "").lower() or "sent",
                    "created_at": m.get("created") or iso_utc_now(),
                    "sender_name": m.get("senderName") or m.get("operatorName") or "",
                })
            return mapped
    except Exception as e:
        logger.warning(f"WATI get history soft-fail for {phone}: {e}")
        return []


async def _wati_get_templates() -> dict:
    """Fetch approved templates from WATI v3."""
    if not WATI_API_TOKEN:
        return {"success": False, "error": "WATI_API_TOKEN not configured", "templates": []}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{WATI_API_ENDPOINT}/api/ext/v3/messageTemplates",
                params={"page_number": 1, "page_size": 100},
                headers=_wati_headers(),
                timeout=30.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                templates = data.get("templates", []) if isinstance(data, dict) else []
                return {"success": True, "templates": templates, "total": data.get("total", len(templates))}
            else:
                logger.warning(f"WATI getTemplates returned {resp.status_code}: {resp.text[:200]}")
                return {"success": False, "error": f"WATI returned {resp.status_code}", "templates": []}
    except Exception as e:
        logger.error(f"WATI getTemplates error: {e}")
        return {"success": False, "error": str(e), "templates": []}


async def _is_session_open(phone: str) -> bool:
    """
    Check if a 24-hour WhatsApp session window is open for this phone.
    Session is open if we received an inbound message from this number within the last 24h.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        cutoff_iso = cutoff.isoformat()
        count = await db.whatsapp_messages.count_documents({
            "source": phone,
            "direction": "inbound",
            "created_at": {"$gte": cutoff_iso},
        })
        return count > 0
    except Exception as e:
        logger.warning(f"Session open check error for {phone}: {e}")
        return False


async def _wati_send(message: WhatsAppMessage, current_user: dict) -> dict:
    """
    Core WATI send dispatcher.
    - If template_name provided → template send (works any time)
    - If session open → plain text send
    - Else → friendly error (no 500)
    """
    phone = _wati_phone(message.destination)
    if not phone:
        return {"success": False, "error": "Invalid destination phone number"}

    if not WATI_API_TOKEN:
        return {"success": False, "error": "WhatsApp not available — WATI token not configured on server"}

    lead_name = current_user.get("full_name", "")  # fallback; send_to_lead passes lead context
    await _wati_ensure_contact(phone, lead_name or phone)

    now_dt = utc_now()
    now_iso = iso_utc_now()

    try:
        # ── Template send ──────────────────────────────────────────────────────
        if message.template_name:
            params = message.template_parameters or []
            broadcast = message.broadcast_name or "arihant_crm"
            resp = await _wati_send_template(phone, message.template_name, params, broadcast)

            try:
                result = resp.json()
            except Exception:
                result = {"raw": resp.text}

            if 200 <= resp.status_code < 300 and result.get("result"):
                wati_msg_id = str(result.get("model", {}).get("ids", [None])[0] or "")
                msg_doc = {
                    "id": str(uuid.uuid4()),
                    "wati_message_id": wati_msg_id,
                    "gupshup_message_id": None,
                    "direction": "outbound",
                    "destination": phone,
                    "message_type": "template",
                    "content": f"Template: {message.template_name}",
                    "status": "submitted",
                    "sent_by": current_user["id"],
                    "sent_by_user_id": current_user["id"],
                    "created_at": now_iso,
                    "created_at_dt": now_dt,
                }
                await db.whatsapp_messages.insert_one(msg_doc)
                return {
                    "success": True,
                    "status": "submitted",
                    "message_id": wati_msg_id,
                    "destination": phone,
                }
            else:
                err = result.get("error") or result.get("message") or f"WATI error {resp.status_code}"
                logger.error(f"WATI sendTemplate failed {phone}: {resp.status_code} {resp.text[:300]}")
                return {"success": False, "error": err, "status_code": resp.status_code}

        # ── Session text send ──────────────────────────────────────────────────
        if not message.text:
            return {"success": False, "error": "Message text is required for session messages"}

        session_open = await _is_session_open(phone)
        if not session_open:
            return {
                "success": False,
                "error": (
                    "No active WhatsApp session — the customer has not messaged in the last 24 hours. "
                    "Select an approved template to reach out."
                ),
            }

        resp = await _wati_send_text(phone, message.text)
        try:
            result = resp.json()
        except Exception:
            result = {"raw": resp.text}

        if 200 <= resp.status_code < 300:
            wati_msg_id = result.get("message", {}).get("id", "")
            msg_doc = {
                "id": str(uuid.uuid4()),
                "wati_message_id": wati_msg_id,
                "gupshup_message_id": None,
                "direction": "outbound",
                "destination": phone,
                "message_type": "text",
                "content": message.text,
                "status": result.get("message", {}).get("status", "sent"),
                "sent_by": current_user["id"],
                "sent_by_user_id": current_user["id"],
                "created_at": now_iso,
                "created_at_dt": now_dt,
            }
            await db.whatsapp_messages.insert_one(msg_doc)
            return {
                "success": True,
                "status": "sent",
                "message_id": wati_msg_id,
                "destination": phone,
            }
        else:
            err = result.get("message") or f"WATI error {resp.status_code}"
            logger.error(f"WATI sendText failed {phone}: {resp.status_code} {resp.text[:300]}")
            return {"success": False, "error": err, "status_code": resp.status_code}

    except Exception as e:
        logger.error(f"WATI send error for {phone}: {e}")
        return {"success": False, "error": f"WhatsApp send failed: {str(e)}"}


# ═══════════════════════════════════════════════════════════════════════════════
# WATI webhook handlers
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_wati_webhook(body: dict) -> None:
    """
    Process a WATI webhook payload.

    WATI sends flat JSON for each event. Key fields:
      waId           — sender's WhatsApp number (inbound) or target (outbound events)
      whatsappMessageId — WAMID
      text           — message text (inbound)
      type           — "text" | "image" | "document" | etc.
      owner          — False = inbound from customer, True = outbound from agent
      eventType      — "message" | "template_message" | "message_delivered" | "message_read" | ...
      statusString   — "SENT" | "DELIVERED" | "READ" | "FAILED"
    """
    try:
        event_type = body.get("eventType", "")
        wati_msg_id = body.get("whatsappMessageId", "") or body.get("id", "")
        owner = body.get("owner", False)

        # ── Delivery/read status update ────────────────────────────────────────
        if event_type in ("message_delivered", "message_read", "message_sent", "template_message_sent"):
            status_map = {
                "message_sent": "sent",
                "template_message_sent": "sent",
                "message_delivered": "delivered",
                "message_read": "read",
            }
            status_val = status_map.get(event_type, event_type)
            if wati_msg_id:
                st_iso = iso_utc_now()
                st_dt = utc_now()
                await db.whatsapp_messages.update_one(
                    {"wati_message_id": wati_msg_id},
                    {"$set": {"status": status_val, "updated_at": st_iso, "updated_at_dt": st_dt}},
                )
            return

        # ── Inbound message from customer ──────────────────────────────────────
        if event_type == "message" and not owner:
            wa_id = body.get("waId", "")
            text = body.get("text") or ""
            msg_type = body.get("type", "text")
            sender_name = body.get("senderName", "")

            if not text and msg_type != "text":
                text = f"[{msg_type} message]"

            now_dt = utc_now()
            now_iso = iso_utc_now()

            msg_doc = {
                "id": str(uuid.uuid4()),
                "wati_message_id": wati_msg_id,
                "gupshup_message_id": None,
                "direction": "inbound",
                "source": wa_id,
                "destination": WATI_CHANNEL_PHONE,
                "message_type": msg_type,
                "content": text,
                "sender_name": sender_name,
                "status": "received",
                "raw_payload": body,
                "created_at": now_iso,
                "created_at_dt": now_dt,
            }
            await db.whatsapp_messages.insert_one(msg_doc)
            logger.info(f"WATI inbound stored from {wa_id}: {text[:80]}")

            # Push to lead timeline (no lead_status change — per plan)
            normalized = normalize_phone(wa_id)
            lead = await db.leads.find_one({"normalized_phone": normalized}, {"_id": 0})
            if lead:
                context_update = {
                    "type": "whatsapp",
                    "timestamp": now_iso,
                    "timestamp_dt": now_dt,
                    "description": f"Incoming WhatsApp: {text[:100]}",
                    "agent": sender_name or "Customer",
                    "direction": "inbound",
                }
                await db.leads.update_one(
                    {"id": lead["id"]},
                    {"$push": {"context_updates": context_update}, "$set": {"updated_at": now_iso, "updated_at_dt": now_dt}},
                )

    except Exception as e:
        logger.error(f"WATI webhook handler error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Public API (called by endpoint router — signatures UNCHANGED)
# ═══════════════════════════════════════════════════════════════════════════════

async def get_templates() -> dict:
    if WHATSAPP_PROVIDER == "wati":
        return await _wati_get_templates()
    # disabled (or unknown)
    return {
        "success": False,
        "error": "WhatsApp is not configured on this server (WHATSAPP_PROVIDER=disabled)",
        "templates": [],
    }


async def send_message(message: WhatsAppMessage, current_user: dict) -> dict:
    if WHATSAPP_PROVIDER == "disabled":
        return {"success": False, "error": "WhatsApp is not enabled on this server"}
    if WHATSAPP_PROVIDER == "wati":
        return await _wati_send(message, current_user)
    return {"success": False, "error": f"Unknown WHATSAPP_PROVIDER: {WHATSAPP_PROVIDER}"}


async def send_to_lead(lead_id: str, message: WhatsAppMessage, current_user: dict) -> dict:
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if not message.destination:
        message.destination = lead.get("phone", "")

    result = await send_message(message, current_user)

    if result.get("success"):
        now_dt = utc_now()
        now_iso = iso_utc_now()
        context_update = {
            "type": "whatsapp",
            "timestamp": now_iso,
            "timestamp_dt": now_dt,
            "description": message.text or (
                f"WhatsApp template sent: {message.template_name}" if message.template_name else "WhatsApp message sent"
            ),
            "agent": current_user["full_name"],
            "actor_user_id": current_user["id"],
            "message_id": result.get("message_id"),
        }
        await db.leads.update_one(
            {"id": lead_id},
            {"$push": {"context_updates": context_update}, "$set": {"updated_at": now_iso, "updated_at_dt": now_dt}},
        )

    return result


async def get_chat_history(phone: str, limit: int = 50) -> dict:
    """
    Return chat history for a phone number.
    When provider=wati: merge WATI API history with DB history (DB is source of truth for inbound).
    When provider=disabled: return DB-only history (preserves old Gupshup messages).
    """
    normalized = _wati_phone(phone) if WHATSAPP_PROVIDER == "wati" else format_phone_for_gupshup(phone)

    # Always read from DB first (includes legacy Gupshup messages + new WATI inserts)
    db_messages = (
        await db.whatsapp_messages.find(
            {"$or": [{"destination": normalized}, {"source": normalized}]},
            {"_id": 0},
        )
        .sort("created_at", -1)
        .limit(limit)
        .to_list(limit)
    )

    if WHATSAPP_PROVIDER == "wati":
        # Also pull live from WATI API and merge (avoids stale DB if webhook missed)
        live_messages = await _wati_get_history(normalized, page_size=limit)
        # Deduplicate: prefer DB record if wati_message_id already stored
        db_wati_ids = {m.get("wati_message_id") for m in db_messages if m.get("wati_message_id")}
        new_live = [m for m in live_messages if m.get("wati_message_id") not in db_wati_ids]
        all_messages = list(db_messages) + new_live
        # Sort combined by created_at descending
        all_messages.sort(key=lambda m: m.get("created_at", ""), reverse=True)
        return {"phone": normalized, "messages": all_messages[:limit], "count": len(all_messages[:limit])}

    return {"phone": normalized, "messages": db_messages, "count": len(db_messages)}


async def get_lead_chat_history(lead_id: str) -> dict:
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    phone = lead.get("phone", "")
    if not phone:
        return {"messages": [], "error": "Lead has no phone number"}

    return await get_chat_history(phone)


async def send_lead_ack(lead_id: str, lead: dict) -> dict:
    """
    Template 1: Auto-Ack on New Lead (arihant_new_lead_ack_v1).
    Always returns a dict — never raises — so it is safe as a fire-and-forget task.
    """
    try:
        if WHATSAPP_PROVIDER != "wati":
            return {"success": False, "error": "WhatsApp is not enabled on this server"}

        phone = _wati_phone(lead.get("phone", ""))
        if not phone:
            return {"success": False, "error": "Lead has no phone number"}

        msg = WhatsAppMessage(
            destination=phone,
            template_name="arihant_new_lead_ack_v1",
            template_parameters=[
                {"name": "1", "value": lead.get("first_name") or lead.get("name", "Customer")},
                {"name": "2", "value": lead.get("project") or "Arihant Spaces"},
            ]
        )
        # Use a system fallback user for auto-ack
        system_user = {"id": "system", "full_name": "System Auto-Ack"}
        return await send_to_lead(lead_id, msg, system_user)
    except Exception as e:
        logger.error(f"send_lead_ack failed for lead {lead_id}: {e}")
        return {"success": False, "error": str(e)}


async def send_pricing(lead_id: str, current_user: dict) -> dict:
    """Template 2: Pricing Info (arihant_pricing_v1)."""
    if WHATSAPP_PROVIDER != "wati":
        return {"success": False, "error": "WhatsApp is not enabled on this server"}

    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    project_key = resolve_lead_project_key(lead)
    price_str = PROJECT_PRICING_MAP.get(project_key)
    if not price_str:
        return {"success": False, "error": f"Starting price not configured for project: {lead.get('project') or 'not set'}"}

    msg = WhatsAppMessage(
        destination=lead.get("phone", ""),
        template_name="arihant_pricing_v1",
        template_parameters=[
            {"name": "1", "value": lead.get("first_name") or lead.get("name", "Customer")},
            {"name": "2", "value": lead.get("project") or "Arihant Spaces"},
            {"name": "3", "value": price_str},
        ]
    )
    return await send_to_lead(lead_id, msg, current_user)


async def send_brochure(lead_id: str, current_user: dict) -> dict:
    """
    Template 3: Brochure (arihant_brochure_v1).

    The template's document header is a dynamic {{pdfLink}} variable. We pass the
    correct per-project brochure URL as a template parameter, so WhatsApp attaches
    the right PDF inside the single template message — works with no open session
    (business-initiated), unlike the old fileViaUrl step which 404'd for cold leads.
    """
    if WHATSAPP_PROVIDER != "wati":
        return {"success": False, "error": "WhatsApp is not enabled on this server"}

    if not WATI_BASE_URL:
        return {"success": False, "error": "WATI_BASE_URL is not configured on server"}

    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    phone = _wati_phone(lead.get("phone", ""))
    if not phone:
        return {"success": False, "error": "Lead has no phone number"}

    project_key = resolve_lead_project_key(lead)
    pdf_filename = PROJECT_BROCHURE_MAP.get(project_key)
    if not pdf_filename:
        return {"success": False, "error": f"No brochure PDF configured for project: {lead.get('project') or 'not set'}"}

    # WATI dynamic media header: pass the project brochure URL as {{pdfLink}}.
    pdf_url = f"{WATI_BASE_URL}/static/{pdf_filename.replace(' ', '%20')}"
    msg = WhatsAppMessage(
        destination=phone,
        template_name="arihant_brochure_v1",
        template_parameters=[{"name": "pdfLink", "value": pdf_url}],
    )
    result = await send_to_lead(lead_id, msg, current_user)
    if result.get("success"):
        result["filename"] = pdf_filename
    return result


async def send_site_visit_request(lead_id: str, current_user: dict) -> dict:
    """Template 4: Site Visit Request Ack (arihant_site_visit_request_ack_v1)."""
    if WHATSAPP_PROVIDER != "wati":
        return {"success": False, "error": "WhatsApp is not enabled on this server"}

    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    msg = WhatsAppMessage(
        destination=lead.get("phone", ""),
        template_name="arihant_site_visit_request_ack_v1",
        template_parameters=[]
    )
    return await send_to_lead(lead_id, msg, current_user)


async def send_site_visit_done(lead_id: str, current_user: dict) -> dict:
    """Template 5: Site Visit Completed (arihant_site_visit_completed_v1)."""
    if WHATSAPP_PROVIDER != "wati":
        return {"success": False, "error": "WhatsApp is not enabled on this server"}

    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    msg = WhatsAppMessage(
        destination=lead.get("phone", ""),
        template_name="arihant_site_visit_completed_v1",
        template_parameters=[]
    )
    return await send_to_lead(lead_id, msg, current_user)


async def process_webhook(body: dict) -> None:

    """
    Route incoming webhook payload to the correct provider handler.
    WATI payloads are identified by the presence of 'waId' or 'whatsappMessageId'.
    Gupshup payloads have 'entry' list (v3) or 'type' string (v2).
    """
    if WHATSAPP_PROVIDER == "wati" or "waId" in body or "whatsappMessageId" in body:
        await handle_wati_webhook(body)
    elif "entry" in body and isinstance(body.get("entry"), list):
        await handle_v3_webhook(body)
    else:
        await handle_v2_webhook(body)


# ═══════════════════════════════════════════════════════════════════════════════
# Gupshup dead-code (preserved for rollback reference — NOT called when provider=wati)
# ═══════════════════════════════════════════════════════════════════════════════

async def setup_webhook(current_user: dict) -> dict:
    """Gupshup webhook setup — deprecated, returns stub when provider != gupshup."""
    return {
        "deprecated": True,
        "message": "Gupshup integration has been replaced by WATI. This endpoint is no longer active.",
    }


async def get_subscriptions() -> dict:
    return {"deprecated": True, "message": "Gupshup subscriptions endpoint is no longer active."}


async def get_webhook_status() -> dict:
    config = await db.webhook_configs.find_one({"app_id": GUPSHUP_APP_ID}, {"_id": 0})
    recent_messages = await db.whatsapp_messages.count_documents({"direction": "inbound"})
    return {
        "provider": WHATSAPP_PROVIDER,
        "configured": WHATSAPP_PROVIDER == "wati" and bool(WATI_API_TOKEN),
        "legacy_gupshup_config": config,
        "inbound_messages_received": recent_messages,
        "webhook_endpoint": "/api/whatsapp/webhook",
    }


async def handle_v3_webhook(body: dict):
    """Gupshup v3 webhook handler — kept as dead-code for rollback."""
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
                        # WhatsApp integration is not yet live: do not auto-transition lead_status
                        # based on inbound webhooks. We only append the context update.
                        set_fields = {"updated_at": now_iso, "updated_at_dt": now_dt}
                        await db.leads.update_one(
                            {"id": lead["id"]},
                            {"$push": {"context_updates": context_update}, "$set": set_fields},
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
    """Gupshup v2 webhook handler — kept as dead-code for rollback."""
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
