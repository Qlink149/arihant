"""Per-project inbound assignment pools (emails) and hop order.

Users are resolved from Mongo at assign time. Missing / inactive identities are skipped.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Set

from crm.core.state import resolve_lead_project_key

DEFAULT_POOL_KEY = "_default"

ANUSHA_EMAIL = "anusha@arihants.co.in"
GOWTHAM_EMAIL = "gowtham@arihants.co.in"
NARENDRAN_EMAIL = "narendran@arihants.co.in"
MALATHY_EMAIL = "malathy@arihants.co.in"
JIGAR_EMAIL = "jigar@arihants.co.in"
HARISH_EMAIL = "harish@arihants.co.in"
SHARIFF_EMAIL = "shariff@arihants.co.in"
ROSHNI_EMAIL = "roshni@arihantspaces.com"
ANANTHRAMAN_EMAIL = "anantharaman@arihants.co.in"

# primary_mode: "rr" (fewest open New among primary) | "fixed" (first eligible in list)
# fallback_mode:
#   alternate_primary_then_chain — other primary first, then fallback_chain in order
#   other_primary — the primary member who is not current owner
#   rr_list — fewest open New among remaining fallback_chain members
PROJECT_ASSIGNMENT_POOLS: Dict[str, dict] = {
    "reserve-16": {
        "primary": [ANUSHA_EMAIL, GOWTHAM_EMAIL],
        "primary_mode": "rr",
        "fallback_chain": [
            NARENDRAN_EMAIL,
            MALATHY_EMAIL,
            JIGAR_EMAIL,
            ANANTHRAMAN_EMAIL,
        ],
        "fallback_mode": "alternate_primary_then_chain",
        "escalate": True,
    },
    "krsna": {
        "primary": [HARISH_EMAIL, MALATHY_EMAIL],
        "primary_mode": "rr",
        "fallback_chain": [],
        "fallback_mode": "other_primary",
        "escalate": True,
    },
    "mira": {
        "primary": [SHARIFF_EMAIL, HARISH_EMAIL],
        "primary_mode": "rr",
        "fallback_chain": [],
        "fallback_mode": "other_primary",
        "escalate": True,
    },
    "vivriti": {
        "primary": [ANUSHA_EMAIL],
        "primary_mode": "fixed",
        "fallback_chain": [NARENDRAN_EMAIL, MALATHY_EMAIL],
        "fallback_mode": "rr_list",
        "escalate": True,
    },
    "melange": {
        "primary": [ROSHNI_EMAIL],
        "primary_mode": "fixed",
        "fallback_chain": [],
        "fallback_mode": None,
        "escalate": False,
    },
    "vipassana": {
        "primary": [ROSHNI_EMAIL],
        "primary_mode": "fixed",
        "fallback_chain": [],
        "fallback_mode": None,
        "escalate": False,
    },
    DEFAULT_POOL_KEY: {
        "primary": [ANUSHA_EMAIL, GOWTHAM_EMAIL],
        "primary_mode": "rr",
        "fallback_chain": [],
        "fallback_mode": "other_primary",
        "escalate": True,
    },
}


def normalize_email(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def pool_key_for_lead(lead: Optional[dict]) -> str:
    """Canonical pool key. Unknown / empty project → default Anusha/Gowtham pool."""
    if lead and lead.get("pool_key"):
        existing = str(lead.get("pool_key") or "").strip()
        if existing in PROJECT_ASSIGNMENT_POOLS:
            return existing
    key = resolve_lead_project_key(lead or {})
    if key and key in PROJECT_ASSIGNMENT_POOLS:
        return key
    return DEFAULT_POOL_KEY


def get_pool(pool_key: Optional[str]) -> dict:
    if pool_key and pool_key in PROJECT_ASSIGNMENT_POOLS:
        return PROJECT_ASSIGNMENT_POOLS[pool_key]
    return PROJECT_ASSIGNMENT_POOLS[DEFAULT_POOL_KEY]


def pool_escalates(pool_key: Optional[str]) -> bool:
    return bool(get_pool(pool_key).get("escalate"))


def _ordered_unique(emails: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for raw in emails:
        email = normalize_email(raw)
        if not email or email in seen:
            continue
        seen.add(email)
        out.append(email)
    return out


def fallback_ordered_emails(pool: dict) -> List[str]:
    """Full fallback hop order (current owner still present; caller filters history)."""
    primary = _ordered_unique(pool.get("primary") or [])
    chain = _ordered_unique(pool.get("fallback_chain") or [])
    mode = pool.get("fallback_mode")
    if mode == "alternate_primary_then_chain":
        primary_set = set(primary)
        return primary + [e for e in chain if e not in primary_set]
    if mode == "other_primary":
        return list(primary)
    if mode == "rr_list":
        return list(chain)
    return []


def next_hop_emails(
    pool: dict,
    history_emails: Sequence[str],
    *,
    initial: bool = False,
) -> List[str]:
    """Emails still to try, excluding anyone already in assignment history."""
    hist = {normalize_email(e) for e in history_emails if e}
    if initial:
        ordered = _ordered_unique(pool.get("primary") or [])
    else:
        ordered = fallback_ordered_emails(pool)
    return [e for e in ordered if e not in hist]


def hop_uses_round_robin(pool: dict, *, initial: bool) -> bool:
    if initial:
        return (pool.get("primary_mode") or "rr") == "rr"
    return pool.get("fallback_mode") == "rr_list"
