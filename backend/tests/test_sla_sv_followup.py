"""Legacy SV Completed – Follow Up SLA rule tests.

SV Completed – Follow Up has been deprecated and is no longer processed by the SLA engine.
We keep only the helper matcher test for backward compatibility (historical data).
"""

from crm.constants.lead_status import is_sv_followup_status


def test_is_sv_followup_status_matches_ui_label():
    assert is_sv_followup_status("SV Completed – Follow Up")
