"""Tests for sales team dashboard aggregation (negotiation replaces dormant)."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from crm.api.v1.endpoints import analytics as analytics_module


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
