"""Terminal lead exclusion from SLA rule queries."""

from crm.services.sla_engine import SLAEngineService


def test_rule_query_includes_terminal_exclusion():
    engine = SLAEngineService()
    q = engine._rule_query({"lead_status": {"$regex": r"^\s*contacted\s*$", "$options": "i"}})
    assert "$and" in q
    assert len(q["$and"]) == 3
    assert q["$and"][1]["lead_status"]["$not"]["$regex"]
    assert q["$and"][2]["sla_paused"] == {"$ne": True}
