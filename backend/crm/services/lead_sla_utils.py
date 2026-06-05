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
