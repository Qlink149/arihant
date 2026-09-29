"""Channel Partner lead-submission webhook → CRM leads.

Serves the 3 client-hosted landing pages (cp-leads-r16, cp-leads-melange,
cp-leads-mira). Unlike Webflow/Zapier intake, a phone number that already
exists anywhere in the CRM is REJECTED (409), never merged — see
``lead_intake_service.ingest_lead(duplicate_policy="reject")``.
"""

from __future__ import annotations

import hmac
import re
import unicodedata
import uuid
from typing import Any, Dict, Optional, Tuple

from crm.constants.lead_picklists import CANONICAL_CHANNEL_PARTNERS
from crm.core.state import CHANNEL_PARTNER_WEBHOOK_SECRET, PROJECT_REGISTRY, db, iso_utc_now, logger, utc_now
from crm.services.lead_intake_service import IntakeValidationError, ingest_lead

# Only these 3 forms exist today. Reject (400) anything else rather than
# silently routing a lead to the wrong project pool.
_ALLOWED_PROJECT_IDS = ("reserve-16", "melange", "mira")

# Field IDs are exactly what the client's form-builder sends (see the field
# mapping table: first_name, last_name, email, mob_number, channel_partner,
# project). Extra aliases are defensive, not load-bearing.
_FIRST_NAME_KEYS = ("first_name", "First Name", "firstname", "firstName")
_LAST_NAME_KEYS = ("last_name", "Last Name", "lastname", "lastName")
_EMAIL_KEYS = ("email", "Email", "e-mail", "Email Address")
_PHONE_KEYS = ("mob_number", "Mobile Number", "mobile_number", "mobileNumber", "phone", "Phone")
_CHANNEL_PARTNER_KEYS = ("channel_partner", "Channel Partner", "partner")
_PROJECT_KEYS = ("project", "Project", "Project (Hidden)", "project_name")
_COMMENT_KEYS = ("comments", "Comments", "comment", "message", "msg")

_PROJECT_ALIASES = {
    "annanagarmira": "mira",
    "mira": "mira",
    "ecrreserve16": "reserve-16",
    "reserve16": "reserve-16",
    "reserve-16": "reserve-16",
    "r16": "reserve-16",
    "saligramammelange": "melange",
    "melange": "melange",
    "melangeprojectmelange": "melange",
}


def verify_webhook_secret(token: Optional[str] = None, header_secret: Optional[str] = None) -> bool:
    """Validate shared secret from query ``token`` or ``X-Webhook-Secret``. Fail-closed."""
    expected = (CHANNEL_PARTNER_WEBHOOK_SECRET or "").strip()
    if not expected:
        return False
    for candidate in (token, header_secret):
        if candidate and hmac.compare_digest(expected, str(candidate).strip()):
            return True
    return False


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value)


def _norm_key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _data_lookup(data: Dict[str, Any], candidates: Tuple[str, ...]) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    by_norm = {_norm_key(k): v for k, v in data.items()}
    for key in candidates:
        text = by_norm.get(_norm_key(key))
        if text is not None and str(text).strip():
            return str(text).strip()
    return None


def _project_by_id(project_id: str) -> Optional[Dict[str, str]]:
    for p in PROJECT_REGISTRY:
        if p["id"] == project_id:
            return {"id": p["id"], "name": p["name"]}
    return None


def resolve_channel_partner_project(raw_value: Optional[str]) -> Optional[Dict[str, str]]:
    """Resolve the submitted project string to one of the 3 allowed projects.

    Tolerant of the exact strings the 3 forms send today ("Anna Nagar - Mira",
    "ECR - Reserve16" — no space, "Saligramam Melange") via fold+compact
    matching, so spacing/accent variants collapse to the same key.
    """
    if not raw_value:
        return None
    compact = _compact(_fold(raw_value))
    project_id = _PROJECT_ALIASES.get(compact)
    if not project_id or project_id not in _ALLOWED_PROJECT_IDS:
        return None
    return _project_by_id(project_id)


def resolve_channel_partner_name(raw_value: Optional[str]) -> Tuple[Optional[str], bool]:
    """Match the submitted partner string against the canonical list.

    Returns (stored_value, matched). Never rejects a lead over this — an
    unmatched or blank value is still stored (raw, trimmed) or left None, and
    flagged via ``matched=False`` so ops can clean it up later.
    """
    text = str(raw_value or "").strip()
    if not text:
        return None, False
    key = _norm_key(text)
    for canonical in CANONICAL_CHANNEL_PARTNERS:
        if _norm_key(canonical) == key:
            return canonical, True
    return text, False


def map_channel_partner_data_to_intake(
    data: Dict[str, Any],
    *,
    project: Dict[str, str],
) -> Dict[str, Any]:
    """Map the submitted form fields into the lead_intake body shape.

    Only email/consent/source/meta go through ``data`` — the partner name,
    project, and comment ride on the synthetic ``api_key`` dict built by the
    caller (mirrors how Zapier stashes project_name/form_id there), since
    ``_create_new_lead`` reads them from there, not from the intake body.
    """
    first = _data_lookup(data, _FIRST_NAME_KEYS)
    last = _data_lookup(data, _LAST_NAME_KEYS) or ""
    email = _data_lookup(data, _EMAIL_KEYS)
    phone = _data_lookup(data, _PHONE_KEYS)

    return {
        "first_name": first,
        "last_name": last,
        "email": email,
        "phone": phone,
        "consent": True,
        "source": "channel partner",
    }


