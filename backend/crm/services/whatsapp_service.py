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
import re
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urlparse

import httpx
from crm.services.lead_project_fields import primary_project_label

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
    resolve_user_id_by_full_name,

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
from crm.services.notification_service import create_notification
from crm.models.schemas.whatsapp_schemas import WhatsAppMessage
from crm.services.dashboard_scope import (
    rep_lead_filter,
    task_assignee_clause,
)
from crm.utils.helpers import (
    coerce_datetime,
    format_phone_for_gupshup,
    iso_utc_now,
    normalize_phone,
    utc_now,
)

# Inbox list caps — keep query bounded for CRM scale.
_INBOX_PEER_CANDIDATE_CAP = 500
_INBOX_DEFAULT_LIMIT = 50
_INBOX_MAX_LIMIT = 100
_INBOX_FILTERS = frozenset({"all", "unread", "mine"})


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


# Friendly labels for WATI message types / our templates (display only — never changes send payloads).
_WATI_TYPE_LABELS = {
    "text": "Message",
    "image": "Image",
    "document": "PDF document",
    "audio": "Audio",
    "voice": "Voice message",
    "video": "Video",
    "sticker": "Sticker",
    "location": "Location",
    "contacts": "Contact",
    "button": "Button reply",
    "interactive": "Interactive reply",
    "reaction": "Reaction",
    "template": "Template message",
    "media_placeholder": "Media",
    "order": "Order",
    "catalog": "Catalog",
}

_TEMPLATE_DISPLAY_NAMES = {
    "arihant_new_lead_ack_v1": "New lead acknowledgment",
    "arihant_pricing_v1": "Pricing information",
    "arihant_brochure_v1": "Project brochure",
    "arihant_site_visit_request_ack_v1": "Site visit request",
    "arihant_site_visit_completed_v1": "Site visit completed",
}

_PLACEHOLDER_CONTENT_RE = re.compile(r"^\[(.+)\]$")
# WATI broadcast rows: 'Broadcast message with using "arihant_pricing_v1" template was received …'
_WATI_BROADCAST_TEMPLATE_RE = re.compile(
    r'using\s+"([^"]+)"\s+template',
    re.IGNORECASE,
)


def _friendly_template_label(template_name: str) -> str:
    name = (template_name or "").strip()
    if not name:
        return "Template message"
    return _TEMPLATE_DISPLAY_NAMES.get(name, name.replace("_", " "))


