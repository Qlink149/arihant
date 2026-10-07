"""Switch-on safety (SOP F11): the pre-mark script must cover every flag the Phase 3
rules use, or flipping SLA_PHASE3_RULES_ENABLED would transfer/escalate the backlog."""

import importlib.util
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
ENGINE_SRC = (BACKEND / "crm" / "services" / "sla_engine.py").read_text(encoding="utf-8")


def _premark():
    spec = importlib.util.spec_from_file_location("premark_sla_backlog", BACKEND / "scripts" / "premark_sla_backlog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_phase3_rules_cover_the_ladder_and_the_interested_task():
    m = _premark()
    flags = {r["flag"] for r in m.RULES if r.get("phase3")}
    assert flags == {
        "sla_flags.rnr.transfer_d4_at_dt",
        "sla_flags.rnr.escalate_d7_at_dt",
        "sla_flags.rnr.escalate_15d_at_dt",
        "sla_flags.interested.followup_task_7d_at_dt",
    }


def test_phase3_flags_are_flags_the_engine_really_uses():
    """A renamed flag would make the pre-mark a silent no-op."""
    for leaf in ("transfer_d4_at_dt", "escalate_d7_at_dt", "followup_task_7d_at_dt"):
        assert leaf in ENGINE_SRC, f"engine no longer uses {leaf}"
    # the 15-day flag is built as escalate_{threshold}_at_dt with threshold "15d"
    assert "sla_flags.rnr.escalate_{threshold}_at_dt" in ENGINE_SRC and '"15d"' in ENGINE_SRC


def test_reminder_slots_match_the_engine_buckets():
    m = _premark()
    assert [s for s, _ in m.RNR_REMINDER_SLOTS] == [f"reminder_{b}" for b in ("a1", "a2", "a3", "b1", "b2", "b3")]
    for b in ("a1", "b3"):
        assert f'"{b}"' in ENGINE_SRC


def test_phase2_rules_are_not_marked_phase3():
    """--phase3-only must leave live Phase 2 rules alone."""
    m = _premark()
    phase2_names = {"contacted_reassign_7d", "visit_completed_feedback_2h", "visit_completed_escalate_72h",
                    "sv_followup_1_escalate_72h", "sv_followup_2_escalate_72h", "nurturing_hot_escalate_14d",
                    "interested_escalate_14d"}
    assert phase2_names <= {r["name"] for r in m.RULES}
    assert not any(r.get("phase3") for r in m.RULES if r["name"] in phase2_names)
