"""Public multi-tenant lead intake (website forms → CRM).

Authenticated via hashed API keys. Soft-dedupes within the same project.
Does not use JWT ``create_lead`` (global phone 400 conflicts with soft dedupe).
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict, deque
from datetime import timedelta
from threading import Lock
from typing import Any, Deque, Dict, List, Optional, Tuple

from pymongo.errors import DuplicateKeyError

from crm.core.state import db, iso_utc_now, logger, utc_now
from crm.services.lead_service import _apply_contact_phones
from crm.services.nurture_temperature import apply_nurture_temperature_rules
from crm.utils.helpers import determine_lead_intent, is_vip_lead, normalize_phone

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MAX_NAME_LEN = 100
MAX_EMAIL_LEN = 254
MAX_PHONE_LEN = 32
MAX_BUDGET_LEN = 100
MAX_SCHEDULE_LEN = 500
MAX_SOURCE_LEN = 200
MAX_META_KEYS = 40
MAX_META_VALUE_LEN = 500
MAX_META_JSON_CHARS = 8000
DEDUPE_WINDOW_DAYS = 30
IDEMPOTENCY_SECONDS = 10
ACTOR_NAME = "Website Intake"
ACTOR_ID = "system-intake"

# In-memory per-key rate limit (single Docker host).
_rate_buckets: Dict[str, Deque[float]] = defaultdict(deque)
_rate_lock = Lock()


class IntakeValidationError(Exception):
    def __init__(self, errors: List[Dict[str, Any]]):
        self.errors = errors
        super().__init__("validation_error")


class IntakeRateLimitError(Exception):
    pass


def _strip_str(value: Any, max_len: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len]


def digits_phone(value: Any) -> Optional[str]:
    """Strip to digits only, keeping country code."""
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits[:MAX_PHONE_LEN] if digits else None


def sanitize_meta(meta: Any) -> Optional[Dict[str, Any]]:
    if meta is None:
        return None
    if not isinstance(meta, dict):
        raise IntakeValidationError([{"loc": ["meta"], "msg": "must be an object", "type": "type_error"}])
    if len(meta) > MAX_META_KEYS:
        raise IntakeValidationError(
            [{"loc": ["meta"], "msg": f"at most {MAX_META_KEYS} keys allowed", "type": "value_error"}]
        )
    out: Dict[str, Any] = {}
    for raw_key, raw_val in meta.items():
        key = str(raw_key).strip()
        if not key or key.startswith("$") or "." in key:
            continue
        if isinstance(raw_val, (dict, list)):
            # Flatten nested to string to avoid operator injection / huge trees
            text = str(raw_val)[:MAX_META_VALUE_LEN]
        elif raw_val is None:
            continue
        elif isinstance(raw_val, bool):
            text = raw_val
        elif isinstance(raw_val, (int, float)):
            text = raw_val
        else:
            text = str(raw_val).strip()[:MAX_META_VALUE_LEN]
            if not text:
                continue
        out[key[:64]] = text
    # rough size guard
    approx = sum(len(str(k)) + len(str(v)) for k, v in out.items())
    if approx > MAX_META_JSON_CHARS:
        raise IntakeValidationError(
            [{"loc": ["meta"], "msg": "meta payload too large", "type": "value_error"}]
        )
    return out or None


def validate_intake_payload(body: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize intake body. Raises IntakeValidationError."""
    if not isinstance(body, dict) or not body:
        raise IntakeValidationError(
            [{"loc": ["body"], "msg": "Request body is required", "type": "value_error"}]
        )

    errors: List[Dict[str, Any]] = []

    if "consent" not in body:
        errors.append({"loc": ["consent"], "msg": "Field required", "type": "missing"})
    elif not isinstance(body.get("consent"), bool):
        errors.append({"loc": ["consent"], "msg": "must be a boolean", "type": "type_error"})

    first_name = _strip_str(body.get("first_name"), MAX_NAME_LEN)
    if not first_name:
        errors.append({"loc": ["first_name"], "msg": "Field required", "type": "missing"})

    last_name = _strip_str(body.get("last_name"), MAX_NAME_LEN) or ""

    email = _strip_str(body.get("email"), MAX_EMAIL_LEN)
    if email:
        email = email.lower()
        if not EMAIL_RE.match(email):
            errors.append({"loc": ["email"], "msg": "Invalid email format", "type": "value_error"})

    phone_raw = body.get("phone")
    phone = digits_phone(phone_raw) if phone_raw is not None and str(phone_raw).strip() else None

    if not email and not phone:
        errors.append(
            {
                "loc": ["email"],
                "msg": "At least one of email or phone is required",
                "type": "value_error",
            }
        )

    budget = _strip_str(body.get("budget"), MAX_BUDGET_LEN)
    schedule_visit = _strip_str(body.get("schedule_visit"), MAX_SCHEDULE_LEN)
    source = _strip_str(body.get("source"), MAX_SOURCE_LEN)

    honeypot_hit = False
    for hp in ("website", "hp"):
        if _strip_str(body.get(hp), 200):
            honeypot_hit = True
            break

    try:
        meta = sanitize_meta(body.get("meta")) if "meta" in body else None
    except IntakeValidationError as e:
        errors.extend(e.errors)
        meta = None

    if errors:
        raise IntakeValidationError(errors)

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "budget": budget,
        "schedule_visit": schedule_visit,
        "consent": bool(body["consent"]),
        "source": source,
        "meta": meta,
        "intake_spam": honeypot_hit,
    }


