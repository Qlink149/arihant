"""Display-only call attempt counts derived from context_updates."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from crm.utils.helpers import coerce_datetime


def compute_call_attempt_counts(context_updates: List[dict]) -> Dict[str, int]:
    """batch2 item 5: three separate counts, never merged into one "total" -
    the only direction data in this system is MCUBE (inbound-only today),
    and a typed call note carries no direction at all, so a single
    "outbound" figure was mostly typed notes wearing the wrong label.

      telephony_inbound  - MCUBE entries, direction == "inbound"
      telephony_outbound - MCUBE entries, direction == "outbound" (0 today)
      logged_by_agent    - any other call entry (typed call_note, or the
                            manual call-summary endpoint) - direction unknown

    CSV-imported notes (batch2 item 4a stores them as type:"note", not
    "call") never reach this function at all; the explicit source check
    below is a defensive backstop in case that ever changes.
    """
    telephony_inbound = 0
    telephony_outbound = 0
    logged_by_agent = 0
    for entry in context_updates or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("source") == "csv_import":
            continue
        if (entry.get("type") or "").strip().lower() != "call":
            continue
        if entry.get("mcube_call_id"):
            direction = (entry.get("direction") or "").strip().lower()
            if direction == "outbound":
                telephony_outbound += 1
            else:
                telephony_inbound += 1
        else:
            logged_by_agent += 1
    return {
        "telephony_inbound": telephony_inbound,
        "telephony_outbound": telephony_outbound,
        "logged_by_agent": logged_by_agent,
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
    """Per-agent logged attempts (SOP rnr_attempt actions) and telephony call
    counts for the current RNR stay (display only).

    batch2 item 5: telephony is split the same way as
    compute_call_attempt_counts - inbound/outbound/logged-by-agent, never
    merged into one total - so this panel can't claim a direction the data
    doesn't have either. "Logged attempts" (rnr_attempt entries) is a
    separate SOP concept from call counts and is unchanged.
    """
    since = coerce_datetime(lead.get("rnr_entered_at_dt"))
    attempts_by_agent: Dict[str, int] = {}
    telephony_inbound = 0
    telephony_outbound = 0
    calls_logged_by_agent = 0
    for entry in lead.get("context_updates") or []:
        if not isinstance(entry, dict) or not _entry_since(entry, since):
            continue
        if entry.get("source") == "csv_import":
            continue
        etype = (entry.get("type") or "").strip().lower()
        if etype == "rnr_attempt":
            actor = (
                entry.get("actor_name")
                or entry.get("agent")
                or entry.get("actor_user_id")
                or "Unknown"
            )
            actor = str(actor).strip() or "Unknown"
            attempts_by_agent[actor] = attempts_by_agent.get(actor, 0) + 1
        elif etype == "call":
            if entry.get("mcube_call_id"):
                direction = (entry.get("direction") or "").strip().lower()
                if direction == "outbound":
                    telephony_outbound += 1
                else:
                    telephony_inbound += 1
            else:
                calls_logged_by_agent += 1
    return {
        "rnr_attempts_by_agent": attempts_by_agent,
        "rnr_attempts_total": sum(attempts_by_agent.values()),
        "rnr_telephony_inbound": telephony_inbound,
        "rnr_telephony_outbound": telephony_outbound,
        "rnr_calls_logged_by_agent": calls_logged_by_agent,
    }