def _reply_object_text(obj) -> str:
    """Extract display text from WATI button/list reply objects."""
    if not isinstance(obj, dict):
        return ""
    for key in ("text", "title", "payload"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _filename_from_url(url: str) -> str:
    if not url or not isinstance(url, str):
        return ""
    try:
        path = unquote(urlparse(url).path or "")
        return path.rsplit("/", 1)[-1] if path else ""
    except Exception:
        return ""


def _is_wati_media_path(path: str) -> bool:
    """True for WATI relative media paths like data/images/….jpg."""
    if not isinstance(path, str):
        return False
    p = path.strip().replace("\\", "/")
    return p.startswith("data/") and "/" in p[5:]


def _infer_media_type_from_path(path: str) -> str:
    p = (path or "").strip().lower().replace("\\", "/")
    if not p:
        return ""
    if "/images/" in p or p.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")):
        return "image"
    if "/audio/" in p or p.endswith((".ogg", ".mp3", ".m4a", ".aac", ".opus", ".amr", ".wav")):
        return "audio"
    if "/video/" in p or p.endswith((".mp4", ".3gp", ".mov", ".webm")):
        return "video"
    if "/document/" in p or p.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")):
        return "document"
    return ""


def _media_display_name(path_or_name: str) -> str:
    if not path_or_name:
        return "File"
    name = path_or_name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return unquote(name) or "File"


def _crm_media_proxy_path(file_name: str) -> str:
    """Relative API path the frontend loads via authenticated blob fetch."""
    return f"/whatsapp/media?fileName={quote(file_name, safe='')}"


def _is_wati_system_event(m: dict) -> bool:
    """
    WATI getMessages mixes real chat with ticket lifecycle events
    (chat initialized, status Open, expired, …). Those are not WhatsApp bubbles.
    """
    if not isinstance(m, dict):
        return True
    event_type = str(m.get("eventType") or "").strip().lower()
    return event_type == "ticket"


def _template_name_from_wati(m: dict):
    """Resolve template name from explicit fields or broadcast eventDescription."""
    if not isinstance(m, dict):
        return None
    for key in ("templateName", "template_name"):
        val = m.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    tmpl = m.get("template")
    if isinstance(tmpl, dict):
        for key in ("elementName", "name", "templateName"):
            val = tmpl.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    elif isinstance(tmpl, str) and tmpl.strip():
        return tmpl.strip()
    desc = m.get("eventDescription")
    if isinstance(desc, str) and desc.strip():
        match = _WATI_BROADCAST_TEMPLATE_RE.search(desc)
        if match:
            return match.group(1).strip()
    return None


def _extract_wati_content(m: dict) -> str:
    """
    Build human-readable chat content from a WATI message/webhook payload.
    Prefer real text / button labels / document names over raw type codes like [0].
    """
    if not isinstance(m, dict):
        return "WhatsApp message"

    text = m.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    # Template / broadcast rows from getMessages use finalText (not text)
    final_text = m.get("finalText")
    if isinstance(final_text, str) and final_text.strip():
        return final_text.strip()

    for key in ("buttonReply", "interactiveButtonReply", "listReply"):
        reply = _reply_object_text(m.get(key))
        if reply:
            return reply

    tc = m.get("templateContent")
    if isinstance(tc, dict):
        parts = []
        for key in ("headerText", "body", "bodyText"):
            val = tc.get(key)
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
        if parts:
            return "\n".join(parts)

    msg_type = m.get("type")
    type_str = str(msg_type).strip().lower() if msg_type is not None else ""
    event_type = str(m.get("eventType") or "").strip().lower()

    data = m.get("data")
    filename = None
    if isinstance(data, dict):
        filename = (
            data.get("fileName")
            or data.get("filename")
            or data.get("name")
            or data.get("caption")
        )
        if isinstance(filename, str):
            filename = filename.strip() or None
        else:
            filename = None
    elif isinstance(data, str) and data.strip() and not data.strip().startswith("http"):
        filename = data.strip()

    source_url = (
        m.get("sourceUrl")
        or m.get("headerLink")
        or m.get("mediaHeaderLink")
        or ""
    )
    if not filename and isinstance(source_url, str):
        filename = _filename_from_url(source_url) or None

    if type_str in ("document", "image", "video", "audio", "voice", "sticker", "media_placeholder"):
        label = _WATI_TYPE_LABELS.get(type_str, "Media")
        return f"{label}: {filename}" if filename else label

    template_name = _template_name_from_wati(m)
    if type_str == "template" or event_type == "broadcastmessage" or template_name:
        # Prefer body text when present; otherwise friendly template label
        label = _friendly_template_label(template_name) if template_name else "Template message"
        return f"{label}: {filename}" if filename else label

    if type_str in _WATI_TYPE_LABELS:
        return _WATI_TYPE_LABELS[type_str]

    # Numeric / unknown type codes → never surface as "[0]" / "[1]"
    if type_str.isdigit() or isinstance(msg_type, int):
        return "WhatsApp message"
    if type_str:
        return type_str.replace("_", " ").title()
    return "WhatsApp message"


def _humanize_stored_content(content) -> str:
    """Upgrade legacy stored placeholders without rewriting Mongo docs."""
    if content is None:
        return "WhatsApp message"
    if not isinstance(content, str):
        return str(content)
    c = content.strip()
    if not c:
        return "WhatsApp message"
    if c.lower().startswith("template:"):
        return _friendly_template_label(c.split(":", 1)[1].strip())
    m = _PLACEHOLDER_CONTENT_RE.match(c)
    if m:
        inner = m.group(1).strip()
        inner_key = re.sub(r"\s+message$", "", inner, flags=re.I).strip().lower()
        if inner_key.isdigit() or inner_key in ("message", "msg", ""):
            return "WhatsApp message"
        if inner_key in _WATI_TYPE_LABELS:
            return _WATI_TYPE_LABELS[inner_key]
        return inner.replace("_", " ").title()
    return content


def _outbound_template_content(template_name: str, parameters=None) -> str:
    """Human-readable content for outbound template rows we insert into Mongo."""
    label = _friendly_template_label(template_name)
    for p in parameters or []:
        if not isinstance(p, dict):
            continue
        if (p.get("name") or "").strip() != "pdfLink":
            continue
        name = _filename_from_url(p.get("value") or "")
        if name:
            return f"{label}: {unquote(name)}"
    return label


def _message_sort_ts(m: dict) -> float:
    """Stable epoch seconds for chat history ordering (DB + live WATI merge)."""
    if not isinstance(m, dict):
        return 0.0
    raw = m.get("created_at_dt") if m.get("created_at_dt") is not None else m.get("created_at")
    dt = coerce_datetime(raw)
    if dt is not None:
        return dt.timestamp()
    # Unix seconds (string/int) from some WATI payloads
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _looks_like_media_template_error(result: dict) -> bool:
    """True when WATI likely rejected the brochure template media/header params."""
    if not isinstance(result, dict):
        return False
    code = result.get("status_code")
    err = str(result.get("error") or "").lower()
    if code == 400:
        return True
    needles = ("pdf", "media", "header", "parameter", "variable", "document", "url", "link", "file")
    return any(n in err for n in needles)


def _pdf_from_template_params(parameters) -> tuple:
    """Return (pdf_url, filename) from template parameters named pdfLink."""
    for p in parameters or []:
        if not isinstance(p, dict):
            continue
        if (p.get("name") or "").strip() != "pdfLink":
            continue
        url = (p.get("value") or "").strip()
        if url:
            return url, unquote(_filename_from_url(url) or "")
    return None, None


def _normalize_wati_message(m: dict, *, phone: str = "") -> dict:
    """
    Build an additive CRM whatsapp_messages doc from a WATI payload.
    Keeps `content` for backward compat and adds structured optional fields.
    """
    if not isinstance(m, dict):
        return {
            "id": str(uuid.uuid4()),
            "content": "WhatsApp message",
            "message_type": "text",
            "direction": "outbound",
            "created_at": iso_utc_now(),
            "created_at_dt": utc_now(),
            "status": "sent",
        }

    content = _extract_wati_content(m)
    event_type = str(m.get("eventType") or "").strip().lower()
    msg_type = m.get("type", "text")
    type_str = str(msg_type).strip().lower() if msg_type is not None else "text"
    if type_str.isdigit() or isinstance(msg_type, int):
        type_str = "text"
    if event_type == "broadcastmessage":
        type_str = "template"

    reply_label = ""
    for key in ("buttonReply", "interactiveButtonReply", "listReply"):
        reply_label = _reply_object_text(m.get(key))
        if reply_label:
            break

    data = m.get("data")
    media_filename = None
    if isinstance(data, dict):
        raw_name = (
            data.get("fileName")
            or data.get("filename")
            or data.get("name")
            or data.get("caption")
        )
        if isinstance(raw_name, str) and raw_name.strip():
            media_filename = raw_name.strip()
    elif isinstance(data, str) and data.strip() and not data.strip().startswith("http"):
        media_filename = data.strip()

    media_url = (
        m.get("sourceUrl")
        or m.get("headerLink")
        or m.get("mediaHeaderLink")
        or None
    )
    if isinstance(media_url, str):
        media_url = media_url.strip() or None
    else:
        media_url = None

    if not media_filename and media_url:
        media_filename = _filename_from_url(media_url) or None

    # WATI often stores relative paths in `data` without sourceUrl — proxy via CRM.
    if not media_url and media_filename and _is_wati_media_path(media_filename):
        media_url = _crm_media_proxy_path(media_filename)

    # Prefer explicit WATI type; fall back to path inference (never treat jpg as document).
    inferred = _infer_media_type_from_path(media_filename or media_url or "")
    if type_str in ("text", "") and inferred:
        type_str = inferred
    elif type_str not in ("image", "audio", "video", "document", "voice", "sticker") and inferred:
        type_str = inferred
    if type_str == "voice":
        type_str = "audio"

    template_name = _template_name_from_wati(m)

    created_raw = m.get("created") or m.get("timestamp")
    created_dt = coerce_datetime(created_raw)
    if created_dt is None and created_raw is not None:
        try:
            # WATI sometimes sends unix seconds as string
            created_dt = datetime.fromtimestamp(float(created_raw), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            created_dt = None
    if created_dt is None:
        created_dt = utc_now()
    created_iso = created_dt.isoformat()

    # Broadcasts omit owner; they are outbound template sends from WATI/CRM.
    if event_type == "broadcastmessage":
        owner = True
    elif "owner" in m:
        owner = bool(m.get("owner"))
    else:
        owner = True
    direction = "inbound" if not owner else "outbound"

    # getMessages uses internal conversation `id`; webhooks use WhatsApp `wamid.*`.
    # Keep both so upsert can merge the same bubble from either source.
    raw_local = m.get("id")
    raw_wamid = m.get("whatsappMessageId")
    local_id = str(raw_local).strip() if raw_local not in (None, "") else None
    wamid = str(raw_wamid).strip() if isinstance(raw_wamid, str) and raw_wamid.strip() else None
    wati_id = wamid or local_id

    wa_id = m.get("waId") or phone or ""
    if direction == "inbound":
        source = _wati_phone(wa_id) if wa_id else wa_id
        destination = WATI_CHANNEL_PHONE
    else:
        source = None
        destination = _wati_phone(phone or wa_id) if (phone or wa_id) else (phone or wa_id)

    status = (m.get("statusString") or m.get("status") or "").lower() or (
        "received" if direction == "inbound" else "sent"
    )

    doc = {
        "id": str(uuid.uuid4()),
        "wati_message_id": wati_id,
        "gupshup_message_id": None,
        "direction": direction,
        "destination": destination,
        "message_type": type_str,
        "content": content,
        "status": status,
        "sender_name": m.get("senderName") or m.get("operatorName") or "",
        "created_at": created_iso,
        "created_at_dt": created_dt,
    }
    if local_id:
        doc["wati_local_id"] = local_id
    if source:
        doc["source"] = source
    if media_url:
        doc["media_url"] = media_url
    if media_filename:
        doc["media_filename"] = media_filename
    if template_name:
        doc["template_name"] = template_name
    if reply_label:
        doc["reply_label"] = reply_label
        # Prefer reply label as content when text was empty-ish placeholder
        if not (isinstance(m.get("text"), str) and m.get("text").strip()):
            doc["content"] = reply_label
    return doc


def _is_wamid(value) -> bool:
    return isinstance(value, str) and value.startswith("wamid.")


def _collect_wati_ids(*docs) -> list:
    ids = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        for key in ("wati_message_id", "wati_local_id"):
            val = d.get(key)
            if isinstance(val, str) and val.strip():
                ids.append(val.strip())
    # preserve order, unique
    return list(dict.fromkeys(ids))


def _pick_primary_and_local_wati_ids(*docs) -> tuple:
    ids = _collect_wati_ids(*docs)
    primary = next((x for x in ids if _is_wamid(x)), ids[0] if ids else None)
    local = next((x for x in ids if x != primary and not _is_wamid(x)), None)
    if local is None and primary and not _is_wamid(primary):
        local = primary
    return primary, local


def _ids_suggest_same_message(a: dict, b: dict) -> bool:
    """
    True only for the same WhatsApp bubble referenced two ways
    (shared id, or webhook wamid paired with getMessages local id).
    Distinct local ids / distinct wamids are different messages — even if text matches.
    """
    a_ids = set(_collect_wati_ids(a))
    b_ids = set(_collect_wati_ids(b))
    if not a_ids or not b_ids:
        # Incomplete id on one side: allow soft twin only with content+time at caller
        a_w = any(_is_wamid(x) for x in a_ids)
        b_w = any(_is_wamid(x) for x in b_ids)
        a_l = any(not _is_wamid(x) for x in a_ids)
        b_l = any(not _is_wamid(x) for x in b_ids)
        if (a_w and b_l and not b_w) or (b_w and a_l and not a_w):
            return True
        if (a_w and not b_ids) or (b_w and not a_ids):
            return True
        return False
    if a_ids & b_ids:
        return True
    a_w = [x for x in a_ids if _is_wamid(x)]
    b_w = [x for x in b_ids if _is_wamid(x)]
    a_l = [x for x in a_ids if not _is_wamid(x)]
    b_l = [x for x in b_ids if not _is_wamid(x)]
    # Classic twin: one row is wamid-only, the other is local-only
    if a_w and b_l and not b_w:
        return True
    if b_w and a_l and not a_w:
        return True
    return False


async def _find_existing_whatsapp_message(doc: dict):
    """Match by wamid/local id, else wamid↔local twin with same text within 30s."""
    if not isinstance(doc, dict):
        return None

    ids = _collect_wati_ids(doc)
    if ids:
        existing = await db.whatsapp_messages.find_one(
            {
                "$or": [
                    {"wati_message_id": {"$in": ids}},
                    {"wati_local_id": {"$in": ids}},
                ]
            }
        )
        if existing:
            return existing

    content = (doc.get("content") or "").strip()
    direction = doc.get("direction")
    if not content or not direction:
        return None
    created = coerce_datetime(doc.get("created_at_dt") or doc.get("created_at"))
    if created is None:
        return None

    phone_ors = []
    if doc.get("source"):
        phone_ors.append({"source": doc["source"]})
    if doc.get("destination"):
        phone_ors.append({"destination": doc["destination"]})
    query = {"direction": direction, "content": content}
    if phone_ors:
        query["$or"] = phone_ors

    candidates = (
        await db.whatsapp_messages.find(query).sort("created_at", -1).limit(25).to_list(25)
    )
    for cand in candidates:
        other = coerce_datetime(cand.get("created_at_dt") or cand.get("created_at"))
        if other is None:
            continue
        if abs((other - created).total_seconds()) > 30:
            continue
        # Do NOT merge two distinct local-id messages that happen to share text
        if _ids_suggest_same_message(doc, cand):
            return cand
    return None


async def _upsert_whatsapp_message(doc: dict) -> None:
    """
    Idempotent write. Merges webhook wamid rows with getMessages local ids so
    the same WhatsApp bubble is not stored twice.
    """
    if not isinstance(doc, dict):
        return

    for key in ("wati_message_id", "wati_local_id"):
        val = doc.get(key)
        if isinstance(val, str):
            doc[key] = val.strip() or None
        elif val is not None and not isinstance(val, str):
            doc[key] = str(val)

    existing = await _find_existing_whatsapp_message(doc)
    primary, local = _pick_primary_and_local_wati_ids(existing or {}, doc)

    set_fields = {k: v for k, v in doc.items() if k != "id" and v is not None}
    if primary:
        set_fields["wati_message_id"] = primary
    if local:
        set_fields["wati_local_id"] = local

    if existing:
        keep_id = existing.get("id") or doc.get("id") or str(uuid.uuid4())
        extra_ids = _collect_wati_ids(
            existing, doc, {"wati_message_id": primary, "wati_local_id": local}
        )
        # Delete siblings first so unique wati_message_id index cannot conflict
        sibling_ors = []
        if extra_ids:
            sibling_ors.extend(
                [
                    {"wati_message_id": {"$in": extra_ids}},
                    {"wati_local_id": {"$in": extra_ids}},
                ]
            )
        if primary:
            sibling_ors.append({"wati_message_id": primary})
        if sibling_ors:
            await db.whatsapp_messages.delete_many(
                {"id": {"$ne": keep_id}, "$or": sibling_ors}
            )
        await db.whatsapp_messages.update_one(
            {"id": keep_id} if existing.get("id") else {"_id": existing["_id"]},
            {"$set": set_fields},
        )
        return

    if primary:
        set_fields["wati_message_id"] = primary
        await db.whatsapp_messages.update_one(
            {"wati_message_id": primary},
            {
                "$set": set_fields,
                "$setOnInsert": {"id": doc.get("id") or str(uuid.uuid4())},
            },
            upsert=True,
        )
    else:
        doc.pop("wati_message_id", None)
        if "id" not in doc:
            doc["id"] = str(uuid.uuid4())
        await db.whatsapp_messages.insert_one(doc)


async def _collapse_near_duplicate_messages(phone: str) -> int:
    """
    Remove webhook/sync twins only (shared ids or wamid↔local).
    Never delete distinct messages that merely share the same text.
    """
    if not phone:
        return 0
    msgs = await db.whatsapp_messages.find(
        {"$or": [{"destination": phone}, {"source": phone}]},
        {
            "_id": 0,
            "id": 1,
            "wati_message_id": 1,
            "wati_local_id": 1,
            "direction": 1,
            "content": 1,
            "created_at": 1,
            "created_at_dt": 1,
            "status": 1,
            "sender_name": 1,
        },
    ).to_list(1000)
    if len(msgs) < 2:
        return 0

    deleted = 0
    used = set()
    for i, a in enumerate(msgs):
        aid = a.get("id")
        if not aid or aid in used:
            continue
        ta = coerce_datetime(a.get("created_at_dt") or a.get("created_at"))
        group = [a]
        for b in msgs[i + 1 :]:
            bid = b.get("id")
            if not bid or bid in used:
                continue
            if a.get("direction") != b.get("direction"):
                continue
            if (a.get("content") or "").strip() != (b.get("content") or "").strip():
                continue
            tb = coerce_datetime(b.get("created_at_dt") or b.get("created_at"))
            if ta is None or tb is None:
                continue
            if abs((ta - tb).total_seconds()) > 30:
                continue
            if not _ids_suggest_same_message(a, b):
                continue
            group.append(b)

        if len(group) == 1:
            used.add(aid)
            continue

        def _score(m: dict) -> tuple:
            return (
                2 if _is_wamid(m.get("wati_message_id")) else 0,
                1 if m.get("sender_name") else 0,
                1 if (m.get("status") or "").lower() == "received" else 0,
            )

        group.sort(key=_score, reverse=True)
        keeper = group[0]
        primary, local = _pick_primary_and_local_wati_ids(*group)
        merge_set = {}
        if primary:
            merge_set["wati_message_id"] = primary
        if local:
            merge_set["wati_local_id"] = local
        if keeper.get("sender_name") in (None, "") and any(g.get("sender_name") for g in group):
            merge_set["sender_name"] = next(g["sender_name"] for g in group if g.get("sender_name"))
        if merge_set:
            await db.whatsapp_messages.update_one({"id": keeper["id"]}, {"$set": merge_set})
        used.add(keeper["id"])
        for extra in group[1:]:
            await db.whatsapp_messages.delete_one({"id": extra["id"]})
            used.add(extra["id"])
            deleted += 1
    return deleted


def _dedupe_history_messages(messages: list) -> list:
    """
    Collapse webhook+sync twins in API responses only.
    Prefer wamid row when ids indicate the same bubble.
    """
    if not messages:
        return []
    ranked = sorted(messages, key=_message_sort_ts)
    kept = []
    for msg in ranked:
        if not isinstance(msg, dict):
            continue
        content = (msg.get("content") or "").strip()
        direction = msg.get("direction")
        ts = coerce_datetime(msg.get("created_at_dt") or msg.get("created_at"))
        dup_idx = None
        for i, prev in enumerate(kept):
            if prev.get("direction") != direction:
                continue
            if (prev.get("content") or "").strip() != content:
                continue
            pts = coerce_datetime(prev.get("created_at_dt") or prev.get("created_at"))
            if ts is None or pts is None:
                continue
            if abs((ts - pts).total_seconds()) > 30:
                continue
            if not _ids_suggest_same_message(prev, msg):
                continue
            dup_idx = i
            break
        if dup_idx is None:
            kept.append(msg)
            continue
        prev = kept[dup_idx]
        prev_score = (
            2 if _is_wamid(prev.get("wati_message_id")) else 0,
            1 if prev.get("sender_name") else 0,
            1 if (prev.get("status") or "").lower() == "received" else 0,
        )
        msg_score = (
            2 if _is_wamid(msg.get("wati_message_id")) else 0,
            1 if msg.get("sender_name") else 0,
            1 if (msg.get("status") or "").lower() == "received" else 0,
        )
        if msg_score > prev_score:
            kept[dup_idx] = msg
    return kept


def _decorate_history_messages(messages: list) -> list:
    """Humanize content and attach playable media proxy URLs for API responses."""
    out = []
    for m in _dedupe_history_messages(messages):
        if not isinstance(m, dict):
            continue
        row = dict(m)
        row["content"] = _humanize_stored_content(row.get("content"))
        media_url = row.get("media_url")
        media_filename = row.get("media_filename")
        if isinstance(media_filename, str) and media_filename.strip():
            # Prefer basename for display in clients that show media_filename
            if _is_wati_media_path(media_filename) and not (
                isinstance(media_url, str) and media_url.strip().startswith("http")
            ):
                row["media_url"] = _crm_media_proxy_path(media_filename.strip())
            display = _media_display_name(media_filename)
            row["media_display_name"] = display
        # Fix legacy rows typed/labelled wrong
        mtype = str(row.get("message_type") or "").lower()
        inferred = _infer_media_type_from_path(
            (media_filename or "") if isinstance(media_filename, str) else ""
        )
        if inferred and mtype in ("", "text", "document") and inferred != "document":
            # Don't downgrade real PDFs; do upgrade image/audio paths mislabeled as document
            if inferred in ("image", "audio", "video"):
                row["message_type"] = inferred
        out.append(row)
    return out


async def fetch_wati_media(file_name: str) -> tuple:
    """
    Download media from WATI v1 getMedia.
    Returns (content_bytes, content_type) or raises ValueError/HTTP-ish errors.
    """
    name = (file_name or "").strip()
    if not name or not _is_wati_media_path(name):
        raise ValueError("Invalid media file name")
    if not WATI_API_TOKEN:
        raise RuntimeError("WATI not configured")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(
            f"{WATI_API_ENDPOINT}/api/v1/getMedia",
            params={"fileName": name},
            headers={"Authorization": f"Bearer {WATI_API_TOKEN}"},
            timeout=60.0,
        )
    if resp.status_code != 200:
        raise LookupError(f"Media not found ({resp.status_code})")
    content_type = resp.headers.get("content-type") or "application/octet-stream"
    return resp.content, content_type


async def _preflight_public_url(url: str) -> tuple:
    """
    Verify Meta/WATI can likely fetch the PDF. HEAD first; some hosts need GET Range.
    Returns (ok, error_message).
    """
    if not url:
        return False, "PDF URL is empty"
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.head(url, timeout=15.0)
            if resp.status_code >= 400:
                resp = await client.get(url, headers={"Range": "bytes=0-0"}, timeout=15.0)
            if resp.status_code >= 400:
                return False, f"PDF URL not reachable (HTTP {resp.status_code}): {url}"
            return True, ""
    except Exception as e:
        return False, f"PDF URL not reachable: {e}"


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


def _wati_session_targets(phone: str) -> list:
    """
    Targets for v3 conversation APIs. Prefer plain phone, then channel-scoped
    Channel:Phone (needed on multi-channel tenants — otherwise WATI returns 404).
    """
    targets = []
    if phone:
        targets.append(phone)
    ch = (WATI_CHANNEL_PHONE or "").strip()
    if ch and phone:
        scoped = f"{ch}:{phone}"
        if scoped not in targets:
            targets.append(scoped)
    return targets


def _friendly_wati_send_error(status_code: int, result, *, kind: str = "message") -> str:
    """Map raw WATI errors to short, user-facing copy for toasts."""
    raw = ""
    if isinstance(result, dict):
        raw = result.get("error") or result.get("message") or result.get("info") or ""
        if isinstance(raw, dict):
            raw = raw.get("message") or raw.get("error") or str(raw)
    raw_s = str(raw or "").strip()
    low = raw_s.lower()

    if status_code == 404 or "not found" in low or "conversation" in low:
        return (
            "No open WhatsApp chat with this customer right now. "
            "Ask them to reply once on WhatsApp, or send an approved template instead."
        )
    if status_code == 401 or status_code == 403:
        return "WhatsApp is not authorized on the server. Check the WATI API token."
    if status_code == 429:
        return "WhatsApp rate limit hit. Wait a moment and try again."
    if status_code == 400:
        return raw_s or f"WhatsApp rejected this {kind}. Check details and try again."
    if 500 <= int(status_code or 0) < 600:
        return "WhatsApp service is temporarily unavailable. Try again shortly."
    if raw_s and not raw_s.lower().startswith("wati error"):
        return raw_s
    return f"Could not send WhatsApp {kind}. Please try again."


async def _wati_send_text(phone: str, text: str):
    """
    Send a session text message via WATI v1 sendSessionMessage.
    messageText must be a query param (JSON body is ignored by WATI).
    Only valid when a 24-hour session window is open.
    """
    if not text or not str(text).strip():
        return None
    last_resp = None
    async with httpx.AsyncClient() as client:
        for target in _wati_session_targets(phone):
            resp = await client.post(
                f"{WATI_API_ENDPOINT}/api/v1/sendSessionMessage/{target}",
                headers=_wati_headers(),
                params={"messageText": str(text).strip()},
                timeout=30.0,
            )
            last_resp = resp
            # v1 returns 200 even for business errors (result:false) — only retry transport 404
            if resp.status_code != 404:
                return resp
            logger.warning(f"WATI sendSessionMessage 404 for target={target}; trying next if any")
    return last_resp


def _wati_session_send_message_id(result: dict) -> str:
    """Extract WhatsApp/local message id from v1 sendSessionMessage response."""
    if not isinstance(result, dict):
        return ""
    msg = result.get("message")
    if isinstance(msg, dict):
        for key in ("whatsappMessageId", "localMessageId", "id"):
            val = msg.get(key)
            if val:
                return str(val)
    for key in ("whatsappMessageId", "localMessageId", "message_id", "id"):
        val = result.get(key)
        if val:
            return str(val)
    return ""


def _wati_session_send_ok(resp_status: int, result: dict) -> bool:
    """True when WATI accepted the session send."""
    if not (200 <= int(resp_status or 0) < 300):
        return False
    if not isinstance(result, dict):
        return False
    if result.get("ok") is True:
        return True
    if result.get("result") in (True, "success"):
        return True
    if result.get("result") is False:
        return False
    # Some tenants only return the message object on success
    return bool(_wati_session_send_message_id(result))


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


async def _wati_send_file_via_url(phone: str, file_url: str, filename: str = "document.pdf"):
    """
    Send a file to an active session.
    Prefer WATI v1 sendSessionFile (multipart). v3 fileViaUrl 404s on this tenant.
    """
    if not file_url:
        return None
    filename = (filename or "document.pdf").strip() or "document.pdf"
    last_resp = None
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            file_resp = await client.get(file_url, timeout=60.0)
            if file_resp.status_code >= 400:
                logger.warning(
                    f"Brochure download failed {file_resp.status_code} for {file_url}"
                )
                return file_resp
            content = file_resp.content
            content_type = file_resp.headers.get("content-type") or "application/pdf"

            for target in _wati_session_targets(phone):
                resp = await client.post(
                    f"{WATI_API_ENDPOINT}/api/v1/sendSessionFile/{target}",
                    headers={"Authorization": f"Bearer {WATI_API_TOKEN}"},
                    params={"caption": filename},
                    files={"file": (filename, content, content_type)},
                    timeout=60.0,
                )
                last_resp = resp
                if resp.status_code != 404:
                    return resp
                logger.warning(
                    f"WATI sendSessionFile 404 for target={target}; trying next if any"
                )
    except Exception as e:
        logger.error(f"WATI sendSessionFile error for {phone}: {e}")
        return last_resp
    return last_resp


async def _wati_get_history(phone: str, page_size: int = 50, max_pages: int = 5) -> list:
    """
    Fetch message history from WATI v1 getMessages (paginated).
    Pulls multiple pages so older WhatsApp messages are not stuck on page 1 only.
    Soft-fails to [] on any error.
    """
    page_size = max(1, min(int(page_size or 50), 100))
    max_pages = max(1, min(int(max_pages or 5), 10))
    mapped = []
    seen_ids = set()

    try:
        async with httpx.AsyncClient() as client:
            for page in range(1, max_pages + 1):
                resp = await client.get(
                    f"{WATI_API_ENDPOINT}/api/v1/getMessages/{phone}",
                    params={"pageNumber": page, "pageSize": page_size},
                    headers=_wati_headers(),
                    timeout=30.0,
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"WATI get history {phone} page {page} returned {resp.status_code}"
                    )
                    break

                data = resp.json()
                raw_messages = []
                if isinstance(data, dict):
                    msgs = data.get("messages")
                    if isinstance(msgs, dict):
                        raw_messages = msgs.get("items", []) or []
                    elif isinstance(msgs, list):
                        raw_messages = msgs

                if not raw_messages:
                    break

                page_added = 0
                for m in raw_messages:
                    if not isinstance(m, dict):
                        continue
                    # Skip ticket lifecycle noise (not real WhatsApp bubbles)
                    if _is_wati_system_event(m):
                        continue
                    doc = _normalize_wati_message(m, phone=phone)
                    wid = doc.get("wati_message_id")
                    if wid and wid in seen_ids:
                        continue
                    if wid:
                        seen_ids.add(wid)
                    mapped.append(doc)
                    page_added += 1

                # Advance while WATI still returns a full page (skip filters shrink page_added)
                if len(raw_messages) < page_size:
                    break

        return mapped
    except Exception as e:
        logger.warning(f"WATI get history soft-fail for {phone}: {e}")
        return mapped


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
                pdf_url, pdf_name = _pdf_from_template_params(params)
                msg_doc = {
                    "id": str(uuid.uuid4()),
                    "wati_message_id": wati_msg_id or None,
                    "gupshup_message_id": None,
                    "direction": "outbound",
                    "destination": phone,
                    "message_type": "template",
                    "content": _outbound_template_content(message.template_name, params),
                    "template_name": message.template_name,
                    "status": "submitted",
                    "sent_by": current_user["id"],
                    "sent_by_user_id": current_user["id"],
                    "created_at": now_iso,
                    "created_at_dt": now_dt,
                }
                if pdf_url:
                    msg_doc["media_url"] = pdf_url
                if pdf_name:
                    msg_doc["media_filename"] = pdf_name
                    msg_doc["message_type"] = "document"
                await _upsert_whatsapp_message(msg_doc)
                return {
                    "success": True,
                    "status": "submitted",
                    "message_id": wati_msg_id,
                    "destination": phone,
                }
            else:
                err = _friendly_wati_send_error(resp.status_code, result, kind="template")
                logger.error(f"WATI sendTemplate failed {phone}: {resp.status_code} {resp.text[:500]}")
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
        if resp is None:
            return {
                "success": False,
                "error": "Message text is required for session messages",
            }
        try:
            result = resp.json()
        except Exception:
            result = {"raw": getattr(resp, "text", "")}

        if _wati_session_send_ok(resp.status_code, result if isinstance(result, dict) else {}):
            msg_obj = result.get("message") if isinstance(result, dict) else {}
            if not isinstance(msg_obj, dict):
                msg_obj = {}
            wati_msg_id = _wati_session_send_message_id(result if isinstance(result, dict) else {})
            local_id = msg_obj.get("localMessageId")
            status_val = (
                msg_obj.get("statusString")
                or msg_obj.get("status")
                or result.get("status")
                or "sent"
            )
            if isinstance(status_val, str):
                status_val = status_val.lower()
            else:
                status_val = "sent"
            msg_doc = {
                "id": str(uuid.uuid4()),
                "wati_message_id": wati_msg_id or None,
                "gupshup_message_id": None,
                "direction": "outbound",
                "destination": phone,
                "message_type": "text",
                "content": message.text,
                "status": status_val,
                "sent_by": current_user["id"],
                "sent_by_user_id": current_user["id"],
                "created_at": now_iso,
                "created_at_dt": now_dt,
            }
            if local_id and str(local_id) != str(wati_msg_id or ""):
                msg_doc["wati_local_id"] = str(local_id)
            await _upsert_whatsapp_message(msg_doc)
            return {
                "success": True,
                "status": status_val,
                "message_id": wati_msg_id,
                "destination": phone,
            }
        else:
            info = ""
            if isinstance(result, dict):
                info = result.get("info") or result.get("error") or result.get("message") or ""
                if isinstance(info, dict):
                    info = info.get("message") or str(info)
            err = _friendly_wati_send_error(
                resp.status_code,
                {"error": info} if info else result,
                kind="message",
            )
            logger.error(f"WATI sendSessionMessage failed {phone}: {resp.status_code} {getattr(resp, 'text', '')[:300]}")
            return {"success": False, "error": err, "status_code": resp.status_code}

    except Exception as e:
        logger.error(f"WATI send error for {phone}: {e}")
        return {"success": False, "error": f"WhatsApp send failed: {str(e)}"}


# ═══════════════════════════════════════════════════════════════════════════════
# WATI webhook handlers
# ═══════════════════════════════════════════════════════════════════════════════

ADMIN_WA_ASSIGNEE_NAME = "Admin"
ADMIN_WA_ASSIGNEE_EMAIL = "roshni@arihantspaces.com"


async def resolve_admin_wa_assignee() -> Optional[dict]:
    """Resolve Admin user for WhatsApp unknown-lead assignment (full_name == Admin)."""
    admin = await db.users.find_one(
        {"full_name": ADMIN_WA_ASSIGNEE_NAME},
        {"_id": 0, "id": 1, "full_name": 1, "email": 1},
    )
    if admin and admin.get("id"):
        return admin
    admin = await db.users.find_one(
        {"email": {"$regex": f"^{re.escape(ADMIN_WA_ASSIGNEE_EMAIL)}$", "$options": "i"}},
        {"_id": 0, "id": 1, "full_name": 1, "email": 1},
    )
    return admin if admin and admin.get("id") else None


def _split_sender_name(sender_name: str, phone: str) -> tuple[str, str]:
    name = (sender_name or "").strip()
    if not name:
        last4 = (phone or "")[-4:] or "????"
        return f"WhatsApp {last4}", ""
    parts = name.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


async def create_whatsapp_unknown_lead(
    phone: str,
    sender_name: str = "",
    *,
    backfill: bool = False,
    notify: bool = True,
) -> Optional[dict]:
    """
    Create a New lead for an unknown WhatsApp inbound, assigned to Admin.
    Returns the lead dict, or None if phone invalid / create skipped.
    """
    from pymongo.errors import DuplicateKeyError
    from crm.services.nurture_temperature import apply_nurture_temperature_rules
    from crm.utils.helpers import determine_lead_intent, is_vip_lead

    normalized = normalize_phone(phone)
    if not normalized or len(normalized) != 10:
        logger.warning("WA unknown lead skipped — invalid phone=%r normalized=%r", phone, normalized)
        return None

    existing = await db.leads.find_one({"normalized_phone": normalized}, {"_id": 0})
    if existing:
        return existing

    admin = await resolve_admin_wa_assignee()
    first_name, last_name = _split_sender_name(sender_name, normalized)
    lead_id = str(uuid.uuid4())
    now_dt = utc_now()
    now_iso = iso_utc_now()
    created_desc = (
        "Lead backfilled from existing WhatsApp conversation (WATI)"
        if backfill
        else "Lead created from WhatsApp inbound (WATI)"
    )
    assigned_desc = (
        "Assigned to Admin from WhatsApp backfill (WATI)"
        if backfill
        else "Assigned to Admin from WhatsApp inbound (WATI)"
    )
    context_updates = [
        {
            "type": "created",
            "timestamp": now_iso,
            "timestamp_dt": now_dt,
            "description": created_desc,
            "agent": "WATI",
            "actor_user_id": "system-wati",
            "actor_name": "WATI",
        }
    ]
    lead_dict = {
        "id": lead_id,
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone if str(phone).startswith("+") else normalized,
        "normalized_phone": normalized,
        "lead_status": "New",
        "lead_source": "WhatsApp",
        "original_source": "WhatsApp",
        "most_recent_source": "WhatsApp",
        "site_visit_count": 0,
        "assigned_to": None,
        "assigned_to_name": None,
        "assigned_user_id": None,
        "presales_agent": None,
        "whatsapp_replied": True,
        "context_updates": context_updates,
        "created_at": now_iso,
        "created_at_dt": now_dt,
        "updated_at": now_iso,
        "updated_at_dt": now_dt,
    }
    if admin:
        admin_name = admin.get("full_name") or ADMIN_WA_ASSIGNEE_NAME
        lead_dict["assigned_to"] = admin_name
        lead_dict["assigned_to_name"] = admin_name
        lead_dict["assigned_user_id"] = admin["id"]
        lead_dict["presales_agent"] = admin_name
        lead_dict["assigned_at"] = now_iso
        lead_dict["assigned_at_dt"] = now_dt
        context_updates.append(
            {
                "type": "assigned",
                "timestamp": now_iso,
                "timestamp_dt": now_dt,
                "description": assigned_desc,
                "agent": "WATI",
                "actor_user_id": "system-wati",
                "actor_name": "WATI",
            }
        )
    else:
        logger.warning("WA unknown lead: Admin user not found; creating unassigned lead phone=%s", normalized)

    temp_patch = {"lead_status": "New"}
    apply_nurture_temperature_rules({}, temp_patch, is_create=True)
    lead_dict["temperature"] = temp_patch.get("temperature")
    lead_dict["intent"] = determine_lead_intent(lead_dict)
    lead_dict["vip"] = is_vip_lead(lead_dict)

    try:
        await db.leads.insert_one(lead_dict)
    except DuplicateKeyError:
        existing = await db.leads.find_one({"normalized_phone": normalized}, {"_id": 0})
        return existing

    if notify and admin and admin.get("id"):
        lead_name = f"{first_name} {last_name}".strip() or first_name
        try:
            await create_notification(
                recipient_user_id=admin["id"],
                recipient_name=admin.get("full_name") or ADMIN_WA_ASSIGNEE_NAME,
                title="New Lead Assigned",
                message=f"{lead_name} created from WhatsApp inbound (WATI)",
                notification_type="new_lead_assigned",
                lead_id=lead_id,
                lead_name=lead_name,
                severity="high",
                urgency="action_needed",
                dedupe_key=f"wa_unknown_create:{lead_id}",
            )
        except Exception as e:
            logger.warning("WA unknown lead notify failed lead=%s: %s", lead_id, e)

    return lead_dict


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
            sender_name = body.get("senderName", "")
            msg_doc = _normalize_wati_message(body, phone=wa_id)
            msg_doc["wati_message_id"] = wati_msg_id or msg_doc.get("wati_message_id")
            msg_doc["sender_name"] = sender_name or msg_doc.get("sender_name") or ""
            msg_doc["status"] = "received"
            msg_doc["raw_payload"] = body
            # Prefer webhook receive time when WATI created stamp is missing/odd
            if not body.get("created"):
                msg_doc["created_at"] = iso_utc_now()
                msg_doc["created_at_dt"] = utc_now()

            await _upsert_whatsapp_message(msg_doc)
            text = msg_doc.get("content") or ""
            logger.info(f"WATI inbound stored from {wa_id}: {text[:80]}")

            # Push to lead timeline (no lead_status change — per plan)
            normalized = normalize_phone(wa_id)
            lead = None
            created_from_wa = False
            if normalized and len(normalized) == 10:
                lead = await db.leads.find_one({"normalized_phone": normalized}, {"_id": 0})
                if not lead:
                    lead = await create_whatsapp_unknown_lead(
                        wa_id or normalized,
                        sender_name,
                        backfill=False,
                        notify=True,
                    )
                    created_from_wa = bool(lead)
            if lead:
                now_iso = msg_doc.get("created_at") or iso_utc_now()
                now_dt = msg_doc.get("created_at_dt") or utc_now()
                context_update = {
                    "type": "whatsapp",
                    "timestamp": now_iso,
                    "timestamp_dt": now_dt,
                    "description": f"Incoming WhatsApp: {text[:100]}",
                    "agent": sender_name or "Customer",
                    "direction": "inbound",
                }
                set_fields = {"updated_at": now_iso, "updated_at_dt": now_dt, "whatsapp_replied": True}
                await db.leads.update_one(
                    {"id": lead["id"]},
                    {"$push": {"context_updates": context_update}, "$set": set_fields},
                )
                from crm.services.ai_lead_regen import enqueue_lead_ai_refresh

                enqueue_lead_ai_refresh(lead["id"])

                # Skip reply notify on the same inbound that auto-created the lead (one bell only)
                if created_from_wa:
                    return

                # Notify assigned rep of inbound WhatsApp reply (deduped by WATI message id)
                try:
                    assignee_id = (lead.get("assigned_user_id") or "").strip()
                    assignee_name = (
                        lead.get("assigned_to")
                        or lead.get("assigned_to_name")
                        or ""
                    ).strip()
                    if not assignee_id and assignee_name:
                        assignee_id = (await resolve_user_id_by_full_name(assignee_name) or "").strip()
                    if assignee_id:
                        lead_name = (
                            f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
                            or lead.get("name")
                            or "Lead"
                        )
                        msg_key = wati_msg_id or msg_doc.get("wati_message_id") or msg_doc.get("id") or ""
                        await create_notification(
                            recipient_user_id=assignee_id,
                            recipient_name=assignee_name,
                            title="WhatsApp reply",
                            message=f"{lead_name} replied on WhatsApp",
                            notification_type="whatsapp_reply",
                            lead_id=lead["id"],
                            lead_name=lead_name,
                            severity="medium",
                            urgency="action_needed",
                            dedupe_key=f"whatsapp_reply:{msg_key}" if msg_key else None,
                        )
                except Exception as notif_err:
                    logger.warning(f"WhatsApp reply notification failed for lead {lead.get('id')}: {notif_err}")

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
        from crm.services.ai_lead_regen import enqueue_lead_ai_refresh
        from crm.services.lead_follow_up import clear_missed_follow_up_after_activity
        from crm.services.lead_overview_service import ist_day_window

        enqueue_lead_ai_refresh(lead_id)
        try:
            today_str, _, _ = ist_day_window()
            await clear_missed_follow_up_after_activity(
                lead_id,
                today_str=today_str,
                actor_name=current_user.get("full_name") or "User",
            )
        except Exception as clear_err:
            logger.warning(
                "clear_missed_follow_up after WhatsApp send failed for %s: %s",
                lead_id,
                clear_err,
            )

    return result


async def get_chat_history(phone: str, limit: int = 50) -> dict:
    """
    Return chat history for a phone number from Mongo only (DB-first).
    Use sync_lead_chat_history / sync_chat_history to pull gaps from WATI.
    """
    normalized = _wati_phone(phone) if WHATSAPP_PROVIDER == "wati" else format_phone_for_gupshup(phone)

    db_messages = (
        await db.whatsapp_messages.find(
            {"$or": [{"destination": normalized}, {"source": normalized}]},
            {"_id": 0},
        )
        .sort("created_at", -1)
        .limit(limit)
        .to_list(limit)
    )

    db_messages.sort(key=_message_sort_ts, reverse=True)
    sliced = _decorate_history_messages(db_messages[:limit])
    session_open = await _is_session_open(normalized)
    return {
        "phone": normalized,
        "messages": sliced,
        "count": len(sliced),
        "session_open": session_open,
    }


async def sync_chat_history(phone: str, limit: int = 100) -> dict:
    """
    Pull live WATI messages (paginated), upsert by wati_message_id, return DB history.
    Used to gap-fill older WhatsApp messages into Mongo — idempotent, never deletes.
    """
    normalized = _wati_phone(phone) if WHATSAPP_PROVIDER == "wati" else format_phone_for_gupshup(phone)
    synced = 0
    # Fetch enough WATI pages to cover older conversation history
    page_size = 50
    max_pages = max(3, min(8, (int(limit or 100) + page_size - 1) // page_size))

    if WHATSAPP_PROVIDER == "wati":
        live_messages = await _wati_get_history(
            normalized, page_size=page_size, max_pages=max_pages
        )
        for doc in live_messages:
            if not doc.get("wati_message_id"):
                continue
            if doc.get("direction") == "inbound":
                doc["source"] = normalized
            else:
                doc["destination"] = normalized
            await _upsert_whatsapp_message(doc)
            synced += 1

        collapsed = await _collapse_near_duplicate_messages(normalized)
        if collapsed:
            logger.info(f"Collapsed {collapsed} duplicate WhatsApp rows for {normalized}")

    history = await get_chat_history(normalized, limit=limit)
    history["synced"] = synced
    return history


async def get_lead_chat_history(lead_id: str) -> dict:
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    phone = lead.get("phone", "")
    if not phone:
        return {"messages": [], "error": "Lead has no phone number", "session_open": False}

    return await get_chat_history(phone)


async def sync_lead_chat_history(lead_id: str) -> dict:
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    phone = lead.get("phone", "")
    if not phone:
        return {"messages": [], "error": "Lead has no phone number", "synced": 0}

    return await sync_chat_history(phone)


def _inbox_peer_phone(raw: str) -> str:
    """Normalize customer phone for inbox join (WATI digits with country code)."""
    if not raw:
        return ""
    if WHATSAPP_PROVIDER == "wati":
        return _wati_phone(str(raw))
    return format_phone_for_gupshup(str(raw))


def _lead_display_name(lead: dict) -> str:
    first = (lead.get("first_name") or "").strip()
    last = (lead.get("last_name") or "").strip()
    name = f"{first} {last}".strip()
    if name:
        return name
    return (lead.get("name") or lead.get("phone") or "Unknown").strip()


def _inbox_preview_text(msg: dict, max_len: int = 120) -> str:
    if not isinstance(msg, dict):
        return ""
    raw = msg.get("reply_label") or msg.get("content") or ""
    text = _humanize_stored_content(raw)
    text = " ".join(str(text).split())
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def _inbox_conversation_key(*, lead_id: str | None, peer: str) -> str:
    if lead_id:
        return f"lead:{lead_id}"
    return f"peer:{peer}"


def _is_mine_lead(lead: dict, current_user: dict) -> bool:
    """True if lead is assigned to the current user (id or name)."""
    if not lead:
        return False
    uid = current_user.get("id") or ""
    name = (current_user.get("full_name") or "").strip().lower()
    if uid and lead.get("assigned_user_id") == uid:
        return True
    if name:
        for field in ("assigned_to_name", "assigned_to", "presales_agent"):
            if (lead.get(field) or "").strip().lower() == name:
                return True
    return False


def _inbox_our_channel_phones() -> set[str]:
    phones: set[str] = set()
    if WATI_CHANNEL_PHONE:
        try:
            peer = _inbox_peer_phone(WATI_CHANNEL_PHONE)
            if peer:
                phones.add(peer)
        except Exception:
            pass
    return phones


async def _inbox_lead_scope_filter(current_user: dict) -> dict:
    """
    Leads visible in WhatsApp inbox.
    Admin/manager: org-wide. Rep: owned leads OR leads with a task assigned to them.
    View grants are intentionally excluded from the list (ephemeral).
    """
    if current_user.get("role") in ("admin", "manager"):
        return {}
    uid = current_user.get("id") or ""
    name = current_user.get("full_name") or ""
    owned = rep_lead_filter(uid, name)
    task_filter = task_assignee_clause(uid, name)
    lead_ids: list[str] = []
    cursor = db.tasks.find(task_filter, {"_id": 0, "lead_id": 1})
    async for t in cursor:
        lid = t.get("lead_id")
        if lid and lid not in lead_ids:
            lead_ids.append(lid)
    if lead_ids:
        return {"$or": [owned, {"id": {"$in": lead_ids}}]}
    return owned


async def _inbox_aggregate_peers(cap: int = _INBOX_PEER_CANDIDATE_CAP) -> list[tuple[str, dict]]:
    """
    Distinct customer peers from whatsapp_messages with their latest message.
    Newest-first; capped for CRM scale.
    """
    our = list(_inbox_our_channel_phones())
    pipeline: list[dict] = [
        {
            "$addFields": {
                "_peer": {
                    "$cond": [
                        {"$eq": ["$direction", "inbound"]},
                        "$source",
                        "$destination",
                    ]
                },
                "_sort_dt": {"$ifNull": ["$created_at_dt", "$created_at"]},
            }
        },
        {
            "$match": {
                "_peer": {"$nin": [None, "", *our]},
            }
        },
        {"$sort": {"_sort_dt": -1}},
        {
            "$group": {
                "_id": "$_peer",
                "last": {"$first": "$$ROOT"},
                "inbound_count": {
                    "$sum": {"$cond": [{"$eq": ["$direction", "inbound"]}, 1, 0]}
                },
                "outbound_count": {
                    "$sum": {"$cond": [{"$eq": ["$direction", "outbound"]}, 1, 0]}
                },
            }
        },
        {"$sort": {"last._sort_dt": -1}},
        {"$limit": cap},
    ]

    out: list[tuple[str, dict]] = []
    async for row in db.whatsapp_messages.aggregate(pipeline):
        peer = row.get("_id")
        last = row.get("last") or {}
        if peer and isinstance(last, dict):
            last = dict(last)
            last["_has_customer_reply"] = int(row.get("inbound_count") or 0) > 0
            last["_has_outbound"] = int(row.get("outbound_count") or 0) > 0
            out.append((str(peer), last))
    return out


async def _resolve_leads_for_peers(peers: list[str]) -> dict[str, dict]:
    """Map WATI peer phone → lead (first wins on duplicate phones)."""
    if not peers:
        return {}
    norms = list({n for p in peers if (n := normalize_phone(p))})
    projection = {
        "_id": 0,
        "id": 1,
        "first_name": 1,
        "last_name": 1,
        "name": 1,
        "phone": 1,
        "normalized_phone": 1,
        "project": 1,
        "assigned_to": 1,
        "assigned_to_name": 1,
        "assigned_user_id": 1,
        "presales_agent": 1,
        "lead_status": 1,
        "status": 1,
        "pipeline_status": 1,
        "budget": 1,
        "configuration": 1,
        "whatsapp_replied": 1,
    }
    or_clauses: list[dict] = []
    if norms:
        or_clauses.append({"normalized_phone": {"$in": norms}})
    or_clauses.append({"phone": {"$in": peers}})
    leads = await db.leads.find({"$or": or_clauses}, projection).to_list(max(2000, len(peers) * 3))

    phone_to_lead: dict[str, dict] = {}
    peer_set = set(peers)
    for lead in leads:
        peer = _inbox_peer_phone(lead.get("phone") or lead.get("normalized_phone") or "")
        if peer and peer in peer_set and peer not in phone_to_lead:
            phone_to_lead[peer] = lead
            continue
        lead_norm = lead.get("normalized_phone") or normalize_phone(lead.get("phone") or "")
        if not lead_norm:
            continue
        for p in peers:
            if p in phone_to_lead:
                continue
            if normalize_phone(p) == lead_norm:
                phone_to_lead[p] = lead
    return phone_to_lead


async def _inbox_in_scope_lead_ids(lead_ids: list[str], scope: dict) -> set[str]:
    if not lead_ids:
        return set()
    if not scope:
        return set(lead_ids)
    query = {"$and": [scope, {"id": {"$in": lead_ids}}]}
    found: set[str] = set()
    async for doc in db.leads.find(query, {"_id": 0, "id": 1}):
        lid = doc.get("id")
        if lid:
            found.add(lid)
    return found


async def _inbox_unread_counts(
    user_id: str, peers: list[str]
) -> dict[str, int]:
    """Count inbound messages per peer newer than the user's last_read_at."""
    if not peers or not user_id:
        return {p: 0 for p in peers}

    reads: dict[str, datetime] = {}
    cursor = db.whatsapp_thread_reads.find(
        {"user_id": user_id, "peer_phone": {"$in": peers}},
        {"_id": 0, "peer_phone": 1, "last_read_at": 1},
    )
    async for row in cursor:
        peer = row.get("peer_phone")
        ts = coerce_datetime(row.get("last_read_at"))
        if peer and ts:
            reads[str(peer)] = ts

    counts: dict[str, int] = {p: 0 for p in peers}
    async for msg in db.whatsapp_messages.find(
        {"direction": "inbound", "source": {"$in": peers}},
        {"_id": 0, "source": 1, "created_at_dt": 1, "created_at": 1},
    ):
        peer = str(msg.get("source") or "")
        if peer not in counts:
            continue
        msg_dt = coerce_datetime(msg.get("created_at_dt") or msg.get("created_at"))
        last_read = reads.get(peer)
        if last_read is None or (msg_dt and msg_dt > last_read):
            counts[peer] += 1
    return counts


async def mark_whatsapp_inbox_read(
    current_user: dict,
    *,
    peer_phone: str | None = None,
    lead_id: str | None = None,
) -> dict:
    """Upsert last_read_at for the current user on a WA peer thread."""
    peer = _inbox_peer_phone(peer_phone or "")
    if not peer and lead_id:
        lead = await db.leads.find_one({"id": lead_id}, {"_id": 0, "phone": 1, "normalized_phone": 1})
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        peer = _inbox_peer_phone(lead.get("phone") or lead.get("normalized_phone") or "")
    if not peer:
        raise HTTPException(status_code=400, detail="peer_phone or lead_id with phone required")

    uid = current_user.get("id") or ""
    if not uid:
        raise HTTPException(status_code=401, detail="Unauthorized")

    now = utc_now()
    await db.whatsapp_thread_reads.update_one(
        {"user_id": uid, "peer_phone": peer},
        {
            "$set": {
                "user_id": uid,
                "peer_phone": peer,
                "last_read_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return {
        "success": True,
        "peer_phone": peer,
        "last_read_at": now.isoformat(),
    }


async def get_whatsapp_inbox(
    current_user: dict,
    *,
    limit: int = _INBOX_DEFAULT_LIMIT,
    skip: int = 0,
    filter_mode: str = "all",
    q: str | None = None,
) -> dict:
    """
    Peer-first WhatsApp conversation list for the Team Inbox.

    Starts from whatsapp_messages peers, left-joins CRM leads.
    Unmatched numbers appear as Unknown. Matched leads respect assignee scope
    for reps; unmatched threads are always team-visible.
    """
    try:
        limit = max(1, min(int(limit or _INBOX_DEFAULT_LIMIT), _INBOX_MAX_LIMIT))
    except (TypeError, ValueError):
        limit = _INBOX_DEFAULT_LIMIT
    try:
        skip = max(0, int(skip or 0))
    except (TypeError, ValueError):
        skip = 0

    mode = (filter_mode or "all").strip().lower()
    if mode not in _INBOX_FILTERS:
        mode = "all"
    query_text = (q or "").strip().lower()

    peer_rows = await _inbox_aggregate_peers(_INBOX_PEER_CANDIDATE_CAP)
    if not peer_rows:
        return {
            "conversations": [],
            "count": 0,
            "limit": limit,
            "skip": skip,
            "has_more": False,
            "filter": mode,
        }

    peers = [p for p, _ in peer_rows]
    phone_to_lead = await _resolve_leads_for_peers(peers)
    scope = await _inbox_lead_scope_filter(current_user)
    matched_ids = [lead["id"] for lead in phone_to_lead.values() if lead.get("id")]
    in_scope_ids = await _inbox_in_scope_lead_ids(matched_ids, scope)
    uid = current_user.get("id") or ""
    unread_map = await _inbox_unread_counts(uid, peers)

    rows: list[dict] = []
    for peer, last in peer_rows:
        lead = phone_to_lead.get(peer)
        is_unmatched = lead is None
        if lead and lead.get("id") not in in_scope_ids:
            # Rep cannot see other reps' matched threads
            continue

        if mode == "mine" and (is_unmatched or not _is_mine_lead(lead or {}, current_user)):
            continue

        unread = int(unread_map.get(peer) or 0)
        if mode == "unread" and unread <= 0:
            continue

        last_at = last.get("created_at") or last.get("created_at_dt")
        if hasattr(last_at, "isoformat"):
            last_at = last_at.isoformat()
        preview = _inbox_preview_text(last)
        display_name = _lead_display_name(lead) if lead else "Unknown"
        phone_display = (lead.get("phone") if lead else None) or peer
        project = lead.get("project") if lead else None

        if query_text:
            hay = f"{display_name} {phone_display} {project or ''} {preview}".lower()
            if query_text not in hay:
                continue

        lead_id = lead.get("id") if lead else None
        session_open = False
        # Session is computed for the page after filter; mark None here and fill for page slice.
        rows.append(
            {
                "conversation_key": _inbox_conversation_key(lead_id=lead_id, peer=peer),
                "lead_id": lead_id,
                "is_unmatched": is_unmatched,
                "peer_phone": peer,
                "display_name": display_name,
                "phone": phone_display,
                "normalized_phone": (
                    (lead.get("normalized_phone") if lead else None) or normalize_phone(peer)
                ),
                "project": project,
                "assigned_to": lead.get("assigned_to") if lead else None,
                "assigned_to_name": lead.get("assigned_to_name") if lead else None,
                "assigned_user_id": lead.get("assigned_user_id") if lead else None,
                "status": (
                    (lead.get("lead_status") or lead.get("status") or lead.get("pipeline_status"))
                    if lead
                    else None
                ),
                "budget": lead.get("budget") if lead else None,
                "configuration": lead.get("configuration") if lead else None,
                "last_message_preview": preview,
                "last_message_at": last_at,
                "last_direction": last.get("direction"),
                "last_message_type": last.get("message_type"),
                "unread_count": unread,
                "has_customer_reply": bool(
                    last.get("_has_customer_reply")
                    or (lead or {}).get("whatsapp_replied")
                    or last.get("direction") == "inbound"
                ),
                "whatsapp_replied": bool((lead or {}).get("whatsapp_replied")),
                "session_open": session_open,
            }
        )

    total = len(rows)
    page = rows[skip : skip + limit]
    # Cheap session flags for visible page only
    for row in page:
        try:
            row["session_open"] = await _is_session_open(row["peer_phone"])
        except Exception:
            row["session_open"] = False

    return {
        "conversations": page,
        "count": total,
        "limit": limit,
        "skip": skip,
        "has_more": skip + limit < total,
        "filter": mode,
    }


_DASHBOARD_WA_LIST_CAP = 100
_DASHBOARD_WA_FILTERS = frozenset({
    "all",
    "needs_followup",
    "not_contacted",
    "replied",
    "unread_mine",
    "awaiting_agent_reply",
    "customer_replied_today",
})


async def _peers_inbound_today(peers: list[str], day_start, day_end) -> set[str]:
    """Peer phones that received at least one inbound message in the IST day window."""
    if not peers:
        return set()
    found: set[str] = set()
    cursor = db.whatsapp_messages.find(
        {
            "direction": "inbound",
            "source": {"$in": peers},
            "created_at_dt": {"$gte": day_start, "$lt": day_end},
        },
        {"_id": 0, "source": 1},
    )
    async for msg in cursor:
        peer = msg.get("source")
        if peer:
            found.add(str(peer))
    return found


async def _count_inbound_today(peers: list[str], day_start, day_end) -> int:
    """Count inbound messages for peers in the IST day window."""
    if not peers:
        return 0
    return int(
        await db.whatsapp_messages.count_documents(
            {
                "direction": "inbound",
                "source": {"$in": peers},
                "created_at_dt": {"$gte": day_start, "$lt": day_end},
            }
        )
    )


async def get_my_dashboard_whatsapp(
    *,
    subject_id: str,
    subject_name: str,
    org_wide: bool,
    filter_mode: str = "all",
) -> dict:
    """
    My Dashboard WhatsApp health (tiles A) + conversation pipeline list (C).

    Reuses peer aggregation + lead join from Team Inbox. No live WATI calls.
    - org_wide=False: subject’s assigned leads only (rep_lead_filter).
    - org_wide=True: all matched leads; unread_mine still uses subject_id (viewer).
    Only threads with a matched lead are included.
    """
    mode = (filter_mode or "all").strip().lower()
    if mode not in _DASHBOARD_WA_FILTERS:
        mode = "all"

    from crm.services.lead_overview_service import ist_day_window

    _, day_start, day_end = ist_day_window()

    peer_rows = await _inbox_aggregate_peers(_INBOX_PEER_CANDIDATE_CAP)
    empty = {
        "tiles": {
            "unread_mine": 0,
            "awaiting_agent_reply": 0,
            "customer_replied_today": 0,
        },
        "conversations": [],
        "count": 0,
        "filter": mode,
        "org_wide": org_wide,
    }
    if not peer_rows:
        return empty

    peers = [p for p, _ in peer_rows]
    phone_to_lead = await _resolve_leads_for_peers(peers)
    scope = {} if org_wide else rep_lead_filter(subject_id, subject_name)
    matched_ids = [lead["id"] for lead in phone_to_lead.values() if lead.get("id")]
    in_scope_ids = await _inbox_in_scope_lead_ids(matched_ids, scope)
    unread_map = await _inbox_unread_counts(subject_id, peers)

    scoped: list[tuple[str, dict, dict]] = []
    for peer, last in peer_rows:
        lead = phone_to_lead.get(peer)
        if not lead or not lead.get("id") or lead["id"] not in in_scope_ids:
            continue
        scoped.append((peer, last, lead))

    scoped_peers = [p for p, _, _ in scoped]
    inbound_today_peers = await _peers_inbound_today(scoped_peers, day_start, day_end)
    customer_replied_today = await _count_inbound_today(scoped_peers, day_start, day_end)

    unread_mine = 0
    awaiting_agent_reply = 0
    for peer, last, _lead in scoped:
        unread = int(unread_map.get(peer) or 0)
        if unread > 0:
            unread_mine += 1
        if last.get("direction") == "inbound":
            awaiting_agent_reply += 1

    tiles = {
        "unread_mine": unread_mine,
        "awaiting_agent_reply": awaiting_agent_reply,
        "customer_replied_today": customer_replied_today,
    }

    rows: list[dict] = []
    for peer, last, lead in scoped:
        unread = int(unread_map.get(peer) or 0)
        has_customer_reply = bool(
            last.get("_has_customer_reply")
            or lead.get("whatsapp_replied")
            or last.get("direction") == "inbound"
        )
        has_outbound = bool(last.get("_has_outbound"))
        last_direction = last.get("direction")

        if mode == "unread_mine" and unread <= 0:
            continue
        if mode in ("awaiting_agent_reply", "needs_followup") and last_direction != "inbound":
            continue
        if mode == "not_contacted" and not (has_customer_reply and not has_outbound):
            continue
        if mode == "replied" and not has_customer_reply:
            continue
        if mode == "customer_replied_today" and peer not in inbound_today_peers:
            continue

        last_at = last.get("created_at") or last.get("created_at_dt")
        if hasattr(last_at, "isoformat"):
            last_at = last_at.isoformat()

        rows.append(
            {
                "lead_id": lead.get("id"),
                "peer_phone": peer,
                "display_name": _lead_display_name(lead),
                "phone": lead.get("phone") or peer,
                "lead_status": (
                    lead.get("lead_status") or lead.get("status") or lead.get("pipeline_status")
                ),
                "last_message_preview": _inbox_preview_text(last),
                "last_message_at": last_at,
                "last_direction": last_direction,
                "unread_count": unread,
                "assigned_to": lead.get("assigned_to"),
                "assigned_to_name": lead.get("assigned_to_name"),
                "assigned_user_id": lead.get("assigned_user_id"),
                "has_customer_reply": has_customer_reply,
            }
        )
        if len(rows) >= _DASHBOARD_WA_LIST_CAP:
            break

    return {
        "tiles": tiles,
        "conversations": rows,
        "count": len(rows),
        "filter": mode,
        "org_wide": org_wide,
    }


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
                {"name": "2", "value": primary_project_label(lead) or "Arihant Spaces"},
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
            {"name": "2", "value": primary_project_label(lead) or "Arihant Spaces"},
            {"name": "3", "value": price_str},
        ]
    )
    return await send_to_lead(lead_id, msg, current_user)


async def send_brochure(lead_id: str, current_user: dict, project: Optional[str] = None) -> dict:
    """
    Template 3: Brochure (arihant_brochure_v1).

    Primary path: template with dynamic {{pdfLink}} header (works with no open session).
    Fallback (session open only): if WATI rejects the media/header params (common 400),
    deliver the correct project PDF via fileViaUrl so live users still get the brochure.

    Optional ``project`` overrides the lead's project when resolving PROJECT_BROCHURE_MAP.
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

    project_override = (project or "").strip()
    if project_override:
        project_key = resolve_lead_project_key({"project": project_override, "project_id": project_override})
    else:
        project_key = resolve_lead_project_key(lead)
    pdf_filename = PROJECT_BROCHURE_MAP.get(project_key)
    if not pdf_filename:
        label = project_override or lead.get("project") or "not set"
        return {"success": False, "error": f"No brochure PDF configured for project: {label}"}

    static_path = Path(__file__).resolve().parents[2] / "static" / pdf_filename
    if not static_path.is_file():
        logger.error(f"Brochure file missing on disk: {static_path}")
        return {"success": False, "error": f"Brochure file missing on server: {pdf_filename}"}

    # WATI dynamic media header: pass the project brochure URL as {{pdfLink}}.
    pdf_url = f"{WATI_BASE_URL}/static/{quote(pdf_filename)}"

    ok, preflight_err = await _preflight_public_url(pdf_url)
    if not ok:
        # Soft fail: many hosts cannot HEAD their own public URL from inside the VPC.
        # Still attempt WATI; surface preflight detail only if the send also fails.
        logger.warning(f"Brochure preflight warning (continuing send): {preflight_err}")

    msg = WhatsAppMessage(
        destination=phone,
        template_name="arihant_brochure_v1",
        template_parameters=[{"name": "pdfLink", "value": pdf_url}],
    )
    result = await send_to_lead(lead_id, msg, current_user)
    if result.get("success"):
        result["filename"] = pdf_filename
        return result

    # Session fallback — only when template media looks rejected and customer window is open.
    # Does not change successful template sends; avoids shipping the wrong fixed-header PDF.
    if _looks_like_media_template_error(result) and await _is_session_open(phone):
        try:
            resp = await _wati_send_file_via_url(phone, pdf_url, pdf_filename)
            try:
                file_result = resp.json()
            except Exception:
                file_result = {"raw": resp.text}

            if 200 <= resp.status_code < 300:
                now_dt = utc_now()
                now_iso = iso_utc_now()
                wati_msg_id = ""
                if isinstance(file_result, dict):
                    wati_msg_id = str(
                        (file_result.get("message") or {}).get("id")
                        or file_result.get("id")
                        or ""
                    )
                await _upsert_whatsapp_message({
                    "id": str(uuid.uuid4()),
                    "wati_message_id": wati_msg_id or None,
                    "gupshup_message_id": None,
                    "direction": "outbound",
                    "destination": phone,
                    "message_type": "document",
                    "content": f"Project brochure: {pdf_filename}",
                    "template_name": "arihant_brochure_v1",
                    "media_url": pdf_url,
                    "media_filename": pdf_filename,
                    "status": "sent",
                    "sent_by": current_user["id"],
                    "sent_by_user_id": current_user["id"],
                    "created_at": now_iso,
                    "created_at_dt": now_dt,
                })
                logger.warning(
                    f"Brochure template failed for {phone}; delivered via fileViaUrl fallback: {pdf_filename}"
                )
                return {
                    "success": True,
                    "status": "sent",
                    "filename": pdf_filename,
                    "delivery": "session_file",
                    "message_id": wati_msg_id,
                    "destination": phone,
                    "note": "Template media send failed; brochure delivered via open WhatsApp session.",
                }

            logger.error(
                f"Brochure fileViaUrl fallback failed {phone}: {resp.status_code} {resp.text[:500]}"
            )
        except Exception as e:
            logger.error(f"Brochure fileViaUrl fallback error for {phone}: {e}")

    # Surface a clearer production hint when public URL / template header is the likely cause
    err = result.get("error") or "Failed to send brochure"
    if _looks_like_media_template_error(result):
        err = (
            f"{err}. Check that arihant_brochure_v1 uses a dynamic document header "
            f"{{{{pdfLink}}}} and that {pdf_url} is publicly reachable by Meta/WATI."
        )
        if not ok and preflight_err:
            err = f"{err} Server preflight: {preflight_err}"
        result = {**result, "error": err, "pdf_url": pdf_url}
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
                        from crm.services.ai_lead_regen import enqueue_lead_ai_refresh

                        enqueue_lead_ai_refresh(lead["id"])

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
                from crm.services.ai_lead_regen import enqueue_lead_ai_refresh

                enqueue_lead_ai_refresh(lead["id"])

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
