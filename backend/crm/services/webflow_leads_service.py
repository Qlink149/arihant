"""Webflow form_submission webhook → CRM leads (enquiry forms)."""

from __future__ import annotations

import hmac
import re
import unicodedata
import uuid
from typing import Any, Dict, Optional

from crm.core.state import (
    PROJECT_REGISTRY,
    WEBFLOW_WEBHOOK_SECRET,
    db,
    iso_utc_now,
    logger,
    utc_now,
)
from crm.services.lead_intake_service import ingest_lead

# Exact Webflow form names → CRM project id (client-provided).
_DEFAULT_FORM_NAME_PROJECT_MAP = {
    "melange enquiry form": "melange",
    "mira enquiry form": "mira",
    "reserve 16 enquiry form": "reserve-16",
    "vivriti enquiry form": "vivriti",
    "krsna enquiry form": "krsna",
}

# Defensive aliases for payload.data keys (normalized).
_FIRST_NAME_KEYS = ("first-name", "first_name", "firstname", "first name")
_LAST_NAME_KEYS = ("last-name", "last_name", "lastname", "last name")
_EMAIL_KEYS = ("cust-email", "email", "e-mail", "email address", "cust_email")
_PHONE_KEYS = ("phone", "phone number", "phone-number", "phone_number", "mobile")
_MESSAGE_KEYS = ("message", "msg", "comments", "comment")
_PROJECT_NAME_KEYS = ("project-name", "project_name", "project name", "project")


def verify_webhook_secret(
    token: Optional[str] = None,
    header_secret: Optional[str] = None,
) -> bool:
    """Validate shared secret from query ``token`` or ``X-Webhook-Secret``."""
    expected = (WEBFLOW_WEBHOOK_SECRET or "").strip()
    if not expected:
        return False
    candidates = []
    if token is not None:
        candidates.append(str(token).strip())
    if header_secret is not None:
        candidates.append(str(header_secret).strip())
    for candidate in candidates:
        if candidate and hmac.compare_digest(expected, candidate):
            return True
    return False


def _norm_key(key: Any) -> str:
    text = str(key or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text)


def _norm_form_name(name: Any) -> str:
    return _norm_key(name)


def _fold_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", (value or "").strip().lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _project_by_id(project_id: str) -> Optional[Dict[str, str]]:
    for p in PROJECT_REGISTRY:
        if p["id"] == project_id:
            return {"id": p["id"], "name": p["name"]}
    return None


def project_from_form_name(form_name: Optional[str]) -> Optional[Dict[str, str]]:
    if not form_name:
        return None
    project_id = _DEFAULT_FORM_NAME_PROJECT_MAP.get(_norm_form_name(form_name))
    if not project_id:
        return None
    return _project_by_id(project_id)


def project_from_project_name_field(project_name: Optional[str]) -> Optional[Dict[str, str]]:
    """Resolve Project-Name field (handles Melange vs Mélange)."""
    raw = (project_name or "").strip()
    if not raw:
        return None
    folded = _fold_name(raw)
    for p in PROJECT_REGISTRY:
        if p["id"] == folded or _fold_name(p["name"]) == folded:
            return {"id": p["id"], "name": p["name"]}
    # Common aliases without accents / spacing
    aliases = {
        "melange": "melange",
        "reserve16": "reserve-16",
        "reserve-16": "reserve-16",
        "reserve 16": "reserve-16",
    }
    compact = folded.replace(" ", "")
    mapped = aliases.get(folded) or aliases.get(compact)
    if mapped:
        return _project_by_id(mapped)
    return None


def _data_lookup(data: Dict[str, Any], candidates: tuple) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    by_norm = {_norm_key(k): v for k, v in data.items()}
    for key in candidates:
        if key in by_norm and by_norm[key] is not None:
            text = str(by_norm[key]).strip()
            if text:
                return text
    return None


