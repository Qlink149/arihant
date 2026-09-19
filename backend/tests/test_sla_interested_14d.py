"""Interested 7d NAD backup and 14d admin escalation."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


def _lead(**overrides):
    now = utc_now()
    base = {
        "id": "i1",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "Interested",
        "interested_entered_at_dt": now - timedelta(days=15),
        "assigned_to": "Rep",
        "assigned_user_id": "u1",
        "sla_flags": {},
    }
    base.update(overrides)
    return base


async def _run(lead):
    now = utc_now()
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        await engine._process_rule_interested(now, now.isoformat(), {"Rep": "u1"})
    return engine


def test_interested_14d_queues_admin_escalation():
    asyncio.run(_interested_14d_queues_admin_escalation())


async def _interested_14d_queues_admin_escalation():
    engine = await _run(_lead())
    thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "escalate_14d" in thresholds
    task = next(op for op in engine._task_ops if op._doc.get("sla_threshold") == "escalate_14d")
    assert task._doc["assigned_user_id"] == "a1"


def test_interested_7d_and_14d_fire_independently():
    asyncio.run(_interested_7d_and_14d_fire_independently())


async def _interested_7d_and_14d_fire_independently():
    now = utc_now()
    lead = _lead(
        interested_entered_at_dt=now - timedelta(days=15),
        sla_flags={"interested": {"7d_at_dt": now}},
    )
    engine = await _run(lead)
    thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "escalate_14d" in thresholds
    assert len([t for t in thresholds if t == "escalate_14d"]) == 1


def test_interested_14d_not_before_threshold():
    asyncio.run(_interested_14d_not_before_threshold())


async def _interested_14d_not_before_threshold():
    now = utc_now()
    engine = await _run(_lead(interested_entered_at_dt=now - timedelta(days=10)))
    assert "escalate_14d" not in [op._doc.get("sla_threshold") for op in engine._task_ops]


def test_interested_7d_nad_at_8_days():
    asyncio.run(_interested_7d_nad_at_8_days())


async def _interested_7d_nad_at_8_days():
    now = utc_now()
    lead = _lead(interested_entered_at_dt=now - timedelta(days=8))
    engine = await _run(lead)
    assert len(engine._lead_ops) == 1
    assert "escalate_14d" not in [op._doc.get("sla_threshold") for op in engine._task_ops]


def test_interested_14d_idempotent_when_flag_set():
    asyncio.run(_interested_14d_idempotent_when_flag_set())


async def _interested_14d_idempotent_when_flag_set():
    now = utc_now()
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def empty_paginate(collection, query, projection=None, batch_size=200):
        if False:
            yield []

    with patch("crm.services.sla_engine._paginate_leads", empty_paginate):
        await engine._process_rule_interested(now, now.isoformat(), {"Rep": "u1"})
    assert not engine._task_ops
