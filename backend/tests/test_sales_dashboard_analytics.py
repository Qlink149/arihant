"""Tests for sales team dashboard aggregation (negotiation replaces dormant)."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from crm.api.v1.endpoints import analytics as analytics_module


def test_contacted_regex_in_sales_metrics_stages():
    stages = analytics_module._sales_metrics_stages()
    add_fields = stages[2]["$addFields"]
    contacted = add_fields["contacted"]["$cond"][0]["$regexMatch"]
    assert contacted["regex"] == r"^contacted$"
    assert contacted["input"] == "$ls"


def test_deals_won_and_lost_in_sales_metrics_stages():
    stages = analytics_module._sales_metrics_stages()
    add_fields = stages[2]["$addFields"]
    assert "deals_won" in add_fields
    assert "deals_lost" in add_fields
    won = add_fields["deals_won"]["$cond"][0]["$regexMatch"]["regex"]
    lost = add_fields["deals_lost"]["$cond"][0]["$regexMatch"]["regex"]
    assert "closed" in won
    assert "lost" in lost


def test_negotiation_regex_in_sales_metrics_stages():
    stages = analytics_module._sales_metrics_stages()
    add_fields = stages[2]["$addFields"]
    negotiation = add_fields["negotiation"]["$cond"][0]["$regexMatch"]
    assert negotiation["regex"] == r"negotiat"
    assert negotiation["input"] == "$ls"


def test_sales_managers_totals_include_negotiation_no_dormant():
    asyncio.run(_sales_managers_totals_include_negotiation_no_dormant())


async def _sales_managers_totals_include_negotiation_no_dormant():
    main_rows = [
        {
            "_id": "Alice",
            "total": 10,
            "hot": 2,
            "warm": 3,
            "cold": 0,
            "rnr": 1,
            "site_visits": 4,
            "deals_won": 2,
            "deals_lost": 0,
            "deals_closed": 2,
            "contacted": 6,
            "negotiation": 3,
            "last_active": datetime(2026, 5, 1, tzinfo=timezone.utc),
        },
        {
            "_id": "Bob",
            "total": 5,
            "hot": 1,
            "warm": 0,
            "cold": 0,
            "rnr": 0,
            "site_visits": 1,
            "deals_won": 1,
            "deals_lost": 0,
            "deals_closed": 1,
            "contacted": 2,
            "negotiation": 1,
            "last_active": None,
        },
    ]
    status_rows = [{"_id": "Negotiation", "count": 4}]
    project_rows = [{"_id": "ECR", "count": 15}]

    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(side_effect=[main_rows, status_rows, project_rows])

    mock_db = MagicMock()
    mock_db.leads.aggregate = MagicMock(return_value=mock_cursor)

    with patch.object(analytics_module, "db", mock_db):
        managers, totals, by_status, by_project = await analytics_module._sales_managers_from_aggregation()

    assert "dormant" not in totals
    assert totals["negotiation"] == 4
    assert totals["total"] == 15
    assert totals["deals_closed"] == 3
    assert totals["deals_won"] == 3

    alice = next(m for m in managers if m["name"] == "Alice")
    assert alice["negotiation"] == 3
    assert "dormant" not in alice
    assert alice["conversion_rate"] == 20

    bob = next(m for m in managers if m["name"] == "Bob")
    assert bob["negotiation"] == 1
    assert bob["conversion_rate"] == 20

    assert mock_db.leads.aggregate.call_count == 3
    first_pipeline = mock_db.leads.aggregate.call_args_list[0][0][0]
    pipeline_str = str(first_pipeline)
    assert "dormant" not in pipeline_str.lower()
    assert "negotiat" in pipeline_str

    assert by_status == [{"name": "Negotiation", "count": 4}]
    assert by_project == [{"name": "ECR", "count": 15}]


def test_resolve_quarter_param_current_and_all():
    from crm.services.lead_analytics_queries import resolve_quarter_param

    created_from, created_to, key, label = resolve_quarter_param("all")
    assert created_from is None
    assert created_to is None
    assert key == "all"
    assert label == "All Time"

    created_from, created_to, key, label = resolve_quarter_param("2026-Q1")
    assert created_from == "2026-01-01"
    assert created_to == "2026-03-31"
    assert key == "2026-Q1"
    assert "Q1 2026" in label

    created_from, created_to, key, _ = resolve_quarter_param("current")
    assert created_from
    assert created_to
    assert "-Q" in key


def test_resolve_sales_period_filter_days_and_range():
    from crm.services.lead_analytics_queries import resolve_sales_period_filter

    filt, label = resolve_sales_period_filter(days=7)
    assert "created_at" in str(filt) or "created_at_dt" in str(filt)
    assert label == "Last 7 days"

    filt, label = resolve_sales_period_filter(created_from="2026-06-17", created_to="2026-06-17")
    assert label == "17 Jun 2026"
    assert "created_at_dt" in str(filt)


def test_sales_dashboard_ranking_sorts_and_filters_unassigned():
    asyncio.run(_sales_dashboard_ranking_sorts_and_filters_unassigned())


async def _sales_dashboard_ranking_sorts_and_filters_unassigned():
    main_rows = [
        {
            "_id": "Unassigned",
            "total": 50,
            "hot": 0,
            "warm": 0,
            "cold": 0,
            "rnr": 0,
            "site_visits": 0,
            "deals_won": 0,
            "deals_lost": 0,
            "deals_closed": 0,
            "contacted": 0,
            "negotiation": 0,
            "last_active": None,
        },
        {
            "_id": "Alice",
            "total": 10,
            "hot": 2,
            "warm": 3,
            "cold": 0,
            "rnr": 1,
            "site_visits": 4,
            "deals_won": 3,
            "deals_lost": 0,
            "deals_closed": 3,
            "contacted": 6,
            "negotiation": 1,
            "last_active": None,
        },
        {
            "_id": "Bob",
            "total": 10,
            "hot": 1,
            "warm": 0,
            "cold": 0,
            "rnr": 0,
            "site_visits": 1,
            "deals_won": 2,
            "deals_lost": 0,
            "deals_closed": 2,
            "contacted": 2,
            "negotiation": 0,
            "last_active": None,
        },
    ]
    status_rows = []
    project_rows = []

    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(side_effect=[main_rows, status_rows, project_rows])

    mock_db = MagicMock()
    mock_db.leads.aggregate = MagicMock(return_value=mock_cursor)

    mock_user = {"role": "admin", "email": "admin@test.com"}

    with patch.object(analytics_module, "db", mock_db):
        result = await analytics_module.get_sales_dashboard_ranking(
            current_user=mock_user,
            quarter="2026-Q1",
        )

    assert result["period_label"] == "Q1 2026 · Jan–Mar"
    names = [m["name"] for m in result["managers"]]
    assert "Unassigned" not in names
    assert names[0] == "Alice"
    assert names[1] == "Bob"
    assert result["managers"][0]["conversion_rate"] == 30
    assert result["managers"][1]["conversion_rate"] == 20

    first_pipeline = mock_db.leads.aggregate.call_args_list[0][0][0]
    match_stage = first_pipeline[0]["$match"]
    assert "created_at_dt" in str(match_stage)
