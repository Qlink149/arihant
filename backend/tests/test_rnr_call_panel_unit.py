"""batch2 item 5: RNR stay call panel - telephony split the same way as
compute_call_attempt_counts (inbound/outbound/logged-by-agent, never a
merged total). "Logged attempts" (rnr_attempt) is a separate SOP concept
and is unaffected."""

from datetime import datetime, timezone

from crm.services.call_stats import compute_rnr_stay_call_panel

SINCE = datetime(2026, 5, 1, tzinfo=timezone.utc)
LATER = datetime(2026, 5, 2, tzinfo=timezone.utc)


def _lead(*entries):
    return {"rnr_entered_at_dt": SINCE, "context_updates": list(entries)}


def test_rnr_attempts_unaffected_by_call_split():
    entry = {"type": "rnr_attempt", "timestamp_dt": LATER, "actor_name": "Anusha"}
    result = compute_rnr_stay_call_panel(_lead(entry))
    assert result["rnr_attempts_by_agent"] == {"Anusha": 1}
    assert result["rnr_attempts_total"] == 1


def test_mcube_inbound_and_outbound_split_separately():
    inbound = {"type": "call", "timestamp_dt": LATER, "mcube_call_id": "c1", "direction": "inbound"}
    outbound = {"type": "call", "timestamp_dt": LATER, "mcube_call_id": "c2", "direction": "outbound"}
    result = compute_rnr_stay_call_panel(_lead(inbound, outbound))
    assert result["rnr_telephony_inbound"] == 1
    assert result["rnr_telephony_outbound"] == 1
    assert result["rnr_calls_logged_by_agent"] == 0


def test_typed_call_note_counts_as_logged_by_agent():
    note = {"type": "call", "timestamp_dt": LATER, "update_type": "call_note", "actor_name": "Anusha"}
    result = compute_rnr_stay_call_panel(_lead(note))
    assert result["rnr_calls_logged_by_agent"] == 1
    assert result["rnr_telephony_inbound"] == 0
    assert result["rnr_telephony_outbound"] == 0


def test_no_merged_total_field():
    result = compute_rnr_stay_call_panel(_lead())
    assert not any("total" in k.lower() and "telephony" in k.lower() for k in result)
    assert "rnr_telephony_total" not in result
    assert "rnr_telephony_by_agent" not in result
    assert "rnr_telephony_unattributed" not in result


def test_entries_before_rnr_entered_at_excluded():
    old_entry = {
        "type": "call", "timestamp_dt": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "mcube_call_id": "c1", "direction": "inbound",
    }
    result = compute_rnr_stay_call_panel(_lead(old_entry))
    assert result["rnr_telephony_inbound"] == 0


def test_csv_imported_entry_excluded_even_if_typed_as_call():
    entry = {"type": "call", "timestamp_dt": LATER, "mcube_call_id": "c1", "direction": "inbound", "source": "csv_import"}
    result = compute_rnr_stay_call_panel(_lead(entry))
    assert result["rnr_telephony_inbound"] == 0
