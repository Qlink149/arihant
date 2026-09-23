"""Logged outcomes (SOP 5.3) and Hot/Warm from history (SOP 5.4)."""

from crm.constants.call_outcomes import (
    ALLOWED_LOGGED_OUTCOMES,
    last_nurture_outcomes,
    last_three_are_neutral,
    normalize_logged_outcome,
    outcome_values_in_order,
)


def test_eight_outcomes():
    assert len(ALLOWED_LOGGED_OUTCOMES) == 8
    assert len(outcome_values_in_order()) == 8
    assert normalize_logged_outcome("needs time") == "Needs Time"


def test_last_three_neutral_ignores_prior_stay():
    from datetime import datetime, timezone, timedelta

    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    since = now - timedelta(days=1)
    updates = [
        {"type": "logged_outcome", "outcome": "Needs Time", "timestamp_dt": since - timedelta(days=5)},
        {"type": "logged_outcome", "outcome": "Switched Off", "timestamp_dt": since + timedelta(hours=1)},
        {"type": "logged_outcome", "outcome": "RNR", "timestamp_dt": since + timedelta(hours=2)},
        {"type": "logged_outcome", "outcome": "Call Back Later", "timestamp_dt": since + timedelta(hours=3)},
    ]
    hist = last_nurture_outcomes(updates, since=since)
    assert hist == ["Switched Off", "RNR", "Call Back Later"]
    assert last_three_are_neutral(hist)
    hist2 = last_nurture_outcomes(updates, since=since, extra_outcome="Interested")
    assert not last_three_are_neutral(hist2)
