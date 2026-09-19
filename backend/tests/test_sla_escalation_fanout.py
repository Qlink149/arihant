"""Escalation tasks fan out notifications to all admins and the general manager."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


def test_escalation_fanout_five_recipients_one_task():
    asyncio.run(_escalation_fanout())


async def _escalation_fanout():
    now = utc_now()
    lead = {
        "id": "esc1",
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

    admins = [{"id": f"a{i}", "full_name": f"Admin {i}", "role": "admin"} for i in range(1, 5)]
    gm = {"id": "gm1", "full_name": "Shariff", "role": "general_manager"}
    engine = SLAEngineService()
    engine._escalation_targets = {
        "admin": admins[0],
        "admins": admins,
        "general_managers": [gm],
    }

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        await engine._process_rule_negotiation(now, now.isoformat(), {"Rep": "u1"})

    admin_tasks = [op for op in engine._task_ops if op._doc.get("sla_threshold") == "admin_15d"]
    assert len(admin_tasks) == 1
    assert admin_tasks[0]._doc["assigned_user_id"] == "a1"
    admin_notifs = [op for op in engine._notif_ops if op._doc.get("sla_threshold") == "admin_15d"]
    assert len(admin_notifs) == 5
    recipient_ids = {op._doc["recipient_user_id"] for op in admin_notifs}
    assert recipient_ids == {"a1", "a2", "a3", "a4", "gm1"}
    dedupe_keys = {op._doc["dedupe_key"] for op in admin_notifs}
    assert len(dedupe_keys) == 5
