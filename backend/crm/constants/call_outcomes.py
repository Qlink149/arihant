"""Single source of truth for Contacted/Nurturing logged call outcomes (SOP 5.3)."""
from __future__ import annotations

from typing import Dict, FrozenSet, List, Optional

OUTCOME_INTERESTED = "Interested"
OUTCOME_NEEDS_TIME = "Needs Time"
OUTCOME_CALL_BACK_LATER = "Call Back Later"
OUTCOME_FOLLOW_UP_SCHEDULED = "Follow-up Scheduled"
OUTCOME_SWITCHED_OFF = "Switched Off"
OUTCOME_RNR = "RNR"
OUTCOME_OTHERS = "Others"
OUTCOME_NOT_INTERESTED = "Not Interested"

OUTCOME_GROUP_POSITIVE = "positive"
OUTCOME_GROUP_NEUTRAL = "neutral"
OUTCOME_GROUP_NEGATIVE = "negative"

OUTCOME_GROUPS: Dict[str, str] = {
    OUTCOME_INTERESTED: OUTCOME_GROUP_POSITIVE,
    OUTCOME_NEEDS_TIME: OUTCOME_GROUP_NEUTRAL,
    OUTCOME_CALL_BACK_LATER: OUTCOME_GROUP_NEUTRAL,
    OUTCOME_FOLLOW_UP_SCHEDULED: OUTCOME_GROUP_NEUTRAL,
    OUTCOME_SWITCHED_OFF: OUTCOME_GROUP_NEUTRAL,
    OUTCOME_RNR: OUTCOME_GROUP_NEUTRAL,
    OUTCOME_OTHERS: OUTCOME_GROUP_NEUTRAL,
    OUTCOME_NOT_INTERESTED: OUTCOME_GROUP_NEGATIVE,
}

ALLOWED_LOGGED_OUTCOMES: FrozenSet[str] = frozenset(OUTCOME_GROUPS)
ALLOWED_OUTCOME_STATUSES: FrozenSet[str] = frozenset({"contacted", "nurturing"})
NEUTRAL_OUTCOMES: FrozenSet[str] = frozenset(
    name for name, group in OUTCOME_GROUPS.items() if group == OUTCOME_GROUP_NEUTRAL
)


def outcome_values_in_order() -> List[str]:
    return [
        OUTCOME_INTERESTED,
        OUTCOME_NEEDS_TIME,
        OUTCOME_CALL_BACK_LATER,
        OUTCOME_FOLLOW_UP_SCHEDULED,
        OUTCOME_SWITCHED_OFF,
        OUTCOME_RNR,
        OUTCOME_OTHERS,
        OUTCOME_NOT_INTERESTED,
    ]


def normalize_logged_outcome(value: str | None) -> str:
    raw = (value or "").strip()
    for name in ALLOWED_LOGGED_OUTCOMES:
        if raw.lower() == name.lower():
            return name
    return raw


def outcome_group(value: str | None) -> str | None:
    normalized = normalize_logged_outcome(value)
    return OUTCOME_GROUPS.get(normalized)


def last_nurture_outcomes(
    context_updates: Optional[List[dict]],
    *,
    since=None,
    extra_outcome: Optional[str] = None,
) -> List[str]:
    """Outcomes logged in the current Nurturing stay, oldest to newest."""
    from crm.utils.helpers import coerce_datetime

    since_dt = coerce_datetime(since) if since is not None else None
    if since_dt is not None and since_dt.tzinfo is None:
        from datetime import timezone

        since_dt = since_dt.replace(tzinfo=timezone.utc)
    out: List[str] = []
    for entry in context_updates or []:
        if not isinstance(entry, dict):
            continue
        etype = (entry.get("type") or "").strip().lower()
        if etype != "logged_outcome":
            continue
        ts = coerce_datetime(entry.get("timestamp_dt")) or coerce_datetime(entry.get("timestamp"))
        if since_dt is not None:
            if not ts:
                continue
            if ts.tzinfo is None:
                from datetime import timezone

                ts = ts.replace(tzinfo=timezone.utc)
            if ts < since_dt:
                continue
        normalized = normalize_logged_outcome(entry.get("outcome") or entry.get("logged_outcome"))
        if normalized in ALLOWED_LOGGED_OUTCOMES:
            out.append(normalized)
    extra = normalize_logged_outcome(extra_outcome)
    if extra in ALLOWED_LOGGED_OUTCOMES:
        out.append(extra)
    return out


def last_three_are_neutral(outcomes: List[str]) -> bool:
    if len(outcomes) < 3:
        return False
    tail = outcomes[-3:]
    return all(outcome_group(name) == OUTCOME_GROUP_NEUTRAL for name in tail)
