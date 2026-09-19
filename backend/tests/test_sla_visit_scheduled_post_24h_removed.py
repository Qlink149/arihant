"""Visit-scheduled post-24h reminder removed per SOP; pre-24h reminder remains."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


def test_visit_scheduled_post_24h_does_not_queue_task():
    asyncio.run(_post_24h_removed())


def test_visit_scheduled_pre_24h_still_queues():
    asyncio.run(_pre_24h_still_fires())


async def _post_24h_removed():
    now = utc_now()
    visit_dt = now - timedelta(hours=48)
    lead = {
        "id": "vs1",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "Site Visit Scheduled",
        "visit_date_dt": visit_dt,
        "assigned_to": "Rep",
        "assigned_user_id": "u1",
        "sla_flags": {},
    }

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    engine = SLAEngineService()

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        await engine._process_rule_visit_scheduled(now, now.isoformat(), {"Rep": "u1"})

    thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "post_24h" not in thresholds


async def _pre_24h_still_fires():
    now = utc_now()
    visit_dt = now + timedelta(hours=12)
    lead = {
        "id": "vs2",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "Site Visit Scheduled",
        "visit_date_dt": visit_dt,
        "assigned_to": "Rep",
        "assigned_user_id": "u1",
        "sla_flags": {},
    }

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    engine = SLAEngineService()

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        await engine._process_rule_visit_scheduled(now, now.isoformat(), {"Rep": "u1"})

    thresholds = [op._doc.get("sla_threshold") for op in engine._task_ops]
    assert "pre_24h" in thresholds