def map_webflow_data_to_intake(
    data: Any,
    *,
    project: Dict[str, str],
    submission_id: Optional[str] = None,
    form_id: Optional[str] = None,
    site_id: Optional[str] = None,
    form_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Map Webflow payload.data into lead_intake body shape."""
    fields = data if isinstance(data, dict) else {}

    first = _data_lookup(fields, _FIRST_NAME_KEYS) or "Unknown"
    last = _data_lookup(fields, _LAST_NAME_KEYS) or ""
    email = _data_lookup(fields, _EMAIL_KEYS)
    phone = _data_lookup(fields, _PHONE_KEYS)
    message = _data_lookup(fields, _MESSAGE_KEYS)
    project_name_field = _data_lookup(fields, _PROJECT_NAME_KEYS)

    meta: Dict[str, Any] = {
        "webflow_submission_id": submission_id,
        "webflow_form_id": form_id,
        "webflow_site_id": site_id,
        "webflow_form_name": form_name,
    }
    if project_name_field:
        meta["project_name"] = project_name_field
    if message:
        meta["message"] = message

    return {
        "first_name": first,
        "last_name": last,
        "email": email,
        "phone": phone,
        "consent": True,
        "source": f"{project['name']} Website",
        "meta": meta,
    }


async def _write_log(
    *,
    submission_id: str,
    form_name: Optional[str],
    form_id: Optional[str],
    site_id: Optional[str],
    success: bool,
    reason: str,
    lead_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> None:
    now_iso = iso_utc_now()
    now_dt = utc_now()
    set_fields = {
        "form_name": form_name,
        "form_id": form_id,
        "site_id": site_id,
        "project_id": project_id,
        "success": success,
        "reason": (reason or "")[:300],
        "lead_id": lead_id,
        "updated_at": now_iso,
        "updated_at_dt": now_dt,
    }
    try:
        await db.webflow_leads_logs.update_one(
            {"submission_id": str(submission_id)},
            {
                "$set": set_fields,
                "$setOnInsert": {
                    "id": str(uuid.uuid4()),
                    "submission_id": str(submission_id),
                    "created_at": now_iso,
                    "created_at_dt": now_dt,
                },
            },
            upsert=True,
        )
    except Exception as e:
        logger.error("webflow_leads_logs write failed: %s", e)


def _extract_payload(body: dict) -> Dict[str, Any]:
    """Normalize Webflow envelope to a flat submission dict."""
    if not isinstance(body, dict):
        return {}
    inner = body.get("payload")
    if isinstance(inner, dict):
        return inner
    # Some older/alternate shapes put fields at top level
    if "data" in body or "name" in body:
        return body
    return {}


async def process_form_submission(body: dict) -> Dict[str, Any]:
    """Process one Webflow form_submission payload. Never raises to webhook caller."""
    trigger = str(body.get("triggerType") or "").strip()
    payload = _extract_payload(body)

    if trigger and trigger != "form_submission":
        return {"success": False, "reason": "ignored_trigger", "triggerType": trigger}

    form_name = str(payload.get("name") or "").strip() or None
    form_id = str(payload.get("formId") or "").strip() or None
    site_id = str(payload.get("siteId") or "").strip() or None
    submission_id = (
        str(payload.get("id") or "").strip()
        or str(payload.get("formSubmissionId") or "").strip()
        or None
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}

    if not submission_id:
        # Stable fallback so we can still audit; not ideal for idempotency across retries
        submission_id = f"anon:{uuid.uuid4()}"

    existing = await db.webflow_leads_logs.find_one(
        {"submission_id": submission_id}, {"_id": 0}
    )
    if existing and existing.get("success"):
        return {
            "success": True,
            "reason": "already_processed",
            "lead_id": existing.get("lead_id"),
            "deduped": True,
        }

    project = project_from_form_name(form_name)
    if not project:
        project_name_field = _data_lookup(data, _PROJECT_NAME_KEYS)
        project = project_from_project_name_field(project_name_field)

    if not project:
        await _write_log(
            submission_id=submission_id,
            form_name=form_name,
            form_id=form_id,
            site_id=site_id,
            success=False,
            reason="unmapped_form",
        )
        logger.warning(
            "Webflow enquiry unmapped form_name=%s submission_id=%s",
            form_name,
            submission_id,
        )
        return {"success": False, "reason": "unmapped_form", "form_name": form_name}

    intake_body = map_webflow_data_to_intake(
        data,
        project=project,
        submission_id=submission_id,
        form_id=form_id,
        site_id=site_id,
        form_name=form_name,
    )

    if not intake_body.get("email") and not intake_body.get("phone"):
        await _write_log(
            submission_id=submission_id,
            form_name=form_name,
            form_id=form_id,
            site_id=site_id,
            success=False,
            reason="missing_email_and_phone",
            project_id=project["id"],
        )
        return {"success": False, "reason": "missing_email_and_phone"}

    api_key = {
        "id": f"webflow:{project['id']}",
        "project_id": project["id"],
        "project_name": project["name"],
        "rate_limit_per_min": 120,
    }

    try:
        result, status = await ingest_lead(body=intake_body, api_key=api_key, ip=None)
        await _write_log(
            submission_id=submission_id,
            form_name=form_name,
            form_id=form_id,
            site_id=site_id,
            success=bool(result.get("success")),
            reason="ingested" if result.get("success") else "ingest_failed",
            lead_id=result.get("lead_id"),
            project_id=project["id"],
        )
        return {
            "success": bool(result.get("success")),
            "reason": "ingested",
            "lead_id": result.get("lead_id"),
            "deduped": result.get("deduped"),
            "http_status": status,
            "project_id": project["id"],
        }
    except Exception as e:
        await _write_log(
            submission_id=submission_id,
            form_name=form_name,
            form_id=form_id,
            site_id=site_id,
            success=False,
            reason=f"ingest_error: {e}"[:300],
            project_id=project["id"],
        )
        logger.error(
            "Webflow enquiry ingest failed submission_id=%s: %s",
            submission_id,
            e,
            exc_info=True,
        )
        return {"success": False, "reason": "ingest_error"}
