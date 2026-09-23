"""Nurturing SLA: warm/hot periodic follow-up tasks."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


def test_nurturing_queues_hot_followup_when_cadence_met():
    asyncio.run(_nurturing_queues_hot_followup_when_cadence_met())


async def _nurturing_queues_hot_followup_when_cadence_met():
    now = utc_now()
    entered = now - timedelta(days=10)
    lead = {
        "id": "nurture-lead-2",
        "first_name": "Hot",
        "last_name": "Lead",
        "lead_status": "Nurturing",
        "temperature": "Hot",
        "nurture_entered_at_dt": entered,
        "updated_at_dt": entered,
        "assigned_to": "Harish Marlecha",
        "assigned_user_id": "rep-1",
        "sla_flags": {"nurturing": {}},
    }
    captured = []

    def capture_task(*args, **kwargs):
        captured.append({"args": args, "kwargs": kwargs})

    engine = SLAEngineService()

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        with patch.object(engine, "_queue_task", side_effect=capture_task):
            with patch.object(engine, "_queue_lead_mutation"):
                await engine._process_rule_nurturing(
                    now, now.isoformat(), {"Harish Marlecha": "rep-1"}
                )

    nurturing_calls = [c for c in captured if c["kwargs"].get("sla_rule") == "nurturing"]
    assert len(nurturing_calls) == 1
    call = nurturing_calls[0]
    assert call["kwargs"]["sla_threshold"] == "hot_2d"
    assert call["args"][1] == "Hot Lead Follow-up"
    assert "nurture-lead-2" in call["args"][2]


def test_nurturing_skips_when_cadence_not_met():
    asyncio.run(_nurturing_skips_when_cadence_not_met())


async def _nurturing_skips_when_cadence_not_met():
    now = utc_now()
    entered = now - timedelta(days=1)
    lead = {
        "id": "nurture-lead-1",
        "first_name": "Warm",
        "last_name": "Lead",
        "lead_status": "Nurturing",
        "temperature": "Warm",
        "nurture_entered_at_dt": entered,
        "updated_at_dt": entered,
        "assigned_to": "Harish Marlecha",
        "assigned_user_id": "rep-1",
        "sla_flags": {"nurturing": {}},
    }
    captured = []

    def capture_task(*args, **kwargs):
        captured.append({"args": args, "kwargs": kwargs})

    engine = SLAEngineService()

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        with patch.object(engine, "_queue_task", side_effect=capture_task):
            with patch.object(engine, "_queue_lead_mutation"):
                await engine._process_rule_nurturing(
                    now, now.isoformat(), {"Harish Marlecha": "rep-1"}
                )

    nurturing_calls = [c for c in captured if c["kwargs"].get("sla_rule") == "nurturing"]
    assert nurturing_calls == []
