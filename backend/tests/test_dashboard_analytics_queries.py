"""Tests for admin dashboard cohort vs snapshot query split and org-wide operational counts."""

from datetime import datetime, timezone

from crm.services.lead_analytics_queries import (
    ORG_WIDE_DASHBOARD_METRICS,
    build_dashboard_base_query,
    build_dashboard_snapshot_query,
    created_since_filter,
)
from crm.services.lead_overview_service import metric_filter_for_key, build_metric_context


def test_snapshot_query_project_only():
    q = build_dashboard_snapshot_query(project="ECR - Reserve 16")
    assert "project" in q
    assert build_dashboard_snapshot_query(project="all") == {}
    assert build_dashboard_snapshot_query(project=None) == {}


def test_cohort_query_includes_days_and_project():
    q = build_dashboard_base_query(days=7, project="OMR - Vivriti")
    assert "project" in str(q)
    assert "created_at_dt" in str(q) or "$or" in str(q)


def test_cohort_and_snapshot_diverge_with_time_filter():
    cohort = build_dashboard_base_query(days=7, project="ECR - Reserve 16")
    snapshot = build_dashboard_snapshot_query(project="ECR - Reserve 16")
    assert cohort != snapshot
    assert "created_at_dt" in str(cohort) or created_since_filter(7).keys()


def test_org_wide_metrics_include_operational_keys():
    assert "missed_follow_up" in ORG_WIDE_DASHBOARD_METRICS
    assert "todays_site_visits" in ORG_WIDE_DASHBOARD_METRICS
    assert "rnr" in ORG_WIDE_DASHBOARD_METRICS
    assert "negotiation" in ORG_WIDE_DASHBOARD_METRICS


def test_negotiation_metric_filter():
    ctx = build_metric_context({}, uid="", name="", is_manager=False)
    filt = metric_filter_for_key("negotiation", ctx)
    assert "lead_status" in str(filt)


def test_missed_follow_up_org_wide_context():
    ctx = build_metric_context(
        {},
        uid="",
        name="",
        is_manager=False,
        now_dt=datetime(2026, 5, 26, 6, 30, 0, tzinfo=timezone.utc),
    )
    filt = metric_filter_for_key("missed_follow_up", ctx)
    assert "$lt" in str(filt)
