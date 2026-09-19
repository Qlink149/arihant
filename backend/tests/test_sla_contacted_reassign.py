"""Contacted 7-day pool reassignment SLA."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from crm.services.sla_engine import CONTACTED_REASSIGN_INTERVAL_DAYS, SLAEngineService
from crm.utils.helpers import utc_now


def _lead(**overrides):
    now = utc_now()
    base = {
        "id": "c1",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "Contacted",
        "contacted_at_dt": now - timedelta(days=CONTACTED_REASSIGN_INTERVAL_DAYS + 1),
        "assigned_to": "Rep1",
        "assigned_user_id": "u1",
        "project_id": "reserve-16",
        "sla_flags": {},
    }
    base.update(overrides)
    return base


async def _run_reassign(lead, *, pending=False, reassign_result=None):
    now = utc_now()
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    reassign_result = reassign_result or {
        "ok": True,
        "assigned_user_id": "u2",
        "assigned_to": "Rep2",
        "previous_assigned_user_id": "u1",
        "previous_assigned_to": "Rep1",
    }

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate), patch(
        "crm.services.sla_engine._lead_has_pending_task", AsyncMock(return_value=pending)
    ), patch(
        "crm.services.sla_engine.reassign_lead_in_pool", AsyncMock(return_value=reassign_result)
    ), patch("crm.services.sla_engine.create_notification", AsyncMock()) as notify:
        await engine._process_contacted_reassign(now, now.isoformat(), {"Rep1": "u1"})
    return engine, notify


def test_contacted_reassign_success_sets_flag_and_notifies():
    asyncio.run(_contacted_reassign_success_sets_flag_and_notifies())


async def _contacted_reassign_success_sets_flag_and_notifies():
    engine, notify = await _run_reassign(_lead())
    assert len(engine._lead_ops) == 1
    assert notify.await_count == 2


def test_contacted_reassign_skipped_with_pending_task():
    asyncio.run(_contacted_reassign_skipped_with_pending_task())


async def _contacted_reassign_skipped_with_pending_task():
    engine, notify = await _run_reassign(_lead(), pending=True)
    assert not engine._lead_ops
    assert notify.await_count == 0


def test_contacted_reassign_not_before_interval():
    asyncio.run(_contacted_reassign_not_before_interval())


async def _contacted_reassign_not_before_interval():
    now = utc_now()
    engine, _ = await _run_reassign(
        _lead(contacted_at_dt=now - timedelta(days=CONTACTED_REASSIGN_INTERVAL_DAYS - 1))
    )
    assert not engine._lead_ops


def test_contacted_reassign_exhausted_queues_admin():
    asyncio.run(_contacted_reassign_exhausted_queues_admin())


async def _contacted_reassign_exhausted_queues_admin():
    engine, _ = await _run_reassign(
        _lead(),
        reassign_result={"ok": False, "reason": "chain_exhausted", "exhausted": True},
    )
    thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "reassign_exhausted" in thresholds


def test_melange_pool_skips_reassign():
    asyncio.run(_melange_pool_skips_reassign())


async def _melange_pool_skips_reassign():
    engine, _ = await _run_reassign(
        _lead(project_id="melange"),
        reassign_result={"ok": False, "reason": "no_escalate", "exhausted": True},
    )
    thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "reassign_exhausted" in thresholds
