"""Unit tests for #53/#54: append-only site visit completion events + report."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.services.site_visit_events import (
    build_site_visit_report,
    build_site_visit_report_filter,
    record_site_visit_event,
    resolve_report_window,
)


# ---------------------------------------------------------------------------
# record_site_visit_event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_site_visit_event_captures_lead_snapshot(monkeypatch):
    mock_db = MagicMock()
    mock_db.site_visit_events.insert_one = AsyncMock()
    import crm.services.site_visit_events as sve

    monkeypatch.setattr(sve, "db", mock_db)

    lead = {
        "first_name": "Priya",
        "last_name": "S",
        "phone": "9876543210",
        "project": "ECR - Reserve 16",
        "projects": ["ECR - Reserve 16"],
        "assigned_user_id": "rep-1",
        "assigned_to_name": "Rep One",
    }
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    actor = {"id": "admin-1", "full_name": "Admin"}

    event_id = await record_site_visit_event("lead-1", lead, actor=actor, completed_at_dt=now)

    assert event_id
    mock_db.site_visit_events.insert_one.assert_awaited_once()
    event = mock_db.site_visit_events.insert_one.call_args[0][0]
    assert event["lead_id"] == "lead-1"
    assert event["completed_at_dt"] == now
    assert event["project"] == "ECR - Reserve 16"
    assert event["projects"] == ["ECR - Reserve 16"]
    assert event["assigned_user_id"] == "rep-1"
    assert event["actor_name"] == "Admin"
    assert event["lead_name"] == "Priya S"
    assert event["phone"] == "9876543210"


@pytest.mark.asyncio
async def test_record_site_visit_event_never_raises_on_db_error(monkeypatch):
    mock_db = MagicMock()
    mock_db.site_visit_events.insert_one = AsyncMock(side_effect=RuntimeError("boom"))
    import crm.services.site_visit_events as sve

    monkeypatch.setattr(sve, "db", mock_db)

    # Must not raise even if the write fails — logging is best-effort.
    event_id = await record_site_visit_event(
        "lead-2", {}, actor={"id": "u1", "full_name": "U"}, completed_at_dt=datetime.now(timezone.utc)
    )
    assert event_id


# ---------------------------------------------------------------------------
# resolve_report_window / build_site_visit_report_filter
# ---------------------------------------------------------------------------

def test_resolve_report_window_month_preset_is_ist_calendar_month():
    now = datetime(2026, 6, 15, 3, 0, 0, tzinfo=timezone.utc)  # ~08:30 IST June 15
    window = resolve_report_window(preset="month", now_dt=now)
    assert window["from"] is not None and window["to"] is not None
    assert window["from"] < window["to"]


def test_resolve_report_window_week_preset():
    now = datetime(2026, 6, 15, 3, 0, 0, tzinfo=timezone.utc)
    window = resolve_report_window(preset="week", now_dt=now)
    assert (window["to"] - window["from"]).days == 7


def test_resolve_report_window_quarter_preset():
    now = datetime(2026, 6, 15, 3, 0, 0, tzinfo=timezone.utc)
    window = resolve_report_window(preset="quarter", now_dt=now)
    assert window["from"] < window["to"]


def test_resolve_report_window_explicit_date_range():
    window = resolve_report_window(date_from="2026-06-01", date_to="2026-06-10")
    assert window["from"] is not None
    assert window["to"] is not None
    assert window["from"] < window["to"]


def test_resolve_report_window_no_args_returns_none_bounds():
    window = resolve_report_window()
    assert window == {"from": None, "to": None}


def test_build_site_visit_report_filter_with_owner_and_window():
    window = resolve_report_window(date_from="2026-06-01", date_to="2026-06-10")
    filt = build_site_visit_report_filter(window=window, sales_owner_id="rep-9")
    assert filt["assigned_user_id"] == "rep-9"
    assert "completed_at_dt" in filt
    assert "$gte" in filt["completed_at_dt"]
    assert "$lt" in filt["completed_at_dt"]


def test_build_site_visit_report_filter_empty_window_no_range_clause():
    filt = build_site_visit_report_filter(window={"from": None, "to": None})
    assert "completed_at_dt" not in filt


# ---------------------------------------------------------------------------
# build_site_visit_report (aggregation)
# ---------------------------------------------------------------------------

class _FakeAggCursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, n):
        return self._rows[:n]


@pytest.mark.asyncio
async def test_build_site_visit_report_groups_by_project(monkeypatch):
    mock_db = MagicMock()
    mock_db.site_visit_events.aggregate = MagicMock(
        return_value=_FakeAggCursor(
            [
                {"_id": "ECR - Reserve 16", "count": 5},
                {"_id": "Unspecified", "count": 2},
            ]
        )
    )
    import crm.services.site_visit_events as sve

    monkeypatch.setattr(sve, "db", mock_db)

    report = await build_site_visit_report(window={"from": None, "to": None})
    assert report["total"] == 7
    assert report["by_project"][0]["project"] == "ECR - Reserve 16"
    assert report["by_project"][0]["count"] == 5
