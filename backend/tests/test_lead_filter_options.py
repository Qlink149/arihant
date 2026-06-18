"""Unit tests for canonical picklist merge helpers."""

from crm.constants.lead_picklists import (
    CANONICAL_SOURCES,
    merge_picklist_with_db,
)


def test_merge_picklist_canonical_first_with_db_counts():
    db_rows = [
        {"name": "google ads", "count": 5},
        {"name": "legacy source", "count": 2},
    ]
    merged = merge_picklist_with_db(["google ads", "website"], db_rows)
    names = [row["name"] for row in merged]
    assert names[0] == "google ads"
    assert names[1] == "website"
    assert "legacy source" in names
    google_row = next(r for r in merged if r["name"] == "google ads")
    assert google_row["count"] == 5


def test_merge_picklist_dedupes_canonical_case_insensitive():
    db_rows = [{"name": "Google Ads", "count": 3}]
    merged = merge_picklist_with_db(["google ads"], db_rows)
    assert len(merged) == 1
    assert merged[0]["count"] == 3


def test_canonical_sources_includes_client_values():
    assert "facebook_ad" in CANONICAL_SOURCES
    assert "direct walk-in" in CANONICAL_SOURCES
    assert len(CANONICAL_SOURCES) >= 60
