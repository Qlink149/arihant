"""Unit tests for lead filter-options aggregation helpers."""

from crm.services.lead_analytics_queries import (
    merge_query_with_valid_projects,
    project_distribution_pipeline,
)


def test_merge_query_with_valid_projects_empty_base():
    q = merge_query_with_valid_projects({})
    assert "project" in q
    assert "$exists" in q["project"]


def test_merge_query_with_valid_projects_and_base():
    base = {"lead_status": "New"}
    q = merge_query_with_valid_projects(base)
    assert "$and" in q
    assert base in q["$and"]


def test_project_distribution_pipeline_splits_and_groups():
    pipeline = project_distribution_pipeline({"location": "Chennai"}, limit=50)
    assert pipeline[0] == {"$match": {"location": "Chennai"}}
    assert any("$split" in str(stage) for stage in pipeline)
    assert pipeline[-1] == {"$limit": 50}
    group = next(s for s in pipeline if "$group" in s)
    assert group["$group"]["_id"] == "$_project_parts"
