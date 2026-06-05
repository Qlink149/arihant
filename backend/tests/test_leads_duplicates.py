"""Tests for GET /leads/duplicates aggregation."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.lead_projections import DUPLICATE_GROUP_PUSH
from crm.services.lead_service import duplicate_groups_base_pipeline, find_duplicate_lead_groups


def test_duplicate_groups_base_pipeline_structure():
    pipeline = duplicate_groups_base_pipeline({"assigned_to": "Rep"})
    assert pipeline[0]["$match"]["normalized_phone"]["$exists"] is True
    assert pipeline[1]["$group"]["_id"] == "$normalized_phone"
    assert pipeline[1]["$group"]["leads"]["$push"] == DUPLICATE_GROUP_PUSH
    assert pipeline[2]["$match"]["count"]["$gt"] == 1


def test_find_duplicate_lead_groups_parses_aggregate_result():
    async def _run():
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            side_effect=[
                [{"n": 2}],
                [
                    {
                        "leads": [
                            {"id": "a", "normalized_phone": "+911"},
                            {"id": "b", "normalized_phone": "+911"},
                        ]
                    },
                ],
            ]
        )
        mock_db = MagicMock()
        mock_db.leads.aggregate = MagicMock(return_value=mock_cursor)

        with patch("crm.services.lead_service.db", mock_db):
            groups, total = await find_duplicate_lead_groups({}, skip=0, limit=10)

        assert total == 2
        assert len(groups) == 1
        assert len(groups[0]) == 2
        assert mock_db.leads.aggregate.call_count == 2

    asyncio.run(_run())
