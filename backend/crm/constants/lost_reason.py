"""Canonical lost-reason picklist for Unqualified / Closed Lost leads."""

from typing import Optional

LOST_REASON_OPTIONS: tuple[str, ...] = (
    "Not able to reach",
    "Ringing no response",
    "Not interested",
    "Lost to competitor",
    "Budget",
    "Location",
    "Other Enquiry",
    "Channel Partner",
    "Possession Date mismatch",
    "Unit size",
    "Rental",
)

LOST_REASON_STATUSES = frozenset({"unqualified", "closed lost"})

_FREE_TEXT_LOST_STATUSES = frozenset({"junk", "dropped"})

_LOST_REASON_LOOKUP = {opt.casefold(): opt for opt in LOST_REASON_OPTIONS}


def is_lost_reason_status(status: str | None) -> bool:
    return (status or "").strip().casefold() in LOST_REASON_STATUSES


def is_free_text_lost_status(status: str | None) -> bool:
    return (status or "").strip().casefold() in _FREE_TEXT_LOST_STATUSES


def normalize_lost_reason(value: str | None) -> Optional[str]:
    """Return canonical option string or None if not in picklist."""
    raw = (value or "").strip()
    if not raw:
        return None
    return _LOST_REASON_LOOKUP.get(raw.casefold())
