"""Unit tests for reminder query helpers."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from crm.services.lead_overview_service import ist_tomorrow_window
from crm.services.reminder_queries import (
    rnr_status_clause,
    site_visit_tomorrow_clause,
    stale_updated_clause,
    status_clause,
)

IST = ZoneInfo("Asia/Kolkata")


def test_ist_tomorrow_window_ist_midday():
    # 2026-06-17 12:00 IST = 2026-06-17 06:30 UTC
    now = datetime(2026, 6, 17, 6, 30, tzinfo=timezone.utc)
    tomorrow_str, start_utc, end_utc = ist_tomorrow_window(now)
    assert tomorrow_str == "2026-06-18"
    assert start_utc == datetime(2026, 6, 17, 18, 30, tzinfo=timezone.utc)
    assert end_utc == datetime(2026, 6, 18, 18, 30, tzinfo=timezone.utc)


def test_status_clause_gone_cold_only():
    clause = status_clause(["Gone Cold"], default_regex="Follow Up")
    assert clause == {"lead_status": "Gone Cold"}


def test_status_clause_multiple_statuses():
    clause = status_clause(["Follow Up 1", "Follow Up 2"], default_regex="Follow Up")
    assert clause == {
        "$or": [{"lead_status": "Follow Up 1"}, {"lead_status": "Follow Up 2"}],
    }


def test_status_clause_default_regex_when_empty():
    clause = status_clause([], default_regex="Follow Up")
    assert clause == {"lead_status": {"$regex": "Follow Up", "$options": "i"}}


def test_site_visit_tomorrow_clause_includes_visit_date_dt():
    now = datetime(2026, 6, 17, 6, 30, tzinfo=timezone.utc)
    clause = site_visit_tomorrow_clause(now)
    assert "$and" in clause
    parts = {k: v for part in clause["$and"] for k, v in part.items()}
    assert "visit_date_dt" in parts
    assert parts["visit_date_dt"]["$gte"] == datetime(2026, 6, 17, 18, 30, tzinfo=timezone.utc)
    assert parts["visit_date_dt"]["$lt"] == datetime(2026, 6, 18, 18, 30, tzinfo=timezone.utc)


def test_stale_updated_clause_prefers_updated_at_dt():
    cutoff_dt = datetime(2026, 6, 10, tzinfo=timezone.utc)
    clause = stale_updated_clause(cutoff_dt, cutoff_dt.isoformat())
    assert "$or" in clause
    assert {"updated_at_dt": {"$lt": cutoff_dt}} in clause["$or"]


def test_rnr_status_clause_uses_rule_statuses_when_set():
    clause = rnr_status_clause(["RNR"])
    assert clause == {"lead_status": "RNR"}
