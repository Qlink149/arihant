"""Phase 3 RNR ladder: daily reminders a1–b3, D4 transfer, D7 + 15d admin tasks.

Isolation: every test wraps engine calls in ``patch(..., phase3_rules_enabled, return_value=True)``
via ``_phase3_enabled()`` — a context manager scoped to that test only. No ``os.environ`` mutation;
other tests in the same pytest process still see the default ``phase3_rules_enabled() == False``.
"""

import asyncio
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


@contextmanager
def _phase3_enabled():
    with patch("crm.services.sla_engine.phase3_rules_enabled", return_value=True):
        yield


def _rnr_lead(**overrides):
    now = utc_now()
    base = {
        "id": "rnr-p3-1",
        "first_name": "Phase",
        "last_name": "Three",
        "lead_status": "RNR",
        "pool_key": "reserve-16",
        "rnr_entered_at_dt": now - timedelta(hours=12),
        "assigned_to": "Rep",
        "assigned_user_id": "rep-1",
        "sla_flags": {},
    }
    base.update(overrides)
    return base


async def _run_phase3(lead, *, capture_tasks=None, capture_mutations=None):
    now = utc_now()
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "admin-1", "full_name": "Admin"}}
    captured_tasks = capture_tasks if capture_tasks is not None else []
    captured_mutations = capture_mutations if capture_mutations is not None else []

    def capture_task(*args, **kwargs):
        captured_tasks.append({"args": args, "kwargs": kwargs})

    def capture_mutation(lead_id, patch, flag, *rest):
        captured_mutations.append(
            {"lead_id": lead_id, "patch": patch, "flag": flag, "rest": rest}
        )

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    mock_db = MagicMock()
    mock_db.tasks.update_many = AsyncMock()
    reassign = AsyncMock(return_value={"ok": False})

    with _phase3_enabled():
        with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
            with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
                with patch("crm.services.sla_engine.db", mock_db):
                    with patch.object(engine, "_queue_task", side_effect=capture_task):
                        with patch.object(
                            engine, "_queue_lead_mutation", side_effect=capture_mutation
                        ):
                            with patch(
                                "crm.services.sla_engine.reassign_lead_in_pool",
                                reassign,
                            ):
                                with patch(
                                    "crm.services.sla_engine.create_notification",
                                    new_callable=AsyncMock,
                                ):
                                    await engine._process_rule_rnr(
                                        now, now.isoformat(), {"Rep": "rep-1"}
                                    )
    return engine, captured_tasks, captured_mutations


def test_phase3_reminder_a1_on_day_one():
    asyncio.run(_phase3_reminder_a1_on_day_one())


async def _phase3_reminder_a1_on_day_one():
    lead = _rnr_lead()
    _, tasks, _ = await _run_phase3(lead)
    rnr_tasks = [t for t in tasks if t["kwargs"].get("sla_rule") == "rnr"]
    assert len(rnr_tasks) == 1
    assert rnr_tasks[0]["kwargs"]["sla_threshold"] == "reminder_a1"
    assert rnr_tasks[0]["args"][1] == "RNR — retry call (day 1 of 3)"


def test_phase3_reminder_a2_after_24h():
    asyncio.run(_phase3_reminder_a2_after_24h())


async def _phase3_reminder_a2_after_24h():
    now = utc_now()
    lead = _rnr_lead(rnr_entered_at_dt=now - timedelta(hours=30))
    _, tasks, _ = await _run_phase3(lead)
    thresholds = [t["kwargs"]["sla_threshold"] for t in tasks]
    assert thresholds == ["reminder_a2"]


def test_phase3_d4_transfer_sets_window_b():
    asyncio.run(_phase3_d4_transfer_sets_window_b())


