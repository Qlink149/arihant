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
from crm.services.lead_project_fields import (
    RE_ENGAGED_STATUS,
    append_incoming_project,
    coalesce_projects,
    incoming_slug_on_lead,
    should_reengage_status,
)
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

ZAPIER_META_ACTOR_NAME = "Zapier Meta Lead"
ZAPIER_META_ACTOR_ID = "system-zapier-meta"
ZAPIER_META_CREATED = "Lead created via Zapier (Meta Instant Form)"
ZAPIER_META_RESUB = "Meta Instant Form resubmission via Zapier"


def _intake_actor(api_key: Optional[dict]) -> Tuple[str, str, str, str]:
    """Return actor_id, actor_name, created_description, resub_description."""
    key_id = str((api_key or {}).get("id") or "")
    if key_id.startswith("zapier-meta:"):
        return (
            ZAPIER_META_ACTOR_ID,
            ZAPIER_META_ACTOR_NAME,
            ZAPIER_META_CREATED,
            ZAPIER_META_RESUB,
        )
    return (
        ACTOR_ID,
        ACTOR_NAME,
        "Lead created via website intake",
        "Website form resubmission",
    )

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


def _match_query(
    project_id: str,
    email: Optional[str],
    normalized_phone: Optional[str],
    *,
    require_project_id: bool = True,
    phone_only: bool = False,
) -> Dict[str, Any]:
    if phone_only and normalized_phone:
        return {"normalized_phone": normalized_phone}
    or_clauses: List[Dict[str, Any]] = []
    if email:
        or_clauses.append({"email": email})
    if normalized_phone:
        or_clauses.append({"normalized_phone": normalized_phone})
    if not or_clauses:
        contact: Dict[str, Any] = {}
    elif len(or_clauses) == 1:
        contact = or_clauses[0]
    else:
        contact = {"$or": or_clauses}
    if require_project_id:
        project_clause: Dict[str, Any] = {
            "$or": [{"project_id": project_id}, {"project_ids": project_id}]
        }
        if contact:
            return {"$and": [project_clause, contact]}
        return project_clause
    return contact


async def _find_recent_lead(
    *,
    project_id: str,
    email: Optional[str],
    normalized_phone: Optional[str],
    within_seconds: Optional[int] = None,
    within_days: Optional[int] = None,
    require_project_id: bool = True,
    phone_only: bool = False,
) -> Optional[dict]:
    if phone_only:
        if not normalized_phone:
            return None
    elif not email and not normalized_phone:
        return None
    q = _match_query(
        project_id,
        email,
        normalized_phone,
        require_project_id=require_project_id,
        phone_only=phone_only,
    )
    if not q:
        return None
    if within_seconds is not None:
        q["updated_at_dt"] = {"$gte": utc_now() - timedelta(seconds=within_seconds)}
    elif within_days is not None:
        q["created_at_dt"] = {"$gte": utc_now() - timedelta(days=within_days)}
    return await db.leads.find_one(q, {"_id": 0}, sort=[("updated_at_dt", -1)])


async def _apply_reengage_transition(lead_id: str, existing: dict, patch: Dict[str, Any], now_dt) -> bool:
    """Closed Lost / Unqualified / Gone Cold → Re-engaged with the same side effects as update_lead."""
    if not should_reengage_status(existing.get("lead_status")):
        return False
    patch["lead_status"] = RE_ENGAGED_STATUS
    patch["reengaged_at_dt"] = now_dt
    tasks_coll = getattr(db, "tasks", None)
    if tasks_coll is not None:
        await tasks_coll.update_many(
            {"lead_id": lead_id, "source": "sla", "status": "pending"},
            {"$set": {"status": "cancelled", "updated_at": iso_utc_now(), "updated_at_dt": now_dt}},
        )
    await db.leads.update_one({"id": lead_id}, {"$unset": {"sla_flags.reengaged": ""}})
    return True


async def _notify_re_enquiry(existing: dict, project_label: str) -> None:
    assignee_id = (existing.get("assigned_user_id") or "").strip()
    if not assignee_id:
        return
    lead_name = f"{existing.get('first_name', '')} {existing.get('last_name', '')}".strip() or "Lead"
    try:
        from crm.services.notification_service import create_notification

        await create_notification(
            recipient_user_id=assignee_id,
            recipient_name=existing.get("assigned_to_name") or existing.get("assigned_to") or "",
            title="Re-enquiry",
            message=f"{lead_name} submitted again for {project_label or 'a project'}",
            notification_type="lead_status_changed",
            lead_id=existing.get("id") or "",
            lead_name=lead_name,
            severity="medium",
            urgency="action_needed",
            dedupe_key=f"re_enquiry:{existing.get('id')}:{iso_utc_now()[:16]}",
        )
    except Exception as e:
        logger.warning("re-enquiry notify failed lead=%s: %s", existing.get("id"), e)