def check_rate_limit(api_key_id: str, limit_per_min: int) -> None:
    limit = max(1, int(limit_per_min or 60))
    now = utc_now().timestamp()
    window_start = now - 60.0
    with _rate_lock:
        bucket = _rate_buckets[api_key_id]
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= limit:
            raise IntakeRateLimitError()
        bucket.append(now)


def reset_rate_limits_for_tests() -> None:
    with _rate_lock:
        _rate_buckets.clear()


async def write_intake_log(
    *,
    project_name: str,
    project_id: Optional[str],
    api_key_id: Optional[str],
    ip: Optional[str],
    success: bool,
    reason: str,
    lead_id: Optional[str],
    http_status: int,
    deduped: Optional[bool] = None,
) -> None:
    try:
        await db.lead_intake_logs.insert_one(
            {
                "id": str(uuid.uuid4()),
                "timestamp": iso_utc_now(),
                "created_at": iso_utc_now(),
                "created_at_dt": utc_now(),
                "project_name": project_name,
                "project_id": project_id,
                "api_key_id": api_key_id,
                "ip": ip,
                "success": success,
                "reason": reason[:300],
                "lead_id": lead_id,
                "http_status": http_status,
                "deduped": deduped,
            }
        )
    except Exception as e:
        logger.error("lead_intake_logs insert failed: %s", e)


def _match_query(project_id: str, email: Optional[str], normalized_phone: Optional[str]) -> Dict[str, Any]:
    or_clauses: List[Dict[str, Any]] = []
    if email:
        or_clauses.append({"email": email})
    if normalized_phone:
        or_clauses.append({"normalized_phone": normalized_phone})
    return {"project_id": project_id, "$or": or_clauses}


async def _find_recent_lead(
    *,
    project_id: str,
    email: Optional[str],
    normalized_phone: Optional[str],
    within_seconds: Optional[int] = None,
    within_days: Optional[int] = None,
) -> Optional[dict]:
    if not email and not normalized_phone:
        return None
    q = _match_query(project_id, email, normalized_phone)
    if within_seconds is not None:
        q["updated_at_dt"] = {"$gte": utc_now() - timedelta(seconds=within_seconds)}
    elif within_days is not None:
        q["created_at_dt"] = {"$gte": utc_now() - timedelta(days=within_days)}
    return await db.leads.find_one(q, {"_id": 0}, sort=[("updated_at_dt", -1)])


