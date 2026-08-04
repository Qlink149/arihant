"""Unit tests for current-status RNR queue clause."""

from crm.services.sales_dashboard_filters import rnr_metric_clause


def test_rnr_metric_clause_excludes_historical_fw_only():
    clause = rnr_metric_clause()
    assert "$and" in clause
    positive, exclusion = clause["$and"]
    or_keys = {tuple(sorted(c.keys())) for c in positive["$or"]}
    assert ("is_rnr",) in or_keys or {"is_rnr"} <= set().union(*[set(c) for c in positive["$or"]])
    fields = set()
    for part in positive["$or"]:
        fields.update(part.keys())
    assert "lead_status" in fields
    assert "is_rnr" in fields
    assert "original_fw_status" not in fields
    assert "lead_status" in exclusion
    assert "$not" in exclusion["lead_status"]
