"""Tests for dashboard analytics $facet consolidation."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.lead_analytics_queries import (
    build_dashboard_cohort_facet_pipeline,
    count_dashboard_cohort_metrics,
)
from crm.services.lead_overview_service import (
    build_dashboard_operational_facet_pipeline,
    count_dashboard_operational_metrics,
)


def test_cohort_facet_pipeline_includes_all_branches():
    pipeline = build_dashboard_cohort_facet_pipeline({"project": "ECR"})
    assert pipeline[0]["$match"] == {"project": "ECR"}
    facet = pipeline[1]["$facet"]
    for key in ("total", "hot", "warm", "vip", "active_pipeline", "open", "lost", "dormant"):
        assert key in facet


def test_operational_facet_pipeline_uses_metric_filters():
    async def _run():
        with patch(
            "crm.services.lead_overview_service.pending_task_due_lead_ids",
            new_callable=AsyncMock,
            return_value=[],
        ):
            pipeline = await build_dashboard_operational_facet_pipeline(
                {},
                ("missed_follow_up", "rnr"),
            )
        facet = pipeline[0]["$facet"]
        assert "missed_follow_up" in facet
        assert "rnr" in facet
        assert "$match" in facet["missed_follow_up"][0]

    asyncio.run(_run())


def test_count_dashboard_cohort_metrics_parses_facet():
    async def _run():
        facet_doc = {
            "total": [{"n": 100}],
            "hot": [{"n": 5}],
            "warm": [{"n": 3}],
            "vip": [{"n": 2}],
            "active_pipeline": [{"n": 10}],
            "open": [{"n": 40}],
            "lost": [{"n": 8}],
            "dormant": [{"n": 1}],
        }
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[facet_doc])
        mock_db = MagicMock()
        mock_db.leads.aggregate = MagicMock(return_value=mock_cursor)

        with patch("crm.services.lead_analytics_queries.db", mock_db):
            counts = await count_dashboard_cohort_metrics({})

        assert counts["total_leads"] == 100
        assert counts["hot_leads"] == 5
        assert counts["dormant_leads"] == 1
        mock_db.leads.aggregate.assert_called_once()

    asyncio.run(_run())


def test_count_dashboard_operational_metrics_parses_facet():
    async def _run():
        facet_doc = {
            "missed_follow_up": [{"n": 4}],
            "rnr": [{"n": 7}],
        }
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[facet_doc])
        mock_db = MagicMock()
        mock_db.leads.aggregate = MagicMock(return_value=mock_cursor)

        with patch("crm.services.lead_overview_service.db", mock_db), patch(
            "crm.services.lead_overview_service.enrich_follow_up_task_ids",
            AsyncMock(),
        ):
            counts = await count_dashboard_operational_metrics(
                {}, ("missed_follow_up", "rnr")
            )

        assert counts["missed_follow_up"] == 4
        assert counts["rnr"] == 7

    asyncio.run(_run())
