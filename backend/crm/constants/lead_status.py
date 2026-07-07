"""Shared SLA-aligned lead status labels and closed-status matching."""

import re

UI_LEAD_STATUSES = [
    "New",
    "RNR",
    "Contacted",
    "Nurturing",
    "Interested",
    "Site Visit Scheduled",
    "Visit Completed",
    "SV Follow-up 1",
    "SV Follow-up 2",
    "Negotiation",
    "Gone Cold",
    "Future Prospect",
    "Re-engaged",
    "Junk",
    "Unqualified",
    "Closed Won",
    "Closed Lost",
]

# Canonical closed/terminal statuses (SLA exclusion + dashboards)
CLOSED_LEAD_STATUS_REGEX = re.compile(
    r"closed|booked|advance paid|dropped|junk|unqualified",
    re.IGNORECASE,
)

_RE_SV_FOLLOWUP = re.compile(r"sv completed.{0,10}follow.?up", re.IGNORECASE)
_RE_SV_FOLLOWUP_1 = re.compile(r"sv follow-up 1", re.IGNORECASE)
_RE_SV_FOLLOWUP_2 = re.compile(r"sv follow-up 2", re.IGNORECASE)
SV_FOLLOWUP_STATUS_QUERY = {"$regex": _RE_SV_FOLLOWUP.pattern, "$options": "i"}
SV_FOLLOWUP_1_STATUS_QUERY = {"$regex": _RE_SV_FOLLOWUP_1.pattern, "$options": "i"}
SV_FOLLOWUP_2_STATUS_QUERY = {"$regex": _RE_SV_FOLLOWUP_2.pattern, "$options": "i"}

INTERESTED_STATUS = "Interested"
NURTURING_STATUS = "Nurturing"
NURTURE_LABELS = ("Hot", "Warm")


def terminal_exclusion_clause() -> dict:
    """Mongo filter fragment: lead_status is not a terminal/closed stage."""
    return {"$not": {"$regex": CLOSED_LEAD_STATUS_REGEX.pattern, "$options": "i"}}


def sla_paused_exclusion_clause() -> dict:
    """Mongo filter fragment: lead is eligible for SLA (not on historical import hold)."""
    return {"$ne": True}


def is_terminal_lead_status(status: str | None) -> bool:
    if not status:
        return False
    return bool(CLOSED_LEAD_STATUS_REGEX.search(str(status).strip()))

def is_interested_status(status: str | None) -> bool:
    if not status:
        return False
    return str(status).strip().lower() == INTERESTED_STATUS.lower()


def is_sv_followup_status(status: str | None) -> bool:
    if not status:
        return False
    s = str(status).strip()
    if is_sv_followup_1_status(s) or is_sv_followup_2_status(s):
        return False
    return bool(_RE_SV_FOLLOWUP.search(s))


def is_sv_followup_1_status(status: str | None) -> bool:
    if not status:
        return False
    return bool(_RE_SV_FOLLOWUP_1.search(str(status).strip()))


def is_sv_followup_2_status(status: str | None) -> bool:
    if not status:
        return False
    return bool(_RE_SV_FOLLOWUP_2.search(str(status).strip()))
