"""Freshworks / legacy lead_status → canonical SLA-aligned lead_status."""

from __future__ import annotations

import re
from typing import Optional, Tuple

from crm.constants.lead_status import UI_LEAD_STATUSES

# Case-insensitive exact match keys (normalized to lowercase for lookup)
_FW_TO_CANONICAL: dict[str, Tuple[str, bool]] = {
    "new": ("New", False),
    "open": ("New", False),
    "contacted": ("Contacted", False),
    "rnr 1": ("RNR", True),
    "rnr 2": ("RNR", True),
    "rnr - 1": ("RNR", True),
    "rnr - 2": ("RNR", True),
    "ring no response": ("RNR", True),
    "no response": ("RNR", True),
    "rnr": ("RNR", True),
    "follow up 1": ("Nurturing", False),
    "follow up 2": ("Nurturing", False),
    "follow up": ("Nurturing", False),
    "interested": ("Nurturing", False),
    "site visit scheduled": ("Site Visit Scheduled", False),
    "site visit completed": ("Visit Completed", False),
    "office visit completed": ("Visit Completed", False),
    "site visit": ("Site Visit Scheduled", False),
    "negotiation": ("Negotiation", False),
    "gone cold": ("Gone Cold", False),
    "project unavailability - future prospect": ("Future Prospect", False),
    "future prospect - bangalore": ("Future Prospect", False),
    "advance paid": ("Closed Won", False),
    "awaiting completion": ("Closed Won", False),
    "handed over": ("Closed Won", False),
    "occupied": ("Closed Won", False),
    "won": ("Closed Won", False),
    "dropped": ("Closed Lost", False),
    "churned": ("Closed Lost", False),
    "rental": ("Closed Lost", False),
    "junk": ("Closed Lost", False),
    "unqualified": ("Closed Lost", False),
    "lost": ("Closed Lost", False),
}

_LEGACY_BUCKETS = frozenset({"open", "follow up", "site visit", "won", "lost"})

_CANONICAL_SET = frozenset(s.lower() for s in UI_LEAD_STATUSES)


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def fw_status_to_canonical(fw_status: Optional[str]) -> Tuple[str, bool]:
    """Map a Freshworks Status label to (canonical lead_status, is_rnr)."""
    key = _norm(fw_status)
    if not key:
        return "New", False
    if key in _FW_TO_CANONICAL:
        return _FW_TO_CANONICAL[key]
    return "New", False


def resolve_imported_lead_status(
    lead_status: Optional[str],
    original_fw_status: Optional[str] = None,
) -> Tuple[str, bool]:
    """
    Resolve canonical lead_status for an imported lead.
    Prefers original_fw_status when present; handles legacy bucket placeholders.
    """
    fw = (original_fw_status or "").strip()
    ls = (lead_status or "").strip()
    fw_key = _norm(fw)
    ls_key = _norm(ls)

    if fw_key:
        canonical, is_rnr = fw_status_to_canonical(fw)
        return canonical, is_rnr

    if ls_key in _LEGACY_BUCKETS:
        return fw_status_to_canonical(ls)

    if ls_key in _CANONICAL_SET:
        is_rnr = ls_key == "rnr"
        return ls if ls else "New", is_rnr

    if ls_key in _FW_TO_CANONICAL:
        return _FW_TO_CANONICAL[ls_key]

    return fw_status_to_canonical(ls)


def is_already_canonical(lead_status: Optional[str]) -> bool:
    return _norm(lead_status) in _CANONICAL_SET


def migration_match_regex(old_label: str) -> dict:
    """Mongo $regex filter for an old status label (case-insensitive exact)."""
    escaped = re.escape(old_label.strip())
    return {"$regex": rf"^\s*{escaped}\s*$", "$options": "i"}


# Distinct old labels used for per-rule migration updates (display order)
MIGRATION_OLD_LABELS: list[str] = [
    "New",
    "Open",
    "Contacted",
    "RNR 1",
    "RNR 2",
    "RNR - 1",
    "RNR - 2",
    "Ring No Response",
    "No Response",
    "RNR",
    "Follow Up 1",
    "Follow Up 2",
    "Follow Up",
    "Interested",
    "Site Visit Scheduled",
    "Site Visit Completed",
    "Office Visit Completed",
    "Site Visit",
    "Negotiation",
    "Gone Cold",
    "Project Unavailability - Future prospect",
    "Future Prospect - Bangalore",
    "Advance Paid",
    "Awaiting Completion",
    "Handed over",
    "Occupied",
    "Won",
    "Dropped",
    "Churned",
    "Rental",
    "Junk",
    "Unqualified",
    "Lost",
]
