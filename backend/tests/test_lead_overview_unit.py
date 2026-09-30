"""Unit tests for lead overview KPI filters (no database)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

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


def test_follow_up_clauses_no_longer_special_case_gone_cold():
    """batch1 #43: Gone Cold is not carved out of Follow-up Today/Missed
    anymore - the 30-day re-evaluation task must be able to resurface it,
    exactly like any other non-terminal status. Only genuine terminal
    statuses (Junk, Unqualified, Closed*, Booked, Advance Paid, Dropped)
    remain excluded."""
    ctx = build_metric_context({}, uid="u1", name="Rep", is_manager=False, now_dt=datetime(2026, 5, 26, 6, 30, 0, tzinfo=timezone.utc))
    today = follow_up_today_clause(ctx, [])
    assert "gone" not in str(today).lower()
    # Terminal exclusion (junk/unqualified/closed/booked/advance paid/dropped) still applies.
    blob = str(today).lower()
    assert "junk" in blob and "unqualified" in blob and "closed" in blob


@pytest.mark.asyncio
async def test_gone_cold_lead_with_task_due_today_appears_in_follow_up_today(monkeypatch):
    """Accept criteria: a Gone Cold lead whose re-evaluation task is due
    TODAY must match follow_up_today_clause; Junk/Closed leads never match
    regardless of a due task; no lead matches both today and missed."""
    from crm.services import lead_follow_up as lfu

    ctx = build_metric_context(
        {}, uid="u1", name="Rep", is_manager=False,
        now_dt=datetime(2026, 5, 26, 6, 30, 0, tzinfo=timezone.utc),
    )

    def matches(lead: dict, clause: dict) -> bool:
        """Minimal in-Python evaluator for the small subset of Mongo
        operators these clauses use, so we can assert against real
        lead-shaped dicts without a live Mongo."""
        import re as _re

        def _status_ok(cond):
            if "$not" in cond:
                inner = cond["$not"]
                return not _re.search(inner["$regex"], lead.get("lead_status") or "", _re.IGNORECASE)
            raise AssertionError("unexpected status clause shape")

        def _eval(c):
            if "$and" in c:
                return all(_eval(p) for p in c["$and"])
            if "$or" in c:
                return any(_eval(p) for p in c["$or"])
            if "$nor" in c:
                return not any(_eval(p) for p in c["$nor"])
            if "lead_status" in c:
                return _status_ok(c["lead_status"])
            if "next_action_date" in c:
                cond = c["next_action_date"]
                nad = lead.get("next_action_date")
                if isinstance(cond, str):
                    return nad == cond
                if "$lt" in cond:
                    if nad in (None, ""):
                        return False
                    return nad < cond["$lt"]
                raise AssertionError("unexpected next_action_date clause")
            if "id" in c:
                return lead.get("id") in c["id"]["$in"]
            raise AssertionError(f"unhandled clause: {c}")

        return _eval(clause)

    gone_cold_due_today = {"id": "gc-1", "lead_status": "Gone Cold", "next_action_date": None}
    gone_cold_not_due = {"id": "gc-2", "lead_status": "Gone Cold", "next_action_date": None}
    junk_with_task = {"id": "junk-1", "lead_status": "Junk", "next_action_date": None}
    closed_with_task = {"id": "closed-1", "lead_status": "Closed Lost", "next_action_date": None}

    # Realistic caller shape: a lead's task is either due-today or overdue,
    # never both, so it appears in exactly one of these two id lists - this
    # is what actually keeps the two queues mutually exclusive.
    due_today_ids = ["gc-1", "junk-1", "closed-1"]
    overdue_ids: list[str] = []

    today_clause = lfu.follow_up_today_clause(
        ctx, task_lead_ids=due_today_ids, missed_task_lead_ids=overdue_ids,
    )
    missed_clause = lfu.missed_follow_up_clause(ctx, task_lead_ids=overdue_ids)

    assert matches(gone_cold_due_today, today_clause) is True
    assert matches(gone_cold_not_due, today_clause) is False
    assert matches(junk_with_task, today_clause) is False
    assert matches(closed_with_task, today_clause) is False

    # Mutual exclusivity: gc-1's task is due TODAY (not overdue), so it must
    # not also show up in Missed Follow-ups.
    assert matches(gone_cold_due_today, missed_clause) is False

    # And the reverse: an overdue Gone Cold lead appears in Missed, not Today.
    gone_cold_overdue = {"id": "gc-3", "lead_status": "Gone Cold", "next_action_date": None}
    today_clause_2 = lfu.follow_up_today_clause(
        ctx, task_lead_ids=[], missed_task_lead_ids=["gc-3"],
    )
    missed_clause_2 = lfu.missed_follow_up_clause(ctx, task_lead_ids=["gc-3"])
    assert matches(gone_cold_overdue, today_clause_2) is False
    assert matches(gone_cold_overdue, missed_clause_2) is True


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
    assert "$nor" in today_str


def test_follow_up_today_excludes_overdue_signals():
    """Missed wins: overdue NAD or overdue task id must not appear in today."""
    ctx = build_metric_context(
        {},
        uid="u1",
        name="Rep",
        is_manager=False,
        now_dt=datetime(2026, 5, 26, 6, 30, 0, tzinfo=timezone.utc),
    )
    today = follow_up_today_clause(
        ctx,
        ["lead-due-today"],
        missed_task_lead_ids=["lead-overdue"],
    )
    today_s = str(today)
    assert "lead-due-today" in today_s
    assert "lead-overdue" in today_s  # listed under $nor exclude
    assert "$nor" in today_s
    assert "$lt" in today_s

    # Enrich-style dedupe: dual-signal lead only in missed task id list
    today_ids = ["lead-both", "lead-today-only"]
    missed_ids = ["lead-both", "lead-missed-only"]
    missed_set = set(missed_ids)
    today_ids = [lid for lid in today_ids if lid not in missed_set]
    assert today_ids == ["lead-today-only"]

    ctx["follow_up_today_task_lead_ids"] = today_ids
    ctx["missed_follow_up_task_lead_ids"] = missed_ids
    today_filt = metric_filter_for_key("follow_up_today", ctx)
    missed_filt = metric_filter_for_key("missed_follow_up", ctx)
    assert "lead-today-only" in str(today_filt)
    assert "lead-both" in str(missed_filt)
    assert "lead-missed-only" in str(missed_filt)


def test_follow_up_today_only_nad_today():
    ctx = build_metric_context(
        {},
        uid="u1",
        name="Rep",
        is_manager=False,
        now_dt=datetime(2026, 5, 26, 6, 30, 0, tzinfo=timezone.utc),
    )
    clause = follow_up_today_clause(ctx, None, missed_task_lead_ids=None)
    assert {"next_action_date": "2026-05-26"} in _or_branches(clause)
    assert "$nor" in str(clause)


def _or_branches(clause: dict) -> list:
    """Collect $or arrays from nested $and."""
    found = []
    if "$or" in clause:
        found.append(clause["$or"])
    for part in clause.get("$and") or []:
        if isinstance(part, dict) and "$or" in part:
            found.append(part["$or"])
    return found[0] if found else []


def test_missed_only_overdue_nad_clause():
    ctx = build_metric_context(
        {},
        uid="u1",
        name="Rep",
        is_manager=False,
        now_dt=datetime(2026, 5, 26, 6, 30, 0, tzinfo=timezone.utc),
    )
    missed = missed_follow_up_clause(ctx, None)
    assert "$lt" in str(missed)
    assert "2026-05-26" in str(missed)


def test_sv_conducted_includes_follow_up_stages():
    clause = sv_conducted_status_clause()
    clause_str = str(clause)
    assert "visit" in clause_str.lower() and "completed" in clause_str.lower()
    assert "sv follow-up 1" in clause_str.lower()


def test_metric_filter_rnr_includes_is_rnr():
    ctx = build_metric_context({}, uid="u1", name="Rep", is_manager=False)
    filt = metric_filter_for_key("rnr", ctx)
    # merge_query may nest the shared RNR clause under $and with base filters
    blob = str(filt)
    assert "is_rnr" in blob
    assert "original_fw_status" not in blob or blob.count("original_fw_status") == 0
    assert "$not" in blob  # terminal exclusion


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
        "unqualified",
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


def test_todays_leads_uses_rolling_24h_created_or_re_enquired_today():
    # #46/#48: a lead created just before midnight IST should still show up
    # the next morning within 24h, and a re-enquiry today counts too even if
    # the lead itself was created long ago.
    now = datetime(2026, 5, 26, 3, 0, 0, tzinfo=timezone.utc)  # 08:30 IST May 26
    ctx = build_metric_context({}, uid="u1", name="Rep", is_manager=False, now_dt=now)
    filt = metric_filter_for_key("todays_leads", ctx)
    blob = str(filt)
    assert "created_at_dt" in blob
    assert "re_enquired_at" in blob
    assert "$or" in blob
    # rolling window should be [now - 24h, now], not IST midnight and not open-ended
    created_clause = filt["$or"][0]
    created_dt_window = created_clause["$or"][0]["created_at_dt"]
    assert created_dt_window["$gte"] == now - timedelta(hours=24)
    assert created_dt_window["$lte"] == now
    created_str_window = created_clause["$or"][1]["$and"][1]["created_at"]
    assert created_str_window["$gte"] == (now - timedelta(hours=24)).isoformat()
    assert created_str_window["$lte"] == now.isoformat()


def test_todays_leads_excludes_future_created_at_dt():
    """Bad imports with future created_at_dt must not match the create branch."""
    now = datetime(2026, 9, 4, 6, 30, 0, tzinfo=timezone.utc)
    ctx = build_metric_context({}, uid="u1", name="Rep", is_manager=False, now_dt=now)
    filt = metric_filter_for_key("todays_leads", ctx)
    created_dt_window = filt["$or"][0]["$or"][0]["created_at_dt"]
    assert created_dt_window["$lte"] == now
    # Future date would fail $lte now while still satisfying an open-ended $gte
    future = datetime(2026, 12, 1, 15, 16, 13, tzinfo=timezone.utc)
    assert future >= created_dt_window["$gte"]
    assert not (future <= created_dt_window["$lte"])


def test_todays_leads_re_enquiry_window_matches_ist_calendar_day():
    now = datetime(2026, 5, 26, 3, 0, 0, tzinfo=timezone.utc)  # 08:30 IST May 26
    ctx = build_metric_context({}, uid="u1", name="Rep", is_manager=False, now_dt=now)
    filt = metric_filter_for_key("todays_leads", ctx)
    re_enquired_clause = filt["$or"][1]
    window = re_enquired_clause["re_enquired_at"]
    assert window["$gte"].astimezone(IST).strftime("%Y-%m-%d") == "2026-05-26"
    assert window["$gte"].astimezone(IST).hour == 0
    assert (window["$lt"] - window["$gte"]).total_seconds() == 86400


def test_transfer_metrics_use_lead_transfers_collection():
    received = next(s for s in METRIC_SPECS if s["key"] == "leads_received")
    transferred = next(s for s in METRIC_SPECS if s["key"] == "leads_transferred")
    assert received["collection"] == "transfers"
    assert transferred["collection"] == "transfers"
