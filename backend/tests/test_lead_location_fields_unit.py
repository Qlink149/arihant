"""batch3(item4): #51 Location Interested multi-select. coalesce_locations()
is the single place that reads both the legacy scalar string and the new
list shape — every consumer (inventory matching, exports, Meta CAPI, the AI
persona sentence, VC filter dropdown) goes through it or first_location()."""

from crm.services.lead_location_fields import (
    coalesce_locations,
    first_location,
    format_locations_display,
)


def test_coalesce_list_shape():
    assert coalesce_locations({"location": ["OMR", "Anna Nagar"]}) == ["OMR", "Anna Nagar"]


def test_coalesce_legacy_scalar_shape():
    assert coalesce_locations({"location": "Chennai"}) == ["Chennai"]


def test_coalesce_missing_or_empty():
    assert coalesce_locations({}) == []
    assert coalesce_locations({"location": None}) == []
    assert coalesce_locations({"location": []}) == []
    assert coalesce_locations({"location": ""}) == []


def test_coalesce_dedupes_case_insensitively_and_trims():
    assert coalesce_locations({"location": [" OMR ", "omr", "Anna Nagar"]}) == ["OMR", "Anna Nagar"]


def test_format_locations_display():
    assert format_locations_display(["OMR", "Anna Nagar"]) == "OMR; Anna Nagar"
    assert format_locations_display([]) == ""


def test_first_location():
    assert first_location({"location": ["OMR", "Anna Nagar"]}) == "OMR"
    assert first_location({"location": "Chennai"}) == "Chennai"
    assert first_location({}) is None
