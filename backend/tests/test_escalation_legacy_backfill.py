"""Legacy escalation notification -> T10 whitelist pair mapping."""

from crm.services.escalation_legacy_backfill import (
    legacy_skip_reason,
    resolve_legacy_escalation_pair,
)


def test_modern_notification_with_sla_rule():
    pair = resolve_legacy_escalation_pair(
        {"sla_rule": "interested", "sla_threshold": "escalate_14d"}
    )
    assert pair == ("interested", "escalate_14d")


def test_legacy_stage_threshold_direct():
    pair = resolve_legacy_escalation_pair(
        {"stage": "contacted", "sla_threshold": "72h", "sla_rule": None}
    )
    assert pair == ("contacted", "72h")


def test_legacy_rnr_24h_maps_to_escalate_d7():
    pair = resolve_legacy_escalation_pair({"stage": "rnr", "sla_threshold": "24h"})
    assert pair == ("rnr", "escalate_d7")


def test_legacy_rnr_48h_maps_to_escalate_d7():
    pair = resolve_legacy_escalation_pair({"stage": "rnr", "sla_threshold": "48h"})
    assert pair == ("rnr", "escalate_d7")


def test_legacy_sv_followup_2_title():
    pair = resolve_legacy_escalation_pair(
        {
            "stage": "sla",
            "sla_threshold": "",
            "title": "SV Follow-up 2 — 7-day follow-up due",
        }
    )
    assert pair == ("sv_followup_2", "escalate_72h")


def test_legacy_new_2h_is_skipped_not_mapped():
    notif = {"stage": "new", "sla_threshold": "2h"}
    assert resolve_legacy_escalation_pair(notif) is None
    assert "not SOP" in (legacy_skip_reason(notif) or "")


def test_unmapped_pair_reports_reason():
    notif = {"stage": "negotiation", "sla_threshold": "admin_15d"}
    assert resolve_legacy_escalation_pair(notif) is None
    assert "unmapped" in (legacy_skip_reason(notif) or "")
