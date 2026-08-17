"""Unit tests for lead list query composition (dashboard drill-down parity)."""

from crm.services.lead_analytics_queries import build_created_cohort_filter
from crm.services.lead_list_query import compose_leads_list_query
from crm.services.lead_overview_service import is_overview_drill_metric


def test_compose_leads_list_query_days_uses_created_at_dt():
    q = compose_leads_list_query({}, days=30)
    assert "created_at_dt" in str(q) or "$or" in str(q)
    assert "created_at" in str(q)


def test_compose_leads_list_query_custom_range_uses_created_at_dt():
    q = compose_leads_list_query(
        {},
        created_from="2026-01-01",
        created_to="2026-01-31",
    )
    assert "created_at_dt" in str(q)


def test_compose_leads_list_query_hot_drill_shape():
    q = compose_leads_list_query(
        {},
        status="Nurturing",
        temperature="Hot",
        days=7,
        project="ECR - Reserve 16",
    )
    body = str(q)
    assert "Nurturing" in body
    assert "Hot" in body
    assert "created_at_dt" in body or "$or" in body
    assert "ECR" in body


def test_build_created_cohort_filter_days():
    filt = build_created_cohort_filter(days=15)
    assert filt
    assert "created_at_dt" in str(filt) or "$or" in str(filt)


def test_build_created_cohort_filter_range():
    filt = build_created_cohort_filter(created_from="2026-03-01", created_to="2026-03-31")
    assert "created_at_dt" in str(filt)


def test_overview_drill_metrics_include_my_dashboard_tiles():
    assert is_overview_drill_metric("rnr")
    assert is_overview_drill_metric("negotiation")
    assert is_overview_drill_metric("missed_follow_up")
    assert is_overview_drill_metric("active_pipeline")
    assert not is_overview_drill_metric("deals_won")
    assert not is_overview_drill_metric("site_visits")


def test_compose_leads_list_query_re_enquiry():
    q = compose_leads_list_query({}, re_enquiry=True)
    body = str(q)
    assert "re_enquiry" in body
