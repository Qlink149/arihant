"""Unit tests for lead overview KPI filters (no database)."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from crm.services.lead_analytics_queries import active_pipeline_filter
from crm.services.lead_follow_up import follow_up_today_clause, missed_follow_up_clause
from crm.services.lead_overview_service import (
    METRIC_SPECS,
    build_metric_context,
    ist_day_window,
    metric_filter_for_key,
    sv_conducted_status_clause,
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
    ctx["follow_up_today_task_lead_ids"] = ["lead-task-1"]
    filt = metric_filter_for_key("follow_up_today", ctx)
    filt_str = str(filt)
    assert "2026-05-26" in filt_str
    assert "$or" in filt_str
    assert "$not" in filt_str


def test_metric_filter_missed_follow_up_before_today():
    ctx = build_metric_context(
        {},
        uid="u1",
        name="Rep",
        is_manager=False,
        now_dt=datetime(2026, 5, 26, 6, 30, 0, tzinfo=timezone.utc),
    )
    ctx["missed_follow_up_task_lead_ids"] = ["lead-overdue-1"]
    filt = metric_filter_for_key("missed_follow_up", ctx)
    filt_str = str(filt)
    assert "$lt" in filt_str
    assert "2026-05-26" in filt_str
    assert "lead-overdue-1" in filt_str


def test_active_pipeline_filter_matches_canonical_statuses():
    filt = active_pipeline_filter()
    assert "contacted" in str(filt)
    assert "nurturing" in str(filt)
    assert "negotiation" in str(filt)


def test_qualified_leads_uses_rep_scope_and_active_pipeline():
    ctx = build_metric_context(
        {"assigned_user_id": "u1"},
        uid="u1",
        name="Rep",
        is_manager=False,
    )
    filt = metric_filter_for_key("active_pipeline", ctx)
    assert "assigned_user_id" in str(filt)
    assert "contacted" in str(filt)


def test_qualified_leads_alias_resolves_to_active_pipeline():
    ctx = build_metric_context(
        {"assigned_user_id": "u1"},
        uid="u1",
        name="Rep",
        is_manager=False,
    )
    assert metric_filter_for_key("qualified_leads", ctx) == metric_filter_for_key("active_pipeline", ctx)


def test_follow_up_clauses_exclude_gone_cold():
    ctx = build_metric_context({}, uid="u1", name="Rep", is_manager=False, now_dt=datetime(2026, 5, 26, 6, 30, 0, tzinfo=timezone.utc))
    today = follow_up_today_clause(ctx, [])
    assert "gone" in str(today).lower() and "cold" in str(today).lower()


def test_follow_up_clauses_union_task_lead_ids():
    ctx = build_metric_context({}, uid="u1", name="Rep", is_manager=False, now_dt=datetime(2026, 5, 26, 6, 30, 0, tzinfo=timezone.utc))
    today = follow_up_today_clause(ctx, ["lid-1"])
    missed = missed_follow_up_clause(ctx, ["lid-2"])
    today_str = str(today)
    missed_str = str(missed)
    assert "$or" in today_str
    assert "$or" in missed_str
    assert "lid-1" in today_str
    assert "lid-2" in missed_str


def test_sv_conducted_includes_follow_up_stages():
    clause = sv_conducted_status_clause()
    clause_str = str(clause)
    assert "visit" in clause_str.lower() and "completed" in clause_str.lower()
    assert "sv follow-up 1" in clause_str.lower()


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


def test_all_metrics_defined_including_negotiation_and_qualified():
    keys = {s["key"] for s in METRIC_SPECS}
    expected = {
        "active_pipeline",
        "all_leads",
        "todays_leads",
        "follow_up_today",
        "missed_follow_up",
        "rnr",
        "todays_site_visits",
        "sv_conducted",
        "negotiation",
        "junk",
        "gone_cold",
        "re_engaged",
        "leads_received",
        "leads_transferred",
    }
    assert keys == expected


def test_metric_filter_negotiation_status():
    ctx = build_metric_context({}, uid="u1", name="Rep", is_manager=False)
    filt = metric_filter_for_key("negotiation", ctx)
    assert "negotiat" in str(filt)


def test_transfer_metrics_use_lead_transfers_collection():
    received = next(s for s in METRIC_SPECS if s["key"] == "leads_received")
    transferred = next(s for s in METRIC_SPECS if s["key"] == "leads_transferred")
    assert received["collection"] == "transfers"
    assert transferred["collection"] == "transfers"
