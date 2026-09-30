"""batch3(item4): #51 - the VC filter-options location aggregation must
$unwind before it $trims/$groups, so a multi-select list on a lead produces
one dropdown row per distinct value instead of erroring or collapsing
distinct values together. $unwind on a legacy scalar string is a documented
MongoDB no-op (the field is treated as a one-element array), so this same
pipeline stays correct for pre-migration leads too."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import crm.services.lead_analytics_queries as laq


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, limit):
        return self._rows[:limit]


def test_location_pipeline_unwinds_before_grouping():
    captured_pipelines = []

    def fake_aggregate(pipeline):
        captured_pipelines.append(pipeline)
        return _FakeCursor([])

    mock_db = MagicMock()
    mock_db.leads.aggregate = MagicMock(side_effect=fake_aggregate)

    with patch.object(laq, "db", mock_db), patch(
        "crm.services.dashboard_scope.build_sales_owner_options", new=AsyncMock(return_value=[])
    ):
        asyncio.run(laq.fetch_lead_filter_options())

    # Second aggregate call is the location pipeline (after project_distribution_pipeline).
    location_pipeline = captured_pipelines[1]
    stage_keys = [list(stage.keys())[0] for stage in location_pipeline]
    assert "$unwind" in stage_keys
    assert stage_keys.index("$unwind") < stage_keys.index("$group")
    unwind_stage = next(s["$unwind"] for s in location_pipeline if "$unwind" in s)
    assert unwind_stage["path"] == "$location"
    assert unwind_stage["preserveNullAndEmptyArrays"] is True


def test_location_pipeline_groups_by_trimmed_location_value():
    mock_db = MagicMock()
    call_count = {"n": 0}

    def fake_aggregate(pipeline):
        call_count["n"] += 1
        if call_count["n"] == 2:
            # Simulate what Mongo's $unwind produces for a lead with
            # location: ["OMR", "Anna Nagar"] followed by one with the
            # legacy scalar "Chennai" - one row per distinct value.
            return _FakeCursor([
                {"_id": "OMR", "count": 3},
                {"_id": "Anna Nagar", "count": 1},
                {"_id": "Chennai", "count": 5},
            ])
        return _FakeCursor([])

    mock_db.leads.aggregate = MagicMock(side_effect=fake_aggregate)

    with patch.object(laq, "db", mock_db), patch(
        "crm.services.dashboard_scope.build_sales_owner_options", new=AsyncMock(return_value=[])
    ):
        result = asyncio.run(laq.fetch_lead_filter_options())

    names = {row["name"] for row in result["locations"]}
    assert "OMR" in names
    assert "Anna Nagar" in names
    assert "Chennai" in names
