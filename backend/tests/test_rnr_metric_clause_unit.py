"""Unit tests for the RNR queue clause: RNR means lead_status (SOP 5.2), full stop.

The legacy import-era `is_rnr` flag is not read: it counted 53 Contacted / Nurturing /
Gone Cold / Future Prospect leads as RNR on the dashboard while the SLA engine (which
acts on lead_status only) gave them no RNR treatment.
"""

from crm.services.sales_dashboard_filters import rnr_metric_clause


def test_rnr_metric_clause_is_status_only():
    clause = rnr_metric_clause()
    assert "$and" in clause
    positive, exclusion = clause["$and"]
    # positive part: lead_status matches the RNR regex, no OR with any other field
    assert set(positive.keys()) == {"lead_status"}
    assert "$regex" in positive["lead_status"]
    # terminal/junk/unqualified excluded
    assert "lead_status" in exclusion
    assert "$not" in exclusion["lead_status"]


def test_rnr_metric_clause_never_reads_legacy_flag_or_history():
    blob = str(rnr_metric_clause())
    assert "is_rnr" not in blob
    assert "original_fw_status" not in blob


def test_rnr_metric_clause_matches_sla_engine_definition():
    """Dashboard RNR and the SLA engine must agree on what 'RNR' is."""
    from crm.services.sla_engine import _rnr_status_filter

    positive = rnr_metric_clause()["$and"][0]
    assert positive == _rnr_status_filter()
