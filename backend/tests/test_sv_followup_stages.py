"""SV Follow-up 1 / 2 status helpers and SLA rules."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from crm.constants.lead_status import (
    is_sv_followup_1_status,
    is_sv_followup_2_status,
    is_sv_followup_status,
)
from crm.services.lead_service import _ist_follow_up_date
from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


def test_sv_followup_status_helpers():
    assert is_sv_followup_status("SV Completed – Follow Up")
    assert not is_sv_followup_status("SV Follow-up 1")
    assert not is_sv_followup_status("SV Follow-up 2")
    assert is_sv_followup_1_status("SV Follow-up 1")
    assert is_sv_followup_2_status("SV Follow-up 2")


def test_ist_follow_up_date_offsets_from_reference():
    ref = utc_now()
    due = _ist_follow_up_date(3, ref)
    assert len(due) == 10
    assert due[4] == "-"


def test_visit_completed_3d_sets_next_action_date_backup():
    asyncio.run(_visit_completed_3d_sets_next_action_date_backup())


async def _visit_completed_3d_sets_next_action_date_backup():
    now = utc_now()
    entered = now - timedelta(days=4)
    lead = {
        "id": "lead-vc-1",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "Visit Completed",
        "visit_completed_at_dt": entered,
        "assigned_to": "Agent",
        "assigned_user_id": "u1",
        "sla_flags": {},
    }

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    engine = SLAEngineService()
    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        await engine._process_rule_visit_completed(now, now.isoformat(), {"Agent": "u1"})

    assert len(engine._lead_ops) == 1
    doc = engine._lead_ops[0]._doc["$set"]
    assert doc.get("next_action_date")
    assert "sla_flags.visit_completed.3d_at_dt" in doc


def test_sv_followup_2_7d_queues_admin_notification_and_email():
    asyncio.run(_sv_followup_2_7d_queues_admin_notification_and_email())


async def _sv_followup_2_7d_queues_admin_notification_and_email():
    now = utc_now()
    entered = now - timedelta(days=8)
    lead = {
        "id": "lead-sv2-1",
        "first_name": "C",
        "last_name": "D",
        "lead_status": "SV Follow-up 2",
        "sv_followup_2_entered_at_dt": entered,
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
        await engine._process_rule_sv_followup_2(now, now.isoformat(), {"Agent": "u1"})

    assert len(engine._lead_ops) == 1
    assert len(engine._notif_ops) == 1
    assert len(engine._admin_email_ops) == 1
    assert engine._admin_email_ops[0]["admin_user_id"] == "admin-1"
    assert "SV Follow-up 2" in engine._admin_email_ops[0]["subject"]
