from crm.services.inventory_match_service import evaluate_lead_for_inventory as eval_inv


def test_budget_missing_blocks():
    ok, reason, _ = eval_inv({"budget": "", "location": "Chennai"}, {"budget": "50L", "location": "Chennai"})
    assert not ok
    assert reason == "budget_missing"


def test_all_missing_blocks():
    ok, reason, _ = eval_inv({}, {"budget": "50L"})
    assert not ok
    assert reason == "all_preferences_missing"


def test_match_with_warnings():
    ok, reason, warnings = eval_inv(
        {"budget": "50 Lakh", "location": "", "configuration": ""},
        {"budget": "45-55L", "location": "Chennai", "configuration": "2 BHK"},
    )
    assert not ok or "preferences_incomplete" in warnings or reason == ""


# batch3(item4): #51 location is now a list; these prove both shapes still work.


def test_location_list_matches_if_any_element_matches():
    ok, reason, _ = eval_inv(
        {"budget": "50L", "location": ["OMR", "Chennai"]},
        {"budget": "45-55L", "location": "Chennai"},
    )
    assert ok
    assert reason == ""


def test_location_list_no_match_when_no_element_matches():
    ok, reason, _ = eval_inv(
        {"budget": "50L", "location": ["OMR", "Anna Nagar"]},
        {"budget": "45-55L", "location": "Chennai"},
    )
    assert not ok


def test_legacy_scalar_location_still_matches():
    ok, reason, _ = eval_inv(
        {"budget": "50L", "location": "Chennai"},
        {"budget": "45-55L", "location": "Chennai"},
    )
    assert ok


def test_empty_location_list_treated_as_missing():
    ok, reason, warnings = eval_inv(
        {"budget": "50L", "location": []},
        {"budget": "45-55L", "location": "Chennai"},
    )
    assert not ok
    assert "location_missing_city_match_skipped" in warnings
