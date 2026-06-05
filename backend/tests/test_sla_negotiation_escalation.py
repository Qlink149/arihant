"""Negotiation 7d and 15d SLA escalations."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


def test_negotiation_15d_queues_admin_task():
    asyncio.run(_negotiation_15d_admin())


async def _negotiation_15d_admin():
    now = utc_now()
    lead = {
        "id": "n1",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "Negotiation",
        "negotiation_entered_at_dt": now - timedelta(days=16),
        "assigned_to": "Rep",
        "assigned_user_id": "u1",
        "sla_flags": {},
    }

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        await engine._process_rule_negotiation(now, now.isoformat(), {"Rep": "u1"})

    thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "admin_15d" in thresholds
    admin_task = next(op for op in engine._task_ops if op._doc.get("sla_threshold") == "admin_15d")
    assert admin_task._doc["assigned_user_id"] == "a1"
