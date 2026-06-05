"""Contacted SLA: 48h to agent, 72h to admin."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

from crm.services.sla_engine import SLAEngineService, build_task_doc
from crm.utils.helpers import utc_now


def test_contacted_48h_uses_assignee_not_admin():
    asyncio.run(_contacted_48h_assignee())


async def _contacted_48h_assignee():
    now = utc_now()
    lead = {
        "id": "c1",
        "first_name": "X",
        "last_name": "Y",
        "lead_status": "Contacted",
        "contacted_at_dt": now - timedelta(hours=50),
        "assigned_to": "Sales Rep",
        "assigned_user_id": "rep-1",
        "sla_flags": {"contacted": {"72h_at_dt": now}},
    }
    captured = []

    def capture_task(*args, **kwargs):
        captured.append(kwargs.get("escalation_target"))

    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        with patch.object(engine, "_queue_task", side_effect=capture_task):
            await engine._process_rule_contacted(now, now.isoformat(), {"Sales Rep": "rep-1"})

    assert None in captured
    assert "admin" in captured


def test_contacted_72h_escalates_to_admin():
    now = utc_now()
    lead = {
        "id": "c2",
        "first_name": "X",
        "last_name": "Y",
        "assigned_to": "Sales Rep",
        "assigned_user_id": "rep-1",
    }
    task = build_task_doc(
        lead=lead,
        description="Admin Alert",
        dedupe_key="sla:contacted:72h:c2",
        now_dt=now,
        now_iso=now.isoformat(),
        name_to_user_id={"Sales Rep": "rep-1"},
        escalation_user={"id": "a1", "full_name": "Admin"},
        priority="high",
    )
    assert task is not None
    assert task["assigned_user_id"] == "a1"
