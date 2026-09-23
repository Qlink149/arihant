"""Event-driven Warm from three neutral outcomes."""

from crm.constants.call_outcomes import OUTCOME_CALL_BACK_LATER, OUTCOME_NEEDS_TIME, OUTCOME_RNR
from crm.services.nurture_temperature import apply_outcome_temperature


def test_three_neutral_moves_hot_to_warm():
    extra = []
    existing = {
        "lead_status": "Nurturing",
        "temperature": "Hot",
        "nurture_entered_at_dt": None,
        "context_updates": [
            {"type": "logged_outcome", "outcome": OUTCOME_NEEDS_TIME},
            {"type": "logged_outcome", "outcome": OUTCOME_RNR},
        ],
    }
    patch = {}
    apply_outcome_temperature(existing, patch, extra, outcome=OUTCOME_CALL_BACK_LATER, current_user={"full_name": "Rep", "id": "u1"})
    assert patch["temperature"] == "Warm"
    assert extra


def test_interested_outcome_promotes_warm():
    extra = []
    existing = {"lead_status": "Nurturing", "temperature": "Warm", "context_updates": []}
    patch = {}
    apply_outcome_temperature(existing, patch, extra, outcome="Interested", current_user={"full_name": "Rep", "id": "u1"})
    assert patch["temperature"] == "Hot"
