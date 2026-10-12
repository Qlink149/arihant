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
_CREATED_AT_KEYS = ("created at", "created_at", "created_time", "created time")
_FULL_NAME_KEYS = ("full name", "full_name", "fullname")
# Meta ad attribution - not sent by Zapier's standard "New Lead" trigger
# today; these cover plausible field names if/once a lookup step is added
# to the Zap itself (see docs - this cannot be fixed from this side alone).
_CAMPAIGN_ID_KEYS = ("campaign id", "campaign_id", "ad.campaign.id", "campaignid")
_CAMPAIGN_NAME_KEYS = ("campaign name", "campaign_name", "ad.campaign.name")
_ADSET_ID_KEYS = ("adset id", "adset_id", "ad set id", "ad_set_id", "ad.adset.id")
_ADSET_NAME_KEYS = ("adset name", "adset_name", "ad set name", "ad_set_name", "ad.adset.name")
_AD_ID_KEYS = ("ad id", "ad_id", "ad.id")
_AD_NAME_KEYS = ("ad name", "ad_name", "ad.name")


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


def _collapse_duplicate_name(first: str, last: str) -> Tuple[str, str]:
    """If Zap mapped full name into both first and last, split once."""
    f = (first or "").strip()
    l = (last or "").strip()
    if f and l and f.casefold() == l.casefold() and " " in f:
        return _split_full_name(f)
    return f, l


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


# When the numeric Form ID is missing from the map, the form/campaign NAME usually still says
# which project the lead is for (e.g. a Zap that sends "R-16 - Leads" in the form_id field).
_FORM_NAME_KEYS = ("form name", "form_name", "formname", "form title", "form_title", "form", "project", "project name")
_PROJECT_NAME_PATTERNS = (
    (re.compile(r"(?<![a-z0-9])(?:r[\s-]*16|reserve[\s-]*16)(?![a-z0-9])"), "reserve-16"),
    (re.compile(r"(?<![a-z0-9])melange(?![a-z0-9])"), "melange"),
    (re.compile(r"(?<![a-z0-9])mira(?![a-z0-9])"), "mira"),
    (re.compile(r"(?<![a-z0-9])(?:krsna|krishna)(?![a-z0-9])"), "krsna"),
    (re.compile(r"(?<![a-z0-9])vivriti(?![a-z0-9])"), "vivriti"),
)


def _project_from_texts(texts) -> Optional[Dict[str, str]]:
    found = set()
    for text in texts:
        norm = _norm_key(text)  # lower-cased, accents stripped ("Melange" matches "Melange")
        for pattern, project_id in _PROJECT_NAME_PATTERNS:
            if pattern.search(norm):
                found.add(project_id)
    if len(found) != 1:
        return None
    project_id = next(iter(found))
    for p in PROJECT_REGISTRY:
        if p["id"] == project_id:
            return {"id": p["id"], "name": p["name"]}
    return None


