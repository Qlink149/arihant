"""RNR escalate query merge, current-status filter, and no Admin ownership transfer."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from crm.constants.lead_kpi import fw_status_indicates_rnr
from crm.services.sla_engine import (
    SLAEngineService,
    _and_query,
    _entered_at_or_updated_fallback,
    _flag_not_set,
    _lead_is_current_rnr,
    _rnr_escalate_match,
    _rnr_status_filter,
)
from crm.utils.helpers import utc_now


def test_rnr_status_filter_is_current_lead_status_only():
    q = _rnr_status_filter()
    blob = str(q)
    assert "lead_status" in q
    assert "original_fw_status" not in blob
    assert "is_rnr" not in q


def test_nurturing_and_contacted_are_not_current_rnr():
    assert not fw_status_indicates_rnr("Nurturing")
    assert not fw_status_indicates_rnr("Contacted")
    assert not fw_status_indicates_rnr("Warm")
    assert not _lead_is_current_rnr({"lead_status": "Nurturing", "is_rnr": True})
    assert not _lead_is_current_rnr({"lead_status": "Contacted", "original_fw_status": "RNR"})
    assert fw_status_indicates_rnr("RNR")
    assert _lead_is_current_rnr({"lead_status": "RNR"})


def test_and_query_keeps_sibling_or_clauses():
    a = {"$or": [{"is_rnr": True}]}
    b = {"$or": [{"updated_at_dt": {"$lt": utc_now()}}]}
    combined = _and_query(a, b, _flag_not_set("sla_flags.rnr.escalate_48h_at_dt"))
    assert "$and" in combined
    assert combined["$and"][0] == a
    assert combined["$and"][1] == b


def test_rnr_escalate_query_keeps_status_and_time():
    cutoff = utc_now()
    q = _rnr_escalate_match(cutoff, "sla_flags.rnr.escalate_48h_at_dt")
    assert "$and" in q
    parts = q["$and"]
    assert any("lead_status" in p for p in parts)
    time_part = _entered_at_or_updated_fallback("rnr_entered_at_dt", cutoff)
    assert time_part in parts
    assert {"sla_flags.rnr.escalate_48h_at_dt": {"$exists": False}} in parts


def test_process_rule_rnr_does_not_reassign_and_queues_admin_tasks():
    asyncio.run(_process_rule_rnr_does_not_reassign_and_queues_admin_tasks())


async def _process_rule_rnr_does_not_reassign_and_queues_admin_tasks():
    now = utc_now()
    lead = {
        "id": "rnr-esc-1",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "RNR",
        "rnr_entered_at_dt": now - timedelta(days=20),
        "assigned_to": "Rep",
        "assigned_user_id": "rep-1",
        "sla_flags": {},
    }
    captured = []

    def capture_task(*args, **kwargs):
        captured.append({"args": args, "kwargs": kwargs})

    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    fake_tasks = MagicMock()
    fake_tasks.find_one = AsyncMock(return_value={"id": "existing-reminder"})

    with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
        with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
            with patch("crm.services.sla_engine.db") as mock_db:
                mock_db.tasks = fake_tasks
                mock_db.leads = MagicMock()
                mock_db.leads.update_one = AsyncMock()
                with patch("crm.services.sla_helpers.assign_lead_to_admin", new_callable=AsyncMock) as mock_assign:
                    with patch.object(engine, "_queue_task", side_effect=capture_task):
                        await engine._process_rule_rnr(now, now.isoformat(), {"Rep": "rep-1"})
                    mock_assign.assert_not_called()
                mock_db.leads.update_one.assert_not_called()

    escalate = [c["kwargs"] for c in captured if c["kwargs"].get("sla_rule") == "rnr"]
    thresholds = {c.get("sla_threshold") for c in escalate}
    assert {"24h", "48h", "15d"} <= thresholds
    for c in escalate:
        if c.get("sla_threshold") in ("24h", "48h", "15d"):
            assert c.get("escalation_target") == "admin"


def test_process_rule_rnr_skips_nurturing_lead():
    asyncio.run(_process_rule_rnr_skips_nurturing_lead())


async def _process_rule_rnr_skips_nurturing_lead():
    now = utc_now()
    lead = {
        "id": "nurture-1",
        "first_name": "Bharathi",
        "last_name": "Raja",
        "lead_status": "Nurturing",
        "is_rnr": True,
        "original_fw_status": "RNR",
        "updated_at_dt": now - timedelta(days=5),
        "assigned_to": "Rep",
        "assigned_user_id": "rep-1",
        "sla_flags": {},
    }
    captured = []

    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    fake_tasks = MagicMock()
    fake_tasks.find_one = AsyncMock(return_value=None)

    with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
        with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
            with patch("crm.services.sla_engine.db") as mock_db:
                mock_db.tasks = fake_tasks
                with patch.object(engine, "_queue_task", side_effect=lambda *a, **k: captured.append(k)):
                    await engine._process_rule_rnr(now, now.isoformat(), {"Rep": "rep-1"})

    assert captured == []