async def _phase3_d4_transfer_sets_window_b():
    now = utc_now()
    lead = _rnr_lead(rnr_entered_at_dt=now - timedelta(hours=80))
    reassign_result = {
        "ok": True,
        "assigned_user_id": "rep-2",
        "assigned_to": "Rep2",
        "previous_assigned_user_id": "rep-1",
        "previous_assigned_to": "Rep",
    }

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    engine = SLAEngineService()
    mock_db = MagicMock()
    mock_db.tasks.update_many = AsyncMock()
    mutations = []

    with _phase3_enabled():
        with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
            with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
                with patch("crm.services.sla_engine.db", mock_db):
                    with patch(
                        "crm.services.sla_engine.reassign_lead_in_pool",
                        AsyncMock(return_value=reassign_result),
                    ) as reassign:
                        with patch("crm.services.sla_engine.create_notification", AsyncMock()):
                            with patch.object(
                                engine,
                                "_queue_lead_mutation",
                                side_effect=lambda *a, **k: mutations.append(a),
                            ):
                                with patch.object(engine, "_queue_task"):
                                    await engine._process_rule_rnr(
                                        now, now.isoformat(), {"Rep": "rep-1"}
                                    )

    reassign.assert_awaited_once()
    assert mutations
    assert mutations[0][1].get("rnr_window_b_started_at_dt")
    assert mutations[0][2] == "sla_flags.rnr.transfer_d4_at_dt"


def test_phase3_d7_queues_admin_and_escalation_raise():
    asyncio.run(_phase3_d7_queues_admin_and_escalation_raise())


async def _phase3_d7_queues_admin_and_escalation_raise():
    now = utc_now()
    lead = _rnr_lead(rnr_entered_at_dt=now - timedelta(hours=150))
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "admin-1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    mock_db = MagicMock()
    mock_db.tasks.update_many = AsyncMock()

    with _phase3_enabled():
        with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
            with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
                with patch("crm.services.sla_engine.db", mock_db):
                    await engine._process_rule_rnr(now, now.isoformat(), {"Rep": "rep-1"})

    d7_tasks = [
        op._doc
        for op in engine._task_ops
        if op._doc.get("sla_threshold") == "escalate_d7"
    ]
    assert len(d7_tasks) == 1
    assert d7_tasks[0]["assigned_user_id"] == "admin-1"

    raise_ops = [
        op
        for op in engine._lead_ops
        if (op._doc.get("$set") or {}).get("escalation.active") is True
    ]
    assert len(raise_ops) == 1
    reasons = raise_ops[0]._doc["$set"]["escalation.reasons"]
    assert any(r.get("sla_threshold") == "escalate_d7" for r in reasons)


def test_phase3_15d_admin_task_unchanged():
    asyncio.run(_phase3_15d_admin_task_unchanged())


async def _phase3_15d_admin_task_unchanged():
    now = utc_now()
    lead = _rnr_lead(
        rnr_entered_at_dt=now - timedelta(days=16),
        sla_flags={"rnr": {"escalate_d7_at_dt": now - timedelta(days=1)}},
    )
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "admin-1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    mock_db = MagicMock()
    mock_db.tasks.update_many = AsyncMock()

    with _phase3_enabled():
        with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
            with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
                with patch("crm.services.sla_engine.db", mock_db):
                    await engine._process_rule_rnr(now, now.isoformat(), {"Rep": "rep-1"})

    thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "15d" in thresholds
    assert "escalate_d7" not in thresholds


def test_phase3_melange_skips_d4_d7_and_15d():
    asyncio.run(_phase3_melange_skips_d4_d7_and_15d())


async def _phase3_melange_skips_d4_d7_and_15d():
    now = utc_now()
    lead = _rnr_lead(
        pool_key="melange",
        rnr_entered_at_dt=now - timedelta(days=20),
    )
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "admin-1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    mock_db = MagicMock()
    mock_db.tasks.update_many = AsyncMock()

    with _phase3_enabled():
        with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
            with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
                with patch("crm.services.sla_engine.db", mock_db):
                    with patch(
                        "crm.services.sla_engine.reassign_lead_in_pool",
                        AsyncMock(),
                    ) as reassign:
                        await engine._process_rule_rnr(now, now.isoformat(), {"Rep": "rep-1"})

    reassign.assert_not_awaited()
    admin_thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "escalate_d7" not in admin_thresholds
    assert "15d" not in admin_thresholds
