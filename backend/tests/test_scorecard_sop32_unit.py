"""Sales Dashboard scorecard additions (SOP v3.2 section 8 / section 10)."""

from crm.api.v1.endpoints.analytics import missed_pickups_pipeline


def test_missed_pickups_counts_every_agent_except_the_latest_router_assignment():
    pipe = missed_pickups_pipeline()
    # only leads that were routed more than once can have a miss
    assert pipe[0] == {"$match": {"pool_assignment_history.1": {"$exists": True}}}
    # slice drops the LAST entry (the current router assignment) before unwinding
    sl = pipe[1]["$project"]["missed"]["$slice"]
    assert sl[0] == "$pool_assignment_history"
    assert sl[1] == {"$subtract": [{"$size": "$pool_assignment_history"}, 1]}
    assert pipe[2] == {"$unwind": "$missed"}
    assert pipe[3] == {"$group": {"_id": "$missed", "missed_pickups": {"$sum": 1}}}


def test_missed_pickups_follows_the_dashboard_scope():
    scope = {"created_at_dt": {"$gte": 1}}
    pipe = missed_pickups_pipeline(scope)
    assert pipe[0]["$match"] == {"$and": [scope, {"pool_assignment_history.1": {"$exists": True}}]}