def _next_submission_count(existing: dict) -> int:
    """Imported leads store submission_count as BSON null; Mongo $inc rejects that."""
    raw = existing.get("submission_count")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 0
    return max(n, 0) + 1


def _blank_to_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _full_name(first: Any, last: Any) -> str:
    parts = [p for p in (_blank_to_none(first), _blank_to_none(last)) if p]
    return " ".join(parts)


def _name_key(first: Any, last: Any) -> str:
    return _full_name(first, last).casefold()


def _email_key(value: Any) -> str:
    return (_blank_to_none(value) or "").casefold()


def _text_changed(before: Any, after: Any) -> bool:
    return (_blank_to_none(before) or "") != (_blank_to_none(after) or "")


def _append_change(changes: List[Dict[str, Any]], field: str, before: Any, after: Any) -> None:
    changes.append({"field": field, "from": before, "to": after})


async def _update_existing_submission(
    existing: dict, data: Dict[str, Any], source: str, *, api_key: Optional[dict] = None
) -> str:
    lead_id = existing["id"]
    now_dt = utc_now()
    now_iso = iso_utc_now()
    actor_id, actor_name, _, resub_desc = _intake_actor(api_key)
    incoming_name = (api_key or {}).get("project_name")
    incoming_id = (api_key or {}).get("project_id")
    merged = append_incoming_project(
        existing, incoming_name=incoming_name, incoming_id=incoming_id
    )
    already = bool(merged.get("already")) or incoming_slug_on_lead(existing, incoming_id)
    label = str(incoming_name or "").strip() or "project"
    old_project_names = coalesce_projects(existing)
    new_project_names = merged.get("projects") or []
    name_appended = {n.casefold() for n in new_project_names} - {n.casefold() for n in old_project_names}
    if name_appended:
        timeline_desc = f"Re-enquiry — added {label}"
    elif incoming_name:
        timeline_desc = f"Re-enquiry — {label} (existing project)"
    else:
        timeline_desc = "Re-enquiry"

    changes: List[Dict[str, Any]] = []
    patch: Dict[str, Any] = {
        "updated_at": now_iso,
        "updated_at_dt": now_dt,
        "most_recent_source": source,
        "consent": data["consent"],
        "re_enquiry": True,
        "re_enquired_at": now_dt,
        "submission_count": _next_submission_count(existing),
        "projects": new_project_names,
        "project_ids": merged.get("project_ids") or [],
    }
    if merged.get("project"):
        patch["project"] = merged["project"]
    if data.get("budget"):
        patch["budget"] = data["budget"]
        if _text_changed(existing.get("budget"), data["budget"]):
            _append_change(
                changes,
                "budget",
                _blank_to_none(existing.get("budget")),
                _blank_to_none(data["budget"]),
            )
    if data.get("schedule_visit"):
        patch["schedule_visit"] = data["schedule_visit"]
        if _text_changed(existing.get("schedule_visit"), data["schedule_visit"]):
            _append_change(
                changes,
                "schedule_visit",
                _blank_to_none(existing.get("schedule_visit")),
                _blank_to_none(data["schedule_visit"]),
            )
    if data.get("meta") is not None:
        patch["intake_meta"] = data["meta"]

    inc_first = data.get("first_name")
    inc_last = data.get("last_name")
    has_incoming_name = bool(_blank_to_none(inc_first) or _blank_to_none(inc_last))
    if has_incoming_name:
        new_first = (inc_first or "").strip() if inc_first is not None else (existing.get("first_name") or "")
        new_last = (inc_last or "").strip() if inc_last is not None else (existing.get("last_name") or "")
        if _name_key(new_first, new_last) != _name_key(existing.get("first_name"), existing.get("last_name")):
            patch["first_name"] = new_first
            patch["last_name"] = new_last
            _append_change(
                changes,
                "name",
                _full_name(existing.get("first_name"), existing.get("last_name")) or None,
                _full_name(new_first, new_last) or None,
            )

    incoming_email = _blank_to_none(data.get("email"))
    if incoming_email and _email_key(incoming_email) != _email_key(existing.get("email")):
        patch["email"] = incoming_email.lower()
        _append_change(
            changes,
            "email",
            _blank_to_none(existing.get("email")),
            incoming_email.lower(),
        )

    if data.get("phone") and not existing.get("phone"):
        patch["phone"] = data["phone"]
        patch["normalized_phone"] = normalize_phone(data["phone"])

    if name_appended:
        _append_change(
            changes,
            "projects",
            old_project_names or None,
            new_project_names,
        )

    reengaged = await _apply_reengage_transition(lead_id, existing, patch, now_dt)
    if patch.get("lead_status") and patch.get("lead_status") != existing.get("lead_status"):
        _append_change(changes, "lead_status", existing.get("lead_status"), patch.get("lead_status"))

    context_entry = {
        "type": "intake_resubmission",
        "timestamp": now_iso,
        "timestamp_dt": now_dt,
        "description": timeline_desc,
        "changes": changes,
        "agent": actor_name,
        "actor_user_id": actor_id,
        "actor_name": actor_name,
    }
    add_to_set: Dict[str, Any] = {}
    if merged.get("appended") and incoming_name and not already:
        add_to_set["projects"] = str(incoming_name).strip()
        if incoming_id:
            add_to_set["project_ids"] = str(incoming_id).strip()

    update_doc: Dict[str, Any] = {
        "$set": patch,
        "$push": {"context_updates": context_entry},
    }
    if add_to_set and isinstance(existing.get("projects"), list) and existing.get("projects"):
        update_doc["$addToSet"] = add_to_set
        # Avoid setting the same array fields we $addToSet
        patch.pop("projects", None)
        patch.pop("project_ids", None)

    await db.leads.update_one({"id": lead_id}, update_doc)

    if reengaged:
        try:
            from crm.services.sla_helpers import create_sla_task_for_lead

            merged_lead = {**existing, **patch, "lead_status": RE_ENGAGED_STATUS}
            await create_sla_task_for_lead(
                merged_lead,
                description="Re-engaged lead — qualify intent",
                dedupe_key=f"sla:reengaged:qualify:{lead_id}",
                sla_rule="reengaged",
                sla_threshold="t0",
                stage="reengaged",
            )
        except Exception as e:
            logger.warning("intake re-engage SLA task failed lead=%s: %s", lead_id, e)

    await _notify_re_enquiry(existing, label)
    return lead_id


