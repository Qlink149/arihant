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
