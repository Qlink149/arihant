"""MCUBE Classic inbound status maps and helpers."""

from __future__ import annotations

import re
from typing import Tuple

# dialstatus (inbound Classic / live hangup) → (normalized, is_answered)
INBOUND_DIALSTATUS_MAP = {
    "answer": ("ANSWERED", True),
    "cancel": ("CANCELLED", False),
    "executive busy": ("BUSY_AGENT", False),
    "busy": ("BUSY_CUSTOMER", False),
    "noanswer": ("NO_ANSWER", False),
    "no answer": ("NO_ANSWER", False),
}

MISSED_SET = frozenset({"CANCELLED", "BUSY_AGENT", "BUSY_CUSTOMER", "NO_ANSWER"})
TERMINAL_STATUSES = frozenset(
    {"ANSWERED", "CANCELLED", "BUSY_AGENT", "BUSY_CUSTOMER", "NO_ANSWER", "UNKNOWN"}
)

# Keys redacted from persisted raw payloads
REDACT_PAYLOAD_KEYS = frozenset({"apikey", "api_key", "api-key"})


def _collapse(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip().lower())


def normalize_inbound_dialstatus(raw: str | None) -> Tuple[str, bool]:
    """Return (normalized_status, is_answered). Unknown → UNKNOWN, False."""
    key = _collapse(raw or "")
    if not key:
        return "UNKNOWN", False
    # Strip spaces for NoAnswer variants already handled; also try compact form
    compact = key.replace(" ", "")
    hit = INBOUND_DIALSTATUS_MAP.get(key) or INBOUND_DIALSTATUS_MAP.get(compact)
    if hit:
        return hit
    return "UNKNOWN", False


def is_terminal_status(normalized: str) -> bool:
    return (normalized or "").upper() in TERMINAL_STATUSES and (normalized or "").upper() != "IN_PROGRESS"


def is_missed_status(normalized: str) -> bool:
    return (normalized or "").upper() in MISSED_SET
