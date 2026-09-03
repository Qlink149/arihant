"""Lead helpers for SLA branching (no sla_engine import)."""

from __future__ import annotations

import re
from datetime import timezone
from typing import Optional

from crm.utils.helpers import coerce_datetime

# Positive booking/deal progress — not the broad CLOSED regex (Closed Lost must not match)
_BOOKING_PROGRESS_REGEX = re.compile(
    r"(?i)(negotiat|advance|booked|token|closed\s*won|\bwon\b)",
)


_SYSTEM_ACTOR_IDS = {"", "system", "system-intake"}
_SYSTEM_ACTOR_NAMES = {
    "system",
    "system auto-ack",
    "website intake",
    "sla engine",
}


def _normalize_actor_token(value) -> str:
    return str(value or "").strip().lower()


def _is_system_actor(entry: dict) -> bool:
    uid = _normalize_actor_token(entry.get("actor_user_id"))
    agent = _normalize_actor_token(entry.get("agent") or entry.get("actor_name"))
    if agent in _SYSTEM_ACTOR_NAMES:
        return True
    if uid in _SYSTEM_ACTOR_IDS:
        # Missing id with a human display name still counts as a person.
        return not bool(agent) or agent in _SYSTEM_ACTOR_NAMES
    if uid in _SYSTEM_ACTOR_NAMES:
        return True
    return False


def _is_assigned_agent(entry: dict, lead: dict) -> bool:
    assigned_id = str(lead.get("assigned_user_id") or "").strip()
    actor_id = str(entry.get("actor_user_id") or "").strip()
    if assigned_id and actor_id and actor_id.lower() not in _SYSTEM_ACTOR_IDS:
        return assigned_id == actor_id
    assigned_name = _normalize_actor_token(
        lead.get("assigned_to") or lead.get("assigned_to_name") or lead.get("presales_agent")
    )
    actor_name = _normalize_actor_token(entry.get("agent") or entry.get("actor_name"))
    if assigned_name and actor_name:
        return assigned_name == actor_name
    return False


def _updated_fields(entry: dict) -> set:
    fields = set()
    for change in entry.get("changes") or []:
        if isinstance(change, dict) and change.get("field"):
            fields.add(str(change["field"]).strip())
    return fields


def has_agent_activity_since(lead: dict, since_dt) -> bool:
    """True when the *assigned agent* logged call / note / status / outcome since since_dt.

    System events (auto WhatsApp, assignment, SLA tasks) never count.
    """
    since = coerce_datetime(since_dt)
    if not since:
        return False
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    for entry in lead.get("context_updates") or []:
        ts = coerce_datetime(entry.get("timestamp_dt")) or coerce_datetime(entry.get("timestamp"))
        if not ts:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts < since:
            continue
        if _is_system_actor(entry):
            continue
        if not _is_assigned_agent(entry, lead):
            continue

        etype = (entry.get("type") or "").strip().lower()
        update_type = (entry.get("update_type") or "").strip().lower()
        if etype == "call" or update_type == "call_note":
            return True
        if etype == "note" or update_type == "general_note":
            return True
        if etype == "updated":
            fields = _updated_fields(entry)
            if "lead_status" in fields or "logged_outcome" in fields or "logged_outcome_reason" in fields:
                return True
    return False


async def has_meaningful_contact_since(lead: dict, since_dt) -> bool:
    since = coerce_datetime(since_dt)
    if not since:
        return False
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    for entry in lead.get("context_updates") or []:
        ts = coerce_datetime(entry.get("timestamp_dt")) or coerce_datetime(entry.get("timestamp"))
        if not ts or ts < since:
            continue
        etype = (entry.get("type") or "").lower()
        if etype in {"call", "whatsapp", "meeting", "task_completed", "site_visit"}:
            return True
        if entry.get("update_type") in {"call_note", "meeting_note", "whatsapp_update"}:
            return True
    return False


def is_booking_progress_status(lead_status: Optional[str]) -> bool:
    if not lead_status:
        return False
    s = str(lead_status).strip()
    return bool(_BOOKING_PROGRESS_REGEX.search(s))