async def _update_existing_submission(existing: dict, data: Dict[str, Any], source: str) -> str:
    lead_id = existing["id"]
    now_dt = utc_now()
    now_iso = iso_utc_now()
    patch: Dict[str, Any] = {
        "updated_at": now_iso,
        "updated_at_dt": now_dt,
        "most_recent_source": source,
        "consent": data["consent"],
    }
    if data.get("budget"):
        patch["budget"] = data["budget"]
    if data.get("schedule_visit"):
        patch["schedule_visit"] = data["schedule_visit"]
    if data.get("meta") is not None:
        patch["intake_meta"] = data["meta"]
    if data.get("first_name"):
        patch["first_name"] = data["first_name"]
    if data.get("last_name") is not None:
        patch["last_name"] = data["last_name"]
    if data.get("email") and not existing.get("email"):
        patch["email"] = data["email"]
    if data.get("phone") and not existing.get("phone"):
        patch["phone"] = data["phone"]
        patch["normalized_phone"] = normalize_phone(data["phone"])

    context_entry = {
        "type": "intake_resubmission",
        "timestamp": now_iso,
        "timestamp_dt": now_dt,
        "description": "Website form resubmission",
        "agent": ACTOR_NAME,
        "actor_user_id": ACTOR_ID,
        "actor_name": ACTOR_NAME,
    }
    await db.leads.update_one(
        {"id": lead_id},
        {
            "$set": patch,
            "$inc": {"submission_count": 1},
            "$push": {"context_updates": context_entry},
        },
    )
    return lead_id


async def _create_new_lead(data: Dict[str, Any], *, api_key: dict, source: str) -> str:
    lead_id = str(uuid.uuid4())
    now_dt = utc_now()
    now_iso = iso_utc_now()
    lead_dict: Dict[str, Any] = {
        "id": lead_id,
        "first_name": data["first_name"],
        "last_name": data["last_name"] or "",
        "email": data.get("email"),
        "phone": data.get("phone"),
        "budget": data.get("budget"),
        "schedule_visit": data.get("schedule_visit"),
        "consent": data["consent"],
        "intake_meta": data.get("meta"),
        "intake_spam": bool(data.get("intake_spam")),
        "submission_count": 1,
        "project": api_key.get("project_name"),
        "project_id": api_key.get("project_id"),
        "lead_status": "New",
        "lead_source": source,
        "original_source": source,
        "most_recent_source": source,
        "site_visit_count": 0,
        "assigned_to": None,
        "assigned_user_id": None,
        "assigned_to_name": None,
        "ai_persona_summary": None,
        "strategic_next_moves": [],
        "ai_grounded_profile": None,
        "ai_last_generated_at": None,
        "ai_last_generated_at_dt": None,
        "context_updates": [
            {
                "type": "created",
                "timestamp": now_iso,
                "timestamp_dt": now_dt,
                "description": "Lead created via website intake",
                "agent": ACTOR_NAME,
                "actor_user_id": ACTOR_ID,
                "actor_name": ACTOR_NAME,
            }
        ],
        "created_at": now_iso,
        "created_at_dt": now_dt,
        "updated_at": now_iso,
        "updated_at_dt": now_dt,
    }
    _apply_contact_phones(lead_dict)
    temp_patch = {"lead_status": "New"}
    apply_nurture_temperature_rules({}, temp_patch, is_create=True)
    lead_dict["temperature"] = temp_patch.get("temperature")
    lead_dict["intent"] = determine_lead_intent(lead_dict)
    lead_dict["vip"] = is_vip_lead(lead_dict)

    await db.leads.insert_one(lead_dict)

    if not lead_dict.get("intake_spam"):
        try:
            from crm.services.assignment_router import route_new_lead

            await route_new_lead(lead_id)
        except Exception as e:
            logger.warning("intake route_new_lead failed lead=%s: %s", lead_id, e)
        try:
            from crm.services.whatsapp_service import send_lead_ack

            # Await so ack cannot be dropped if the event loop/process exits
            # right after ingest (CLI backfills, short-lived tasks, etc.).
            ack = await send_lead_ack(lead_id, lead_dict)
            if not ack.get("success"):
                logger.warning(
                    "intake send_lead_ack unsuccessful lead=%s: %s",
                    lead_id,
                    ack.get("error") or ack,
                )
        except Exception as e:
            logger.warning("intake send_lead_ack failed lead=%s: %s", lead_id, e)

    return lead_id


