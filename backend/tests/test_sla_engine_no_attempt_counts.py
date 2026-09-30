"""Phase 3 T3: SLA rules must never read display-only attempt counts."""

from pathlib import Path


def test_sla_engine_does_not_read_attempt_counts():
    engine = Path("crm/services/sla_engine.py").read_text(encoding="utf-8")
    banned = (
        "rnr_attempts_by_agent",
        "rnr_attempts_total",
        "rnr_telephony",  # covers rnr_telephony_inbound/outbound (batch2 item 5)
        "telephony_inbound",
        "telephony_outbound",
        "logged_by_agent",
        "compute_rnr_stay_call_panel",
        "compute_call_attempt_counts",
    )
    for token in banned:
        assert token not in engine, token
