"""Display-only call attempt counts on lead detail responses."""

from crm.services.call_stats import apply_call_attempt_counts_to_lead, compute_call_attempt_counts
from crm.services.lead_service import normalize_lead_for_response


def test_compute_call_attempt_counts_mixed():
    updates = [
        {"type": "call", "direction": "outbound"},
        {"type": "call", "direction": "inbound"},
        {"type": "call"},
        {"type": "note"},
    ]
    counts = compute_call_attempt_counts(updates)
    assert counts["call_attempt_count_total"] == 3
    assert counts["call_attempt_count_outbound"] == 2


def test_apply_call_attempt_counts_on_lead():
    lead = {
        "context_updates": [
            {"type": "call", "direction": "inbound"},
            {"type": "call"},
        ],
    }
    apply_call_attempt_counts_to_lead(lead)
    assert lead["call_attempt_count_total"] == 2
    assert lead["call_attempt_count_outbound"] == 1


def test_list_view_skips_call_counts():
    lead = {
        "context_updates": [{"type": "call"}],
        "strategic_next_moves": [],
        "recent_note": "x",
    }
    normalize_lead_for_response(lead, list_view=True)
    assert "call_attempt_count_total" not in lead
