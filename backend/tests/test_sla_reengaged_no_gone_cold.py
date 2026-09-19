"""Re-engaged 48h SLA must alert admin without auto-moving to Gone Cold."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


def test_reengaged_48h_queues_admin_alert_without_status_change():
    asyncio.run(_reengaged_48h_admin_only())


async def _reengaged_48h_admin_only():
    now = utc_now()
    lead = {
        "id": "re1",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "Re-engaged",
        "reengaged_at_dt": now - timedelta(hours=49),
        "assigned_to": "Rep",
        "assigned_user_id": "u1",
        "sla_flags": {},
    }

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        await engine._process_rule_reengaged(now, now.isoformat(), {"Rep": "u1"})

    admin_tasks = [op for op in engine._task_ops if op._doc.get("sla_threshold") == "48h"]
    assert len(admin_tasks) == 1
    assert admin_tasks[0]._doc["assigned_user_id"] == "a1"
    assert admin_tasks[0]._doc["description"] == "Re-engaged — Admin alert"
    for op in engine._lead_ops:
        set_fields = op._doc.get("$set") or {}
        assert "lead_status" not in set_fields
        assert "gone_cold_48h_at_dt" not in str(set_fields)
