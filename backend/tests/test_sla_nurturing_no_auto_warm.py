"""Nurturing SLA must not auto-set temperature after elapsed time."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


def test_nurturing_does_not_auto_set_warm_after_24h():
    asyncio.run(_nurturing_no_auto_warm())


async def _nurturing_no_auto_warm():
    now = utc_now()
    lead = {
        "id": "n-warm",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "Nurturing",
        "updated_at_dt": now - timedelta(hours=25),
        "nurture_entered_at_dt": now - timedelta(hours=25),
        "assigned_to": "Rep",
        "assigned_user_id": "u1",
        "sla_flags": {},
    }

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    engine = SLAEngineService()

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate), patch(
        "crm.services.sla_engine.db.tasks.find_one", new_callable=AsyncMock, return_value=None
    ):
        await engine._process_rule_nurturing(now, now.isoformat(), {"Rep": "u1"})

    assert not engine._lead_ops
