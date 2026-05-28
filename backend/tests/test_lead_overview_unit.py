"""Unit tests for lead overview KPI filters (no database)."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from crm.services.lead_overview_service import (
    METRIC_SPECS,
    build_metric_context,
    ist_day_window,
    metric_filter_for_key,
)

IST = ZoneInfo("Asia/Kolkata")


def test_ist_day_window_midday_ist():
    # 2026-05-26 12:00 IST = 06:30 UTC
    now = datetime(2026, 5, 26, 6, 30, 0, tzinfo=timezone.utc)
    today_str, day_start, day_end = ist_day_window(now)
    assert today_str == "2026-05-26"
    assert day_start.astimezone(IST).hour == 0
    assert day_end.astimezone(IST).hour == 0
    assert (day_end - day_start).total_seconds() == 86400


def test_ist_day_window_just_before_midnight_ist():
    # 2026-05-25 23:30 IST = 18:00 UTC same calendar UTC day but IST still May 25
    now = datetime(2026, 5, 25, 18, 0, 0, tzinfo=timezone.utc)
    today_str, _, _ = ist_day_window(now)
    assert today_str == "2026-05-25"


def _find_in_filter(filt: dict, key: str) -> dict:
    if key in filt:
        return filt
    if "$and" in filt:
        for part in filt["$and"]:
            if key in part:
                return part
    return {}


def test_metric_filter_follow_up_today_uses_today_str():
    ctx = build_metric_context(
        {"assigned_user_id": "u1"},
        uid="u1",
        name="Rep",
        is_manager=False,
        now_dt=datetime(2026, 5, 26, 6, 30, 0, tzinfo=timezone.utc),
    )
    filt = metric_filter_for_key("follow_up_today", ctx)
    date_part = _find_in_filter(filt, "next_action_date")
    assert date_part["next_action_date"] == "2026-05-26"
    status_part = _find_in_filter(filt, "lead_status")
    assert "$not" in status_part["lead_status"]


def test_metric_filter_missed_follow_up_before_today():
    ctx = build_metric_context(
        {},
        uid="u1",
        name="Rep",
        is_manager=False,
        now_dt=datetime(2026, 5, 26, 6, 30, 0, tzinfo=timezone.utc),
    )
    filt = metric_filter_for_key("missed_follow_up", ctx)
    date_part = _find_in_filter(filt, "next_action_date")
    assert date_part["next_action_date"]["$lt"] == "2026-05-26"


def test_metric_filter_rnr_includes_is_rnr():
    ctx = build_metric_context({}, uid="u1", name="Rep", is_manager=False)
    filt = metric_filter_for_key("rnr", ctx)
    assert "$or" in filt
    or_clause = next(p for p in filt["$and"] if "$or" in p) if "$and" in filt else filt
    if "$and" in filt:
        rnr_part = next(p for p in filt["$and"] if "$or" in p)
        assert "is_rnr" in str(rnr_part)
    else:
        assert "$or" in filt


def test_metric_filter_unknown_returns_empty():
    ctx = build_metric_context({}, uid="u1", name="Rep", is_manager=False)
    assert metric_filter_for_key("not_a_metric", ctx) == {}


def test_all_twelve_metrics_defined():
    keys = {s["key"] for s in METRIC_SPECS}
    expected = {
        "all_leads",
        "todays_leads",
        "follow_up_today",
        "missed_follow_up",
        "rnr",
        "todays_site_visits",
        "sv_conducted",
        "junk",
        "gone_cold",
        "re_engaged",
        "leads_received",
        "leads_transferred",
    }
    assert keys == expected


def test_transfer_metrics_use_lead_transfers_collection():
    received = next(s for s in METRIC_SPECS if s["key"] == "leads_received")
    transferred = next(s for s in METRIC_SPECS if s["key"] == "leads_transferred")
    assert received["collection"] == "transfers"
    assert transferred["collection"] == "transfers"