async def ingest_lead(
    *,
    body: Dict[str, Any],
    api_key: dict,
    ip: Optional[str] = None,
) -> Tuple[Dict[str, Any], int]:
    """Validate + ingest. Returns (response_dict, http_status).

    Raises IntakeValidationError, IntakeRateLimitError.
    Unexpected errors are logged and re-raised for the endpoint to map to 500.
    """
    project_name = api_key.get("project_name") or ""
    project_id = api_key.get("project_id") or ""
    api_key_id = api_key.get("id")

    check_rate_limit(api_key_id or "unknown", api_key.get("rate_limit_per_min") or 60)

    data = validate_intake_payload(body)
    source = data.get("source") or project_name
    normalized = normalize_phone(data["phone"]) if data.get("phone") else None

    # 10s double-click idempotency
    recent = await _find_recent_lead(
        project_id=project_id,
        email=data.get("email"),
        normalized_phone=normalized,
        within_seconds=IDEMPOTENCY_SECONDS,
    )
    if recent:
        await write_intake_log(
            project_name=project_name,
            project_id=project_id,
            api_key_id=api_key_id,
            ip=ip,
            success=True,
            reason="idempotent_10s",
            lead_id=recent["id"],
            http_status=200,
            deduped=True,
        )
        return {"success": True, "lead_id": recent["id"], "deduped": True}, 200

    # 30-day soft dedupe (same project)
    existing = await _find_recent_lead(
        project_id=project_id,
        email=data.get("email"),
        normalized_phone=normalized,
        within_days=DEDUPE_WINDOW_DAYS,
    )
    if existing:
        lead_id = await _update_existing_submission(existing, data, source)
        await write_intake_log(
            project_name=project_name,
            project_id=project_id,
            api_key_id=api_key_id,
            ip=ip,
            success=True,
            reason="deduped_30d" + ("_spam" if data.get("intake_spam") else ""),
            lead_id=lead_id,
            http_status=200,
            deduped=True,
        )
        return {"success": True, "lead_id": lead_id, "deduped": True}, 200

    try:
        lead_id = await _create_new_lead(data, api_key=api_key, source=source)
    except DuplicateKeyError:
        # Global unique normalized_phone — treat as soft dedupe of that lead
        existing_phone = None
        if normalized:
            existing_phone = await db.leads.find_one({"normalized_phone": normalized}, {"_id": 0})
        if existing_phone:
            lead_id = await _update_existing_submission(existing_phone, data, source)
            await write_intake_log(
                project_name=project_name,
                project_id=project_id,
                api_key_id=api_key_id,
                ip=ip,
                success=True,
                reason="deduped_unique_phone",
                lead_id=lead_id,
                http_status=200,
                deduped=True,
            )
            return {"success": True, "lead_id": lead_id, "deduped": True}, 200
        raise

    reason = "created_spam" if data.get("intake_spam") else "created"
    await write_intake_log(
        project_name=project_name,
        project_id=project_id,
        api_key_id=api_key_id,
        ip=ip,
        success=True,
        reason=reason,
        lead_id=lead_id,
        http_status=201,
        deduped=False,
    )
    return {"success": True, "lead_id": lead_id, "deduped": False}, 201
