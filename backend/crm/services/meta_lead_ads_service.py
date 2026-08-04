"""Meta Lead Ads webhook processing — Instant Forms → CRM leads."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from crm.core.state import (
    META_API_VERSION,
    META_APP_SECRET,
    META_LEAD_FORM_PROJECT_MAP,
    META_LEAD_VERIFY_TOKEN,
    META_PAGE_ACCESS_TOKEN,
    PROJECT_REGISTRY,
    db,
    iso_utc_now,
    logger,
    utc_now,
)
from crm.services.lead_intake_service import ingest_lead

HTTP_TIMEOUT = 30.0
SOURCE_DEFAULT = "Facebook Lead Form"


def verify_hub_token(mode: Optional[str], token: Optional[str]) -> bool:
    if (mode or "").strip() != "subscribe":
        return False
    expected = (META_LEAD_VERIFY_TOKEN or "").strip()
    if not expected or not token:
        return False
    return hmac.compare_digest(expected, str(token).strip())


def verify_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """Validate X-Hub-Signature-256 using META_APP_SECRET."""
    secret = (META_APP_SECRET or "").strip()
    if not secret or not signature_header:
        return False
    header = signature_header.strip()
    if not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


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


def _field_map(field_data: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not isinstance(field_data, list):
        return out
    for item in field_data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        values = item.get("values") or []
        if not name:
            continue
        if isinstance(values, list) and values:
            out[name] = str(values[0]).strip()
        elif values:
            out[name] = str(values).strip()
    return out


def _split_full_name(full: str) -> Tuple[str, str]:
    parts = full.strip().split(None, 1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def map_field_data_to_intake(
    field_data: Any,
    *,
    leadgen_id: str,
    form_id: Optional[str] = None,
    page_id: Optional[str] = None,
    ad_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Map Meta field_data into lead_intake payload shape."""
    fields = _field_map(field_data)

    first = fields.get("first_name") or fields.get("firstname") or ""
    last = fields.get("last_name") or fields.get("lastname") or ""
    full = (
        fields.get("full_name")
        or fields.get("fullname")
        or fields.get("full name")
        or ""
    )
    if not first and full:
        first, last = _split_full_name(full)

    email = (
        fields.get("email")
        or fields.get("email_address")
        or fields.get("work_email")
        or None
    )
    phone = (
        fields.get("phone_number")
        or fields.get("phone")
        or fields.get("mobile_number")
        or fields.get("mobile")
        or None
    )

    return {
        "first_name": first or "Unknown",
        "last_name": last or "",
        "email": email,
        "phone": phone,
        "consent": True,
        "source": SOURCE_DEFAULT,
        "meta": {
            "leadgen_id": leadgen_id,
            "form_id": form_id,
            "page_id": page_id,
            "ad_id": ad_id,
            "campaign_id": campaign_id,
            "raw_fields": fields,
        },
    }


async def _write_log(
    *,
    leadgen_id: str,
    form_id: Optional[str],
    page_id: Optional[str],
    success: bool,
    reason: str,
    lead_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> None:
    now_iso = iso_utc_now()
    now_dt = utc_now()
    set_fields = {
        "form_id": form_id,
        "page_id": page_id,
        "project_id": project_id,
        "success": success,
        "reason": (reason or "")[:300],
        "lead_id": lead_id,
        "updated_at": now_iso,
        "updated_at_dt": now_dt,
    }
    try:
        await db.meta_lead_ads_logs.update_one(
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
        logger.error("meta_lead_ads_logs write failed: %s", e)


async def fetch_lead_from_graph(leadgen_id: str) -> dict:
    token = (META_PAGE_ACCESS_TOKEN or "").strip()
    if not token:
        raise RuntimeError("META_PAGE_ACCESS_TOKEN not configured")
    version = (META_API_VERSION or "v21.0").strip().lstrip("/")
    url = f"https://graph.facebook.com/{version}/{leadgen_id}"
    params = {
        "access_token": token,
        "fields": "created_time,ad_id,adgroup_id,campaign_id,form_id,field_data",
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def extract_leadgen_events(payload: dict) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            if (change.get("field") or "") != "leadgen":
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            leadgen_id = value.get("leadgen_id")
            if leadgen_id:
                events.append(value)
    return events


async def process_leadgen_event(value: dict) -> Dict[str, Any]:
    """Fetch one leadgen, map, ingest. Never raises to caller of webhook POST."""
    leadgen_id = str(value.get("leadgen_id") or "").strip()
    form_id = str(value.get("form_id") or "").strip() or None
    page_id = str(value.get("page_id") or "").strip() or None
    ad_id = str(value.get("ad_id") or "").strip() or None
    campaign_id = str(value.get("campaign_id") or "").strip() or None

    if not leadgen_id:
        return {"success": False, "reason": "missing_leadgen_id"}

    existing = await db.meta_lead_ads_logs.find_one({"leadgen_id": leadgen_id}, {"_id": 0})
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
            page_id=page_id,
            success=False,
            reason="unmapped_form",
        )
        logger.warning("Meta leadgen unmapped form_id=%s leadgen_id=%s", form_id, leadgen_id)
        return {"success": False, "reason": "unmapped_form", "form_id": form_id}

    try:
        graph_lead = await fetch_lead_from_graph(leadgen_id)
    except Exception as e:
        await _write_log(
            leadgen_id=leadgen_id,
            form_id=form_id,
            page_id=page_id,
            success=False,
            reason=f"graph_fetch_failed: {e}",
            project_id=project["id"],
        )
        logger.error("Meta leadgen fetch failed leadgen_id=%s: %s", leadgen_id, e)
        return {"success": False, "reason": "graph_fetch_failed"}

    form_id = str(graph_lead.get("form_id") or form_id or "").strip() or form_id
    # Re-resolve if graph returned form_id
    project = project_from_form_id(form_id) or project

    body = map_field_data_to_intake(
        graph_lead.get("field_data"),
        leadgen_id=leadgen_id,
        form_id=form_id,
        page_id=page_id,
        ad_id=ad_id or str(graph_lead.get("ad_id") or "") or None,
        campaign_id=campaign_id or str(graph_lead.get("campaign_id") or "") or None,
    )

    # Need email or phone for intake validation
    if not body.get("email") and not body.get("phone"):
        await _write_log(
            leadgen_id=leadgen_id,
            form_id=form_id,
            page_id=page_id,
            success=False,
            reason="missing_email_and_phone",
            project_id=project["id"],
        )
        return {"success": False, "reason": "missing_email_and_phone"}

    api_key = {
        "id": f"meta-lead-ads:{project['id']}",
        "project_id": project["id"],
        "project_name": project["name"],
        "rate_limit_per_min": 120,
    }

    try:
        result, status = await ingest_lead(body=body, api_key=api_key, ip=None)
        await _write_log(
            leadgen_id=leadgen_id,
            form_id=form_id,
            page_id=page_id,
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
        }
    except Exception as e:
        await _write_log(
            leadgen_id=leadgen_id,
            form_id=form_id,
            page_id=page_id,
            success=False,
            reason=f"ingest_error: {e}",
            project_id=project["id"],
        )
        logger.error("Meta leadgen ingest failed leadgen_id=%s: %s", leadgen_id, e, exc_info=True)
        return {"success": False, "reason": "ingest_error"}


async def process_webhook_payload(payload: dict) -> List[Dict[str, Any]]:
    results = []
    for value in extract_leadgen_events(payload):
        results.append(await process_leadgen_event(value))
    return results
