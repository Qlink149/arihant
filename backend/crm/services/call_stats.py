"""Display-only call attempt counts derived from context_updates."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from crm.utils.helpers import coerce_datetime


def compute_call_attempt_counts(context_updates: List[dict]) -> Dict[str, int]:
    """Count call timeline entries. Manual summaries count as outbound."""
    total = 0
    outbound = 0
    for entry in context_updates or []:
        if not isinstance(entry, dict):
            continue
        if (entry.get("type") or "").strip().lower() != "call":
            continue
        total += 1
        direction = (entry.get("direction") or "").strip().lower()
        if direction == "outbound" or not direction:
            outbound += 1
    return {
        "call_attempt_count_total": total,
        "call_attempt_count_outbound": outbound,
    }


def apply_call_attempt_counts_to_lead(lead: Dict[str, Any]) -> None:
    counts = compute_call_attempt_counts(lead.get("context_updates") or [])
    lead.update(counts)


def _entry_since(entry: dict, since: Optional[datetime]) -> bool:
    if not since:
        return True
    ts = coerce_datetime(entry.get("timestamp_dt")) or coerce_datetime(entry.get("timestamp"))
    if not ts:
        return False
    if ts.tzinfo is None:
        from datetime import timezone

        ts = ts.replace(tzinfo=timezone.utc)
    if since.tzinfo is None:
        from datetime import timezone

        since = since.replace(tzinfo=timezone.utc)
    return ts >= since


def compute_rnr_stay_call_panel(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Per-agent logged attempts and telephony for the current RNR stay (display only)."""
    since = coerce_datetime(lead.get("rnr_entered_at_dt"))
    attempts_by_agent: Dict[str, int] = {}
    calls_by_agent: Dict[str, int] = {}
    calls_unattributed = 0
    for entry in lead.get("context_updates") or []:
        if not isinstance(entry, dict) or not _entry_since(entry, since):
            continue
        etype = (entry.get("type") or "").strip().lower()
        actor = (
            entry.get("actor_name")
            or entry.get("agent")
            or entry.get("actor_user_id")
            or "Unknown"
        )
        actor = str(actor).strip() or "Unknown"
        if etype == "rnr_attempt":
            attempts_by_agent[actor] = attempts_by_agent.get(actor, 0) + 1
        elif etype == "call":
            if entry.get("actor_user_id") or entry.get("actor_name") or entry.get("agent"):
                calls_by_agent[actor] = calls_by_agent.get(actor, 0) + 1
            else:
                calls_unattributed += 1
    return {
        "rnr_attempts_by_agent": attempts_by_agent,
        "rnr_telephony_by_agent": calls_by_agent,
        "rnr_telephony_unattributed": calls_unattributed,
        "rnr_attempts_total": sum(attempts_by_agent.values()),
        "rnr_telephony_total": sum(calls_by_agent.values()) + calls_unattributed,
    }
