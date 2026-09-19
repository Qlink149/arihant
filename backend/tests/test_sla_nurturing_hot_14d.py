"""Nurturing Hot 14-day admin escalation."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


def _lead(**overrides):
    now = utc_now()
    base = {
        "id": "n1",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "Nurturing",
        "temperature": "Hot",
        "nurture_entered_at_dt": now - timedelta(days=15),
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
        await engine._process_nurturing_hot_14d_escalation(now, now.isoformat(), {"Rep": "u1"})
    return engine


def test_nurturing_hot_14d_queues_admin_escalation():
    asyncio.run(_nurturing_hot_14d_queues_admin_escalation())


async def _nurturing_hot_14d_queues_admin_escalation():
    engine = await _run(_lead())
    thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "hot_escalate_14d" in thresholds
    task = next(op for op in engine._task_ops if op._doc.get("sla_threshold") == "hot_escalate_14d")
    assert task._doc["assigned_user_id"] == "a1"


def test_nurturing_warm_14d_no_escalation():
    asyncio.run(_nurturing_warm_14d_no_escalation())


async def _nurturing_warm_14d_no_escalation():
    now = utc_now()
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def empty_paginate(collection, query, projection=None, batch_size=200):
        if False:
            yield []

    with patch("crm.services.sla_engine._paginate_leads", empty_paginate):
        await engine._process_nurturing_hot_14d_escalation(now, now.isoformat(), {"Rep": "u1"})
    assert not engine._task_ops


def test_nurturing_hot_not_before_14d():
    asyncio.run(_nurturing_hot_not_before_14d())


async def _nurturing_hot_not_before_14d():
    now = utc_now()
    engine = await _run(_lead(nurture_entered_at_dt=now - timedelta(days=12)))
    assert "hot_escalate_14d" not in [op._doc.get("sla_threshold") for op in engine._task_ops]


def test_nurturing_hot_idempotent_when_flag_set():
    asyncio.run(_nurturing_hot_idempotent_when_flag_set())


async def _nurturing_hot_idempotent_when_flag_set():
    now = utc_now()
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def empty_paginate(collection, query, projection=None, batch_size=200):
        if False:
            yield []

    with patch("crm.services.sla_engine._paginate_leads", empty_paginate):
        await engine._process_nurturing_hot_14d_escalation(now, now.isoformat(), {"Rep": "u1"})
    assert not [op for op in engine._task_ops if op._doc.get("sla_threshold") == "hot_escalate_14d"]


def test_nurturing_hot_recent_entry_no_escalation():
    asyncio.run(_nurturing_hot_recent_entry_no_escalation())


async def _nurturing_hot_recent_entry_no_escalation():
    now = utc_now()
    engine = await _run(_lead(nurture_entered_at_dt=now - timedelta(days=2)))
    assert "hot_escalate_14d" not in [op._doc.get("sla_threshold") for op in engine._task_ops]
