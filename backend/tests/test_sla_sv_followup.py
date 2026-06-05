"""SV Completed – Follow Up SLA rule tests."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from crm.constants.lead_status import is_sv_followup_status
from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


def test_is_sv_followup_status_matches_ui_label():
    assert is_sv_followup_status("SV Completed – Follow Up")


def test_sv_followup_7d_moves_to_gone_cold_without_booking_progress():
    asyncio.run(_sv_followup_7d_gone_cold())


async def _sv_followup_7d_gone_cold():
    now = utc_now()
    entered = now - timedelta(days=8)
    lead = {
        "id": "lead-sv-1",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "SV Completed – Follow Up",
        "sv_followup_entered_at_dt": entered,
        "assigned_to": "Agent",
        "assigned_user_id": "u1",
        "sla_flags": {},
    }

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    admin = {"id": "admin-1", "full_name": "Admin"}
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": admin}

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        with patch("crm.services.sla_engine.db") as mock_db:
            mock_db.leads = MagicMock()
            mock_db.tasks.find_one = AsyncMock(return_value=None)
            await engine._process_rule_sv_followup(now, now.isoformat(), {"Agent": "u1"})

    assert any(
        op._doc["$set"].get("lead_status") == "Gone Cold"
        for op in engine._lead_ops
        if hasattr(op, "_doc")
    )


def test_sv_followup_72h_requires_pending_task():
    asyncio.run(_sv_followup_72h_skips_without_pending())


async def _sv_followup_72h_skips_without_pending():
    now = utc_now()
    entered = now - timedelta(hours=80)
    lead = {
        "id": "lead-sv-2",
        "lead_status": "SV Completed – Follow Up",
        "sv_followup_entered_at_dt": entered,
        "assigned_to": "Agent",
        "assigned_user_id": "u1",
        "sla_flags": {},
    }

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        with patch("crm.services.sla_engine.db") as mock_db:
            mock_db.leads = MagicMock()
            mock_db.tasks.find_one = AsyncMock(return_value=None)
            await engine._process_rule_sv_followup(now, now.isoformat(), {})

    assert not any(
        getattr(op, "_doc", {}).get("$set", {}).get("sla_flags.sv_followup.admin_72h_at_dt")
        for op in engine._lead_ops
    )
