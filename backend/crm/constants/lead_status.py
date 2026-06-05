"""Shared SLA-aligned lead status labels and closed-status matching."""

import re

UI_LEAD_STATUSES = [
    "New",
    "RNR",
    "Contacted",
    "Nurturing",
    "Site Visit Scheduled",
    "Visit Completed",
    "SV Completed – Follow Up",
    "Negotiation",
    "Gone Cold",
    "Future Prospect",
    "Re-engaged",
    "Closed Won",
    "Closed Lost",
]

# Canonical closed/terminal statuses (SLA exclusion + dashboards)
CLOSED_LEAD_STATUS_REGEX = re.compile(
    r"closed|booked|advance paid|dropped|junk|unqualified",
    re.IGNORECASE,
)

_RE_SV_FOLLOWUP = re.compile(r"sv completed.{0,10}follow.?up", re.IGNORECASE)
SV_FOLLOWUP_STATUS_QUERY = {"$regex": _RE_SV_FOLLOWUP.pattern, "$options": "i"}

NURTURING_STATUS = "Nurturing"
NURTURE_LABELS = ("Hot", "Warm")


def terminal_exclusion_clause() -> dict:
    """Mongo filter fragment: lead_status is not a terminal/closed stage."""
    return {"$not": {"$regex": CLOSED_LEAD_STATUS_REGEX.pattern, "$options": "i"}}


def is_terminal_lead_status(status: str | None) -> bool:
    if not status:
        return False
    return bool(CLOSED_LEAD_STATUS_REGEX.search(str(status).strip()))


def is_sv_followup_status(status: str | None) -> bool:
    if not status:
        return False
    return bool(_RE_SV_FOLLOWUP.search(str(status).strip()))
