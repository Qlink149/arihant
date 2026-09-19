"""SV Follow-up entry tasks and 72h pending-task admin escalations."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


def _sv1_lead(**overrides):
    now = utc_now()
    base = {
        "id": "sv1",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "SV Follow-up 1",
        "sv_followup_1_entered_at_dt": now - timedelta(hours=80),
        "assigned_to": "Rep",
        "assigned_user_id": "u1",
        "sla_flags": {},
    }
    base.update(overrides)
    return base


async def _run_sv1_rule(lead, pending_task=True):
    now = utc_now()
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate), patch(
        "crm.services.sla_engine._has_pending_sv_entry_task",
        AsyncMock(return_value=pending_task),
    ):
        await engine._process_rule_sv_followup_1(now, now.isoformat(), {"Rep": "u1"})
    return engine


def test_sv_followup_1_72h_escalates_when_entry_task_pending():
    asyncio.run(_sv_followup_1_72h_escalates_when_entry_task_pending())


async def _sv_followup_1_72h_escalates_when_entry_task_pending():
    engine = await _run_sv1_rule(_sv1_lead())
    thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "escalate_72h" in thresholds
    task = next(op for op in engine._task_ops if op._doc.get("sla_threshold") == "escalate_72h")
    assert task._doc["assigned_user_id"] == "a1"


def test_sv_followup_1_72h_not_before_threshold():
    asyncio.run(_sv_followup_1_72h_not_before_threshold())


async def _sv_followup_1_72h_not_before_threshold():
    now = utc_now()
    lead = _sv1_lead(sv_followup_1_entered_at_dt=now - timedelta(hours=48))
    engine = await _run_sv1_rule(lead)
    assert "escalate_72h" not in [op._doc.get("sla_threshold") for op in engine._task_ops]


def test_sv_followup_1_72h_skipped_without_pending_entry_task():
    asyncio.run(_sv_followup_1_72h_skipped_without_pending_entry_task())


async def _sv_followup_1_72h_skipped_without_pending_entry_task():
    engine = await _run_sv1_rule(_sv1_lead(), pending_task=False)
    assert "escalate_72h" not in [op._doc.get("sla_threshold") for op in engine._task_ops]


def test_sv_followup_1_72h_idempotent_when_flag_set():
    asyncio.run(_sv_followup_1_72h_idempotent_when_flag_set())


async def _sv_followup_1_72h_idempotent_when_flag_set():
    now = utc_now()
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def empty_paginate(collection, query, projection=None, batch_size=200):
        if False:
            yield []

    with patch("crm.services.sla_engine._paginate_leads", empty_paginate):
        await engine._process_rule_sv_followup_1(now, now.isoformat(), {"Rep": "u1"})
    assert not engine._task_ops


def test_sv_followup_2_72h_escalates_when_entry_task_pending():
    asyncio.run(_sv_followup_2_72h_escalates_when_entry_task_pending())


async def _sv_followup_2_72h_escalates_when_entry_task_pending():
    now = utc_now()
    lead = {
        "id": "sv2",
        "first_name": "C",
        "last_name": "D",
        "lead_status": "SV Follow-up 2",
        "sv_followup_2_entered_at_dt": now - timedelta(hours=80),
        "assigned_to": "Rep",
        "assigned_user_id": "u1",
        "sla_flags": {},
    }
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate), patch(
        "crm.services.sla_engine._has_pending_sv_entry_task", AsyncMock(return_value=True)
    ):
        await engine._process_rule_sv_followup_2(now, now.isoformat(), {"Rep": "u1"})

    thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "escalate_72h" in thresholds


def test_sv_followup_entry_task_created_on_status_change():
    asyncio.run(_sv_followup_entry_task_created_on_status_change())


async def _sv_followup_entry_task_created_on_status_change():
    from crm.models.schemas.lead_schemas import LeadUpdatePatch
    from crm.services.lead_service import update_lead

    existing = {
        "id": "lead-sv-entry",
        "lead_status": "Visit Completed",
        "first_name": "E",
        "last_name": "F",
        "assigned_to": "Rep",
        "assigned_user_id": "u1",
        "temperature": None,
    }
    current_user = {"id": "u1", "full_name": "Rep", "role": "rep"}

    updated = {**existing, "lead_status": "SV Follow-up 1"}
    mock_db = AsyncMock()
    mock_db.leads.find_one = AsyncMock(side_effect=[existing, updated])
    mock_db.leads.update_one = AsyncMock()
    mock_db.tasks = AsyncMock()
    mock_db.tasks.update_many = AsyncMock()

    with patch("crm.services.lead_service.db", mock_db), patch(
        "crm.services.lead_service.create_sla_task_for_lead", AsyncMock(return_value="task-1")
    ) as mock_task, patch(
        "crm.services.lead_service.log_lead_event", AsyncMock()
    ), patch(
        "crm.services.lead_service.create_notification", AsyncMock()
    ):
        await update_lead(
            "lead-sv-entry",
            LeadUpdatePatch(lead_status="SV Follow-up 1"),
            current_user,
        )

    mock_task.assert_called_once()
    assert mock_task.call_args.kwargs["sla_rule"] == "sv_followup_1"
    assert mock_task.call_args.kwargs["sla_threshold"] == "entry"