def project_from_form_name(fields: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Project from the form's NAME (e.g. "Reserve - 16 | Oct 26", "Melange - May26").

    Agreed with the client's Zapier owner: a form's numeric ID changes whenever the form is
    edited, so the project name in the form title is the identifier. Exactly one project must
    be named; two is ambiguous and is not guessed at."""
    name = _lookup(fields, _FORM_NAME_KEYS)
    return _project_from_texts([name]) if name else None


def project_from_names(fields: Dict[str, Any], form_id: Optional[str]) -> Optional[Dict[str, str]]:
    """Project from the form / campaign name, or None.

    Only when EXACTLY ONE project is named across the candidates: a form called for one
    project inside a campaign for another is ambiguous, and a wrong project is worse than
    an alert. A purely numeric value is an ID, not a name, and is never guessed at.
    """
    candidates = []
    if form_id and not str(form_id).strip().isdigit():
        candidates.append(str(form_id))
    candidates.extend(filter(None, (_lookup(fields, _FORM_NAME_KEYS), _lookup(fields, _CAMPAIGN_NAME_KEYS))))
    return _project_from_texts(candidates)


def _parse_created_time(value: Any):
    """Meta's "Created Time" as an aware UTC datetime, or None."""
    from datetime import datetime, timezone

    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            t = datetime.strptime(text.replace("Z", "+0000"), fmt)
            return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def _notify_admins_unmapped(form_id: Optional[str]) -> None:
    """In-app alert so an unrecognised Meta form can never be dropped silently.
    One alert per form per day."""
    try:
        from crm.services.notification_service import create_notification

        day = utc_now().strftime("%Y-%m-%d")
        admins = await db.users.find(
            {"role": {"$regex": r"^\s*admin\s*$", "$options": "i"}, "is_active": {"$ne": False}},
            {"_id": 0, "id": 1, "full_name": 1},
        ).to_list(20)
        for a in admins:
            await create_notification(
                recipient_user_id=a["id"],
                recipient_name=a.get("full_name") or "",
                title="Meta form not recognised - leads were not created",
                message=(
                    f"A Meta lead form submission (form '{form_id or 'unknown'}') could not be matched to a "
                    "project, so no lead was created. The details are saved. Ask the Zapier owner to send "
                    "the numeric Form ID, or add this form to the project map."
                ),
                notification_type="system_warning",
                severity="high",
                urgency="action_needed",
                dedupe_key=f"zapier_unmapped:{form_id}:{day}:{a['id']}",
            )
    except Exception as e:  # noqa: BLE001 - alerting must never break intake
        logger.error("zapier unmapped-form alert failed: %s", e)


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
    else:
        first, last = _collapse_duplicate_name(first, last)

    email = _lookup(fields, _EMAIL_KEYS)
    phone = _lookup(fields, _PHONE_KEYS)
    budget = _lookup(fields, _BUDGET_KEYS)
    visit = _lookup(fields, _VISIT_KEYS)
    created_at = _lookup(fields, _CREATED_AT_KEYS)
    campaign_id = _lookup(fields, _CAMPAIGN_ID_KEYS)
    campaign_name = _lookup(fields, _CAMPAIGN_NAME_KEYS)
    adset_id = _lookup(fields, _ADSET_ID_KEYS)
    adset_name = _lookup(fields, _ADSET_NAME_KEYS)
    ad_id = _lookup(fields, _AD_ID_KEYS)
    ad_name = _lookup(fields, _AD_NAME_KEYS)

    meta: Dict[str, Any] = {
        "leadgen_id": leadgen_id,
        "form_id": form_id,
        "via": "zapier",
    }
    if created_at:
        meta["created_at"] = created_at
    if campaign_id:
        meta["campaign_id"] = campaign_id
    if campaign_name:
        meta["campaign_name"] = campaign_name
    if adset_id:
        meta["adset_id"] = adset_id
    if adset_name:
        meta["adset_name"] = adset_name
    if ad_id:
        meta["ad_id"] = ad_id
    if ad_name:
        meta["ad_name"] = ad_name

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
    payload: Optional[Dict[str, Any]] = None,
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
    if payload is not None:
        # Kept ONLY for submissions we could not turn into a lead, so they can be replayed
        # (scripts/replay_unmapped_zapier_leads.py) instead of being lost.
        set_fields["rejected_payload"] = payload
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


async def process_zapier_lead(body: dict, *, backfill: bool = False) -> Dict[str, Any]:
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

    by_name = project_from_form_name(fields)
    by_id = project_from_form_id(form_id)
    project = by_name or by_id
    resolved_by = "form_name" if by_name else "form_id"
    if by_name and by_id and by_name["id"] != by_id["id"]:
        logger.warning(
            "Zapier Meta lead: form name says %s but Form ID %r maps to %s (leadgen_id=%s); using the form name.",
            by_name["id"], form_id, by_id["id"], leadgen_id,
        )
    if not project:
        project = project_from_names(fields, form_id)
        resolved_by = "name"
        if project:
            logger.warning(
                "Zapier Meta lead: form_id=%r not in the map; project %s taken from the form/campaign name "
                "(leadgen_id=%s). Ask the Zapier owner to send the numeric Form ID.",
                form_id, project["id"], leadgen_id,
            )
    if not project:
        await _write_log(
            leadgen_id=leadgen_id,
            form_id=form_id,
            success=False,
            reason="unmapped_form",
            payload=dict(fields),
        )
        logger.warning("Zapier Meta lead unmapped form_id=%s leadgen_id=%s", form_id, leadgen_id)
        await _notify_admins_unmapped(form_id)
        return {"success": False, "reason": "unmapped_form", "form_id": form_id}

    intake_body = map_zap_payload_to_intake(fields, leadgen_id=leadgen_id, form_id=form_id)
    if backfill and isinstance(intake_body.get("meta"), dict):
        occurred = _parse_created_time(intake_body["meta"].get("created_at"))
        if occurred:
            intake_body["meta"]["backfill"] = True
            intake_body["meta"]["occurred_at"] = occurred.isoformat()
    if resolved_by in ("form_name", "name") and isinstance(intake_body.get("meta"), dict):
        intake_body["meta"]["project_resolved_by"] = "form_name" if resolved_by == "form_name" else "form_or_campaign_name"
        form_name_value = _lookup(fields, _FORM_NAME_KEYS)
        if form_name_value:
            intake_body["meta"]["form_name"] = form_name_value

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
        "form_id": form_id,
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
            "reason": "ingested" if result.get("success") else "ingest_failed",
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
