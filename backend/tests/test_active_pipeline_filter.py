"""Tests for active pipeline cohort filter and IST date boundaries."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from crm.services.lead_analytics_queries import (
    _parse_ymd_boundary,
    active_pipeline_filter,
    qualified_leads_filter,
)

IST = ZoneInfo("Asia/Kolkata")


def test_active_pipeline_filter_excludes_unqualified():
    filt = active_pipeline_filter()
    assert qualified_leads_filter() == filt
    assert "unqualified" not in str(filt).lower() or "^(contacted" in str(filt)


def test_parse_ymd_boundary_uses_ist_midnight():
    start = _parse_ymd_boundary("2026-06-17", end_of_day=False)
    end = _parse_ymd_boundary("2026-06-17", end_of_day=True)
    assert start is not None and end is not None
    assert start.astimezone(IST).hour == 0
    assert end.astimezone(IST).hour == 23