async def _create_new_lead(data: Dict[str, Any], *, api_key: dict, source: str) -> str:
    lead_id = str(uuid.uuid4())
    now_dt = utc_now()
    now_iso = iso_utc_now()
    actor_id, actor_name, created_desc, _ = _intake_actor(api_key)
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
        "projects": [api_key["project_name"]] if api_key.get("project_name") else None,
        "project_ids": [api_key["project_id"]] if api_key.get("project_id") else None,
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
                "description": created_desc,
                "agent": actor_name,
                "actor_user_id": actor_id,
                "actor_name": actor_name,
            }
        ],
        "created_at": now_iso,
        "created_at_dt": now_dt,
        "updated_at": now_iso,
        "updated_at_dt": now_dt,
    }
    if not lead_dict.get("projects"):
        lead_dict.pop("projects", None)
    if not lead_dict.get("project_ids"):
        lead_dict.pop("project_ids", None)
    lead_dict["normalized_phone"] = normalize_phone(data.get("phone")) if data.get("phone") else None
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

    # 10s double-click idempotency (same project only)
    recent = await _find_recent_lead(
        project_id=project_id,
        email=data.get("email"),
        normalized_phone=normalized,
        within_seconds=IDEMPOTENCY_SECONDS,
        require_project_id=True,
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

    # 30-day merge: phone is global; email-only stays same-project
    if normalized:
        existing = await _find_recent_lead(
            project_id=project_id,
            email=None,
            normalized_phone=normalized,
            within_days=DEDUPE_WINDOW_DAYS,
            require_project_id=False,
            phone_only=True,
        )
    else:
        existing = await _find_recent_lead(
            project_id=project_id,
            email=data.get("email"),
            normalized_phone=None,
            within_days=DEDUPE_WINDOW_DAYS,
            require_project_id=True,
        )
    if existing:
        lead_id = await _update_existing_submission(existing, data, source, api_key=api_key)
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
            lead_id = await _update_existing_submission(existing_phone, data, source, api_key=api_key)
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