async def _write_log(
    *,
    fingerprint: str,
    project_id: Optional[str],
    channel_partner: Optional[str],
    success: bool,
    reason: str,
    lead_id: Optional[str] = None,
    http_status: Optional[int] = None,
) -> None:
    now_iso = iso_utc_now()
    now_dt = utc_now()
    try:
        await db.channel_partner_leads_logs.insert_one(
            {
                "id": str(uuid.uuid4()),
                "fingerprint": fingerprint,
                "project_id": project_id,
                "channel_partner": channel_partner,
                "success": success,
                "reason": (reason or "")[:300],
                "lead_id": lead_id,
                "http_status": http_status,
                "created_at": now_iso,
                "created_at_dt": now_dt,
            }
        )
    except Exception as e:
        logger.error("channel_partner_leads_logs insert failed: %s", e)


async def process_channel_partner_submission(body: dict, *, ip: Optional[str] = None) -> Tuple[Dict[str, Any], int]:
    """Process one Channel Partner form submission. Returns (response_dict, http_status).

    Unlike the Webflow/Zapier webhooks, real HTTP status codes are returned —
    these are the client's own forms and should surface validation/duplicate
    errors to the visitor, not silently swallow them.
    """
    data = body if isinstance(body, dict) else {}

    raw_project = _data_lookup(data, _PROJECT_KEYS)
    project = resolve_channel_partner_project(raw_project)
    if not project:
        await _write_log(
            fingerprint=str(raw_project or ""),
            project_id=None,
            channel_partner=None,
            success=False,
            reason="unknown_project",
            http_status=400,
        )
        return {
            "status": "error",
            "reason": "unknown_project",
            "message": "Submitted project is not one of the recognized Channel Partner forms.",
        }, 400

    first_name = _data_lookup(data, _FIRST_NAME_KEYS)
    phone = _data_lookup(data, _PHONE_KEYS)
    email = _data_lookup(data, _EMAIL_KEYS)

    if not first_name:
        await _write_log(
            fingerprint="", project_id=project["id"], channel_partner=None,
            success=False, reason="missing_first_name", http_status=400,
        )
        return {
            "status": "error",
            "reason": "missing_required_field",
            "message": "First name is required.",
        }, 400

    if not phone:
        await _write_log(
            fingerprint="", project_id=project["id"], channel_partner=None,
            success=False, reason="missing_phone", http_status=400,
        )
        return {
            "status": "error",
            "reason": "missing_required_field",
            "message": "Mobile number is required.",
        }, 400

    partner_raw = _data_lookup(data, _CHANNEL_PARTNER_KEYS)
    partner_value, partner_matched = resolve_channel_partner_name(partner_raw)
    comment = _data_lookup(data, _COMMENT_KEYS)

    intake_body = map_channel_partner_data_to_intake(data, project=project)
    if partner_value and not partner_matched:
        intake_body["meta"] = {"channel_partner_unmatched": True, "channel_partner_raw": partner_value}

    api_key = {
        "id": f"channel-partner:{project['id']}",
        "project_id": project["id"],
        "project_name": project["name"],
        "channel_partner": partner_value,
        "comments": comment,
        "rate_limit_per_min": 120,
    }

    fingerprint = f"{phone or ''}|{email or ''}"

    try:
        result, status = await ingest_lead(
            body=intake_body, api_key=api_key, ip=ip, duplicate_policy="reject",
        )
    except IntakeValidationError as e:
        await _write_log(
            fingerprint=fingerprint, project_id=project["id"], channel_partner=partner_value,
            success=False, reason="validation_error", http_status=400,
        )
        return {"status": "error", "reason": "validation_error", "errors": e.errors}, 400
    except Exception as e:
        await _write_log(
            fingerprint=fingerprint, project_id=project["id"], channel_partner=partner_value,
            success=False, reason=f"ingest_error: {e}"[:300], http_status=500,
        )
        logger.error("channel partner ingest failed project=%s: %s", project["id"], e, exc_info=True)
        return {"status": "error", "reason": "internal_error"}, 500

    if result.get("duplicate"):
        await _write_log(
            fingerprint=fingerprint, project_id=project["id"], channel_partner=partner_value,
            success=False, reason="duplicate", lead_id=result.get("lead_id"), http_status=409,
        )
        return {
            "status": "duplicate",
            "message": "A lead with this mobile number already exists in Clara CRM.",
        }, 409

    if result.get("deduped"):
        # 10s double-click idempotency retry of the same submission — success, not an error.
        await _write_log(
            fingerprint=fingerprint, project_id=project["id"], channel_partner=partner_value,
            success=True, reason="idempotent_10s", lead_id=result.get("lead_id"), http_status=200,
        )
        return {"status": "ok", "lead_id": result.get("lead_id"), "deduped": True}, 200

    await _write_log(
        fingerprint=fingerprint, project_id=project["id"], channel_partner=partner_value,
        success=True, reason="created", lead_id=result.get("lead_id"), http_status=201,
    )
    return {"status": "created", "lead_id": result.get("lead_id")}, 201
