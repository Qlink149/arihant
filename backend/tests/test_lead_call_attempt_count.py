"""Display-only call counts on lead detail responses.

batch2 item 5: three separate counts (telephony_inbound, telephony_outbound,
logged_by_agent), never merged into one "total" - see call_stats.py.
"""

from crm.services.call_stats import apply_call_attempt_counts_to_lead, compute_call_attempt_counts
from crm.services.lead_service import normalize_lead_for_response


def _mcube(direction):
    return {"type": "call", "mcube_call_id": "call-1", "direction": direction}


def _typed_call_note():
    return {"type": "call", "update_type": "call_note", "actor_user_id": "u1"}


def _manual_call_summary():
    """crm/api/v1/endpoints/call_summary.py's shape - no update_type, no mcube_call_id."""
    return {"type": "call", "intent_level": "high", "actor_user_id": "u1"}


def test_accept_criteria_one_inbound_zero_outbound_two_logged():
    """The exact Accept example: one MCUBE inbound, zero MCUBE outbound, two
    typed call notes -> 1 / 0 / 2."""
    updates = [_mcube("inbound"), _typed_call_note(), _typed_call_note()]
    counts = compute_call_attempt_counts(updates)
    assert counts == {"telephony_inbound": 1, "telephony_outbound": 0, "logged_by_agent": 2}


def test_mcube_outbound_counts_as_outbound_telephony():
    counts = compute_call_attempt_counts([_mcube("outbound")])
    assert counts["telephony_outbound"] == 1
    assert counts["telephony_inbound"] == 0


def test_mcube_missing_direction_fails_safe_as_inbound():
    entry = {"type": "call", "mcube_call_id": "call-2"}  # no direction field
    counts = compute_call_attempt_counts([entry])
    assert counts["telephony_inbound"] == 1
    assert counts["telephony_outbound"] == 0


def test_manual_call_summary_counts_as_logged_by_agent_not_telephony():
    counts = compute_call_attempt_counts([_manual_call_summary()])
    assert counts["logged_by_agent"] == 1
    assert counts["telephony_inbound"] == 0
    assert counts["telephony_outbound"] == 0


def test_csv_imported_note_never_counted_even_if_mislabelled_call():
    """Defensive backstop: even if a future bug re-labels a csv_import entry
    as type:"call", the explicit source check keeps it out of every count."""
    entry = {"type": "call", "mcube_call_id": "x", "direction": "inbound", "source": "csv_import"}
    counts = compute_call_attempt_counts([entry])
    assert counts == {"telephony_inbound": 0, "telephony_outbound": 0, "logged_by_agent": 0}


def test_non_call_entries_ignored():
    counts = compute_call_attempt_counts([{"type": "note"}, {"type": "whatsapp"}])
    assert counts == {"telephony_inbound": 0, "telephony_outbound": 0, "logged_by_agent": 0}


def test_no_single_total_field_anywhere():
    counts = compute_call_attempt_counts([_mcube("inbound"), _typed_call_note()])
    assert "total" not in "".join(counts.keys()).lower()


def test_apply_call_attempt_counts_on_lead():
    lead = {
        "context_updates": [_mcube("inbound"), _manual_call_summary()],
    }
    apply_call_attempt_counts_to_lead(lead)
    assert lead["telephony_inbound"] == 1
    assert lead["telephony_outbound"] == 0
    assert lead["logged_by_agent"] == 1


def test_list_view_skips_call_counts():
    lead = {
        "context_updates": [_mcube("inbound")],
        "strategic_next_moves": [],
        "recent_note": "x",
    }
    normalize_lead_for_response(lead, list_view=True)
    assert "telephony_inbound" not in lead
