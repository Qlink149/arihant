"""Visit Completed 2h feedback task and 72h admin escalation."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


def _lead(**overrides):
    now = utc_now()
    base = {
        "id": "vc1",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "Visit Completed",
        "visit_completed_at_dt": now - timedelta(hours=3),
        "assigned_to": "Rep",
        "assigned_user_id": "u1",
        "sla_flags": {},
        "context_updates": [],
    }
    base.update(overrides)
    return base


async def _run_rule(lead):
    now = utc_now()
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        await engine._process_rule_visit_completed(now, now.isoformat(), {"Rep": "u1"})
    return engine


def test_visit_completed_2h_queues_agent_task():
    asyncio.run(_visit_completed_2h_queues_agent_task())


async def _visit_completed_2h_queues_agent_task():
    engine = await _run_rule(_lead())
    thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "feedback_2h" in thresholds
    task = next(op for op in engine._task_ops if op._doc.get("sla_threshold") == "feedback_2h")
    assert task._doc["assigned_user_id"] == "u1"


def test_visit_completed_2h_not_before_threshold():
    asyncio.run(_visit_completed_2h_not_before_threshold())


async def _visit_completed_2h_not_before_threshold():
    now = utc_now()
    lead = _lead(visit_completed_at_dt=now - timedelta(minutes=90))
    engine = await _run_rule(lead)
    assert "feedback_2h" not in [op._doc.get("sla_threshold") for op in engine._task_ops]


def test_visit_completed_2h_skipped_when_agent_active():
    asyncio.run(_visit_completed_2h_skipped_when_agent_active())


async def _visit_completed_2h_skipped_when_agent_active():
    now = utc_now()
    lead = _lead(
        visit_completed_at_dt=now - timedelta(hours=3),
        context_updates=[
            {
                "type": "note",
                "timestamp_dt": now - timedelta(hours=2),
                "agent": "Rep",
                "actor_user_id": "u1",
            }
        ],
    )
    engine = await _run_rule(lead)
    assert not engine._task_ops


def test_visit_completed_72h_queues_admin_escalation():
    asyncio.run(_visit_completed_72h_queues_admin_escalation())


async def _visit_completed_72h_queues_admin_escalation():
    now = utc_now()
    lead = _lead(visit_completed_at_dt=now - timedelta(hours=80))
    engine = await _run_rule(lead)
    thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "escalate_72h" in thresholds
    admin_task = next(op for op in engine._task_ops if op._doc.get("sla_threshold") == "escalate_72h")
    assert admin_task._doc["assigned_user_id"] == "a1"


def test_visit_completed_72h_blocked_by_activity_on_day_2():
    asyncio.run(_visit_completed_72h_blocked_by_activity_on_day_2())


async def _visit_completed_72h_blocked_by_activity_on_day_2():
    now = utc_now()
    lead = _lead(
        visit_completed_at_dt=now - timedelta(hours=80),
        context_updates=[
            {
                "type": "note",
                "timestamp_dt": now - timedelta(days=1),
                "agent": "Rep",
                "actor_user_id": "u1",
            }
        ],
    )
    engine = await _run_rule(lead)
    assert "escalate_72h" not in [op._doc.get("sla_threshold") for op in engine._task_ops]


def test_visit_completed_rules_idempotent_when_flag_set():
    asyncio.run(_visit_completed_rules_idempotent_when_flag_set())


async def _visit_completed_rules_idempotent_when_flag_set():
    now = utc_now()
    lead = _lead(
        visit_completed_at_dt=now - timedelta(hours=80),
        sla_flags={"visit_completed": {"feedback_2h_at_dt": now, "escalate_72h_at_dt": now}},
    )
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def empty_paginate(collection, query, projection=None, batch_size=200):
        if False:
            yield []

    with patch("crm.services.sla_engine._paginate_leads", empty_paginate):
        await engine._process_rule_visit_completed(now, now.isoformat(), {"Rep": "u1"})
    assert not engine._task_ops
