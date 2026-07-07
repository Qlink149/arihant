"""Interested status SLA: 7-day reminder sets next_action_date to today (IST)."""

import asyncio
from datetime import timedelta
from unittest.mock import patch

from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


def test_interested_7d_sets_next_action_date_backup():
    asyncio.run(_interested_7d_sets_next_action_date_backup())


async def _interested_7d_sets_next_action_date_backup():
    now = utc_now()
    entered = now - timedelta(days=8)
    lead = {
        "id": "lead-int-1",
        "first_name": "I",
        "last_name": "N",
        "lead_status": "Interested",
        "interested_entered_at_dt": entered,
        "assigned_to": "Agent",
        "assigned_user_id": "u1",
        "sla_flags": {},
    }

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    engine = SLAEngineService()
    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        await engine._process_rule_interested(now, now.isoformat(), {"Agent": "u1"})

    assert len(engine._lead_ops) == 1
    doc = engine._lead_ops[0]._doc["$set"]
    assert doc.get("next_action_date")
    assert "sla_flags.interested.7d_at_dt" in doc

