"""Zapier Meta Instant Form webhook → CRM leads."""

from __future__ import annotations

import hmac
import re
import unicodedata
import uuid
from typing import Any, Dict, Optional, Tuple

from crm.core.state import (
    META_LEAD_FORM_PROJECT_MAP,
    PROJECT_REGISTRY,
    ZAPIER_WEBHOOK_SECRET,
    db,
    iso_utc_now,
    logger,
    utc_now,
)
from crm.services.lead_intake_service import ingest_lead

SOURCE_DEFAULT = "Facebook Lead Form"

_LEAD_ID_KEYS = ("lead id", "lead_id", "leadgen_id", "id")
_FORM_ID_KEYS = ("form id", "form_id")
_FIRST_NAME_KEYS = ("first name", "first_name", "firstname")
_LAST_NAME_KEYS = ("last name", "last_name", "lastname")
_EMAIL_KEYS = ("email", "email_address", "e-mail")
_PHONE_KEYS = ("phone number", "phone_number", "phone", "mobile")
_BUDGET_KEYS = ("budget",)
_VISIT_KEYS = ("site visit preference", "schedule_visit", "site_visit_preference")
_CREATED_AT_KEYS = ("created at", "created_at", "created_time")
_FULL_NAME_KEYS = ("full name", "full_name", "fullname")


def verify_webhook_secret(
    token: Optional[str] = None,
    header_secret: Optional[str] = None,
) -> bool:
    """Validate shared secret from query ``token`` or ``X-Webhook-Secret``."""
    expected = (ZAPIER_WEBHOOK_SECRET or "").strip()
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


def _flatten_payload(body: dict) -> Dict[str, Any]:
    """Accept Zapier flat JSON or a nested ``data`` object."""
    if not isinstance(body, dict):
        return {}
    inner = body.get("data")
    if isinstance(inner, dict) and not any(_norm_key(k) in ("form id", "form_id") for k in body.keys()):
        merged = dict(inner)
        for k, v in body.items():
            if k != "data" and k not in merged:
                merged[k] = v
        return merged
    return body


def _lookup(fields: Dict[str, Any], candidates: tuple) -> Optional[str]:
    if not isinstance(fields, dict):
        return None
    by_norm = {_norm_key(k): v for k, v in fields.items()}
    for key in candidates:
        if key in by_norm and by_norm[key] is not None:
            text = str(by_norm[key]).strip()
            if text:
                return text
    return None


def _split_full_name(full: str) -> Tuple[str, str]:
    parts = full.strip().split(None, 1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def project_from_form_id(form_id: Optional[str]) -> Optional[Dict[str, str]]:
    if not form_id:
        return None
    project_id = META_LEAD_FORM_PROJECT_MAP.get(str(form_id).strip())
    if not project_id:
        return None
    for p in PROJECT_REGISTRY:
        if p["id"] == project_id:
            return {"id": p["id"], "name": p["name"]}
    return None


def map_zap_payload_to_intake(
    fields: Dict[str, Any],
    *,
    leadgen_id: str,
    form_id: Optional[str],
) -> Dict[str, Any]:
    first = _lookup(fields, _FIRST_NAME_KEYS) or ""
    last = _lookup(fields, _LAST_NAME_KEYS) or ""
    full = _lookup(fields, _FULL_NAME_KEYS) or ""
    if not first and full:
        first, last = _split_full_name(full)

    email = _lookup(fields, _EMAIL_KEYS)
    phone = _lookup(fields, _PHONE_KEYS)
    budget = _lookup(fields, _BUDGET_KEYS)
    visit = _lookup(fields, _VISIT_KEYS)
    created_at = _lookup(fields, _CREATED_AT_KEYS)

    meta: Dict[str, Any] = {
        "leadgen_id": leadgen_id,
        "form_id": form_id,
        "via": "zapier",
    }
    if created_at:
        meta["created_at"] = created_at

    body: Dict[str, Any] = {
        "first_name": first or "Unknown",
        "last_name": last or "",
        "email": email,
        "phone": phone,
        "consent": True,
        "source": SOURCE_DEFAULT,
        "meta": meta,
    }
    if budget:
        body["budget"] = budget
    if visit:
        body["schedule_visit"] = visit
    return body


async def _write_log(
    *,
    leadgen_id: str,
    form_id: Optional[str],
    success: bool,
    reason: str,
    lead_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> None:
    now_iso = iso_utc_now()
    now_dt = utc_now()
    set_fields = {
        "form_id": form_id,
        "project_id": project_id,
        "success": success,
        "reason": (reason or "")[:300],
        "lead_id": lead_id,
        "updated_at": now_iso,
        "updated_at_dt": now_dt,
    }
    try:
        await db.zapier_leads_logs.update_one(
            {"leadgen_id": str(leadgen_id)},
            {
                "$set": set_fields,
                "$setOnInsert": {
                    "id": str(uuid.uuid4()),
                    "leadgen_id": str(leadgen_id),
                    "created_at": now_iso,
                    "created_at_dt": now_dt,
                },
            },
            upsert=True,
        )
    except Exception as e:
        logger.error("zapier_leads_logs write failed: %s", e)


async def process_zapier_lead(body: dict) -> Dict[str, Any]:
    """Process one Zapier Meta lead payload. Never raises to webhook caller."""
    fields = _flatten_payload(body if isinstance(body, dict) else {})
    form_id = _lookup(fields, _FORM_ID_KEYS)
    leadgen_id = _lookup(fields, _LEAD_ID_KEYS) or f"anon:{uuid.uuid4()}"

    existing = await db.zapier_leads_logs.find_one({"leadgen_id": leadgen_id}, {"_id": 0})
    if existing and existing.get("success"):
        return {
            "success": True,
            "reason": "already_processed",
            "lead_id": existing.get("lead_id"),
            "deduped": True,
        }

    project = project_from_form_id(form_id)
    if not project:
        await _write_log(
            leadgen_id=leadgen_id,
            form_id=form_id,
            success=False,
            reason="unmapped_form",
        )
        logger.warning("Zapier Meta lead unmapped form_id=%s leadgen_id=%s", form_id, leadgen_id)
        return {"success": False, "reason": "unmapped_form", "form_id": form_id}

    intake_body = map_zap_payload_to_intake(fields, leadgen_id=leadgen_id, form_id=form_id)

    if not intake_body.get("email") and not intake_body.get("phone"):
        await _write_log(
            leadgen_id=leadgen_id,
            form_id=form_id,
            success=False,
            reason="missing_email_and_phone",
            project_id=project["id"],
        )
        return {"success": False, "reason": "missing_email_and_phone"}

    api_key = {
        "id": f"zapier-meta:{project['id']}",
        "project_id": project["id"],
        "project_name": project["name"],
        "rate_limit_per_min": 120,
    }

    try:
        result, status = await ingest_lead(body=intake_body, api_key=api_key, ip=None)
        await _write_log(
            leadgen_id=leadgen_id,
            form_id=form_id,
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
            leadgen_id=leadgen_id,
            form_id=form_id,
            success=False,
            reason=f"ingest_error: {e}"[:300],
            project_id=project["id"],
        )
        logger.error("Zapier Meta lead ingest failed leadgen_id=%s: %s", leadgen_id, e, exc_info=True)
        return {"success": False, "reason": "ingest_error"}
