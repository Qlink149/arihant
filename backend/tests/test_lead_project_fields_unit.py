"""Unit tests for lead project array helpers."""
from crm.services.lead_project_fields import (
    EmptyProjectsError,
    TooManyProjectsError,
    append_incoming_project,
    apply_coalesce_for_response,
    coalesce_projects,
    format_projects_display,
    incoming_slug_on_lead,
    normalize_lead_projects,
    primary_project_label,
    should_reengage_status,
    split_project_string,
)


def test_split_project_string_semicolon_only():
    assert split_project_string("ECR - Reserve 16; OMR - Vivriti") == [
        "ECR - Reserve 16",
        "OMR - Vivriti",
    ]
    assert split_project_string("ECR - Reserve 16, OMR - Vivriti") == [
        "ECR - Reserve 16, OMR - Vivriti"
    ]


def test_coalesce_prefers_array():
    lead = {"projects": ["A", "B"], "project": "Z"}
    assert coalesce_projects(lead) == ["A", "B"]


def test_coalesce_falls_back_to_scalar():
    assert coalesce_projects({"project": "A; B"}) == ["A", "B"]
    assert coalesce_projects({}) == []


def test_normalize_projects_wins_over_project():
    out = normalize_lead_projects(projects=["OMR - Vivriti"], project="ECR - Reserve 16")
    assert out["projects"] == ["OMR - Vivriti"]
    assert out["project"] == "OMR - Vivriti"


def test_normalize_legacy_project_string():
    out = normalize_lead_projects(project="ECR - Reserve 16")
    assert out["projects"] == ["ECR - Reserve 16"]
    assert out["project"] == "ECR - Reserve 16"
    assert "reserve-16" in (out.get("project_ids") or [])


def test_normalize_preserves_existing_project_id():
    existing = {"project": "ECR - Reserve 16", "project_id": "reserve-16"}
    out = normalize_lead_projects(
        projects=["ECR - Reserve 16", "OMR - Vivriti"],
        existing=existing,
        caller_project_id="reserve-16",
    )
    assert out["project_id"] == "reserve-16"
    assert out["project"] == "ECR - Reserve 16; OMR - Vivriti"


def test_normalize_empty_projects_rejected():
    try:
        normalize_lead_projects(projects=[], reject_empty=True)
        assert False, "expected EmptyProjectsError"
    except EmptyProjectsError:
        pass


def test_normalize_empty_without_reject_is_noop():
    assert normalize_lead_projects(projects=[], reject_empty=False) == {}


def test_normalize_cap():
    try:
        normalize_lead_projects(projects=[str(i) for i in range(11)])
        assert False, "expected TooManyProjectsError"
    except TooManyProjectsError:
        pass


def test_incoming_slug_on_lead():
    lead = {"project_id": "reserve-16", "project": "ECR - Reserve 16"}
    assert incoming_slug_on_lead(lead, "reserve-16") is True
    assert incoming_slug_on_lead(lead, "vivriti") is False


def test_append_does_not_duplicate_same_slug():
    existing = {
        "project": "ECR - Reserve 16",
        "project_id": "reserve-16",
        "projects": ["ECR - Reserve 16"],
        "project_ids": ["reserve-16"],
    }
    out = append_incoming_project(existing, incoming_name="Reserve 16", incoming_id="reserve-16")
    assert out["appended"] is False
    assert out["already"] is True
    assert out["projects"] == ["ECR - Reserve 16"]


def test_append_adds_new_project_keeps_original_names():
    existing = {"project": "ECR - Reserve 16", "project_id": "reserve-16"}
    out = append_incoming_project(existing, incoming_name="Vivriti", incoming_id="vivriti")
    assert out["appended"] is True
    assert "ECR - Reserve 16" in out["projects"]
    assert "Vivriti" in out["projects"]
    assert out["project"].startswith("ECR - Reserve 16")


def test_should_reengage_status():
    assert should_reengage_status("Closed Lost") is True
    assert should_reengage_status("Unqualified") is True
    assert should_reengage_status("Gone Cold") is True
    assert should_reengage_status("Junk") is False
    assert should_reengage_status("Contacted") is False
    assert should_reengage_status("Nurturing") is False
    assert should_reengage_status("Closed Won") is False


def test_apply_coalesce_for_response():
    lead = {"project": "A; B"}
    apply_coalesce_for_response(lead)
    assert lead["projects"] == ["A", "B"]


def test_primary_project_label():
    assert primary_project_label({"projects": ["A", "B"]}) == "A"
    assert format_projects_display(["A", "B"]) == "A; B"
