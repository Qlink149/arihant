"""New-lead admin alert fires only after pool exhaustion, not on elapsed time alone."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from zoneinfo import ZoneInfo

from crm.services.sla_engine import (
    SLAEngineService,
    _POOL_EXHAUSTED_ALERT_COPY,
)

IST = ZoneInfo("Asia/Kolkata")


def test_pool_exhausted_alert_fires_once_with_exact_copy():
    asyncio.run(_exhausted_alert_fires())


def test_no_alert_without_exhaustion_flag():
    asyncio.run(_no_alert_without_exhaustion())


def test_no_eligible_loop_sets_exhaustion_then_alerts():
    asyncio.run(_no_eligible_then_alert())


def test_off_window_lead_skips_alert():
    asyncio.run(_off_window_skips())


async def _exhausted_alert_fires():
    now = datetime(2026, 6, 2, 14, 0, tzinfo=IST).astimezone(timezone.utc)
    assigned_at = datetime(2026, 6, 2, 11, 0, tzinfo=IST).astimezone(timezone.utc)
    lead = {
        "id": "new-1",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "New",
        "created_at_dt": assigned_at,
        "assigned_at_dt": assigned_at,
        "context_updates": [],
        "sla_flags": {"new": {"pool_chain_exhausted_at_dt": assigned_at}},
    }

    async def fake_paginate(coll, query, **kwargs):
        q = str(query)
        if "pool_chain_exhausted_at_dt" in q and "pool_exhausted_alert_at_dt" in q:
            yield [lead]
        else:
            yield []

    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}, "admins": [{"id": "a1", "full_name": "Admin"}]}

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        await engine._process_rule_new(now, now.isoformat(), {})

    assert len(engine._task_ops) == 1
    task = engine._task_ops[0]._doc
    assert task["description"] == _POOL_EXHAUSTED_ALERT_COPY
    assert task["sla_threshold"] == "pool_exhausted_alert"


async def _no_alert_without_exhaustion():
    now = datetime(2026, 6, 2, 14, 0, tzinfo=IST).astimezone(timezone.utc)
    lead = {
        "id": "new-2",
        "lead_status": "New",
        "created_at_dt": now - timedelta(hours=5),
        "assigned_at_dt": now - timedelta(hours=5),
        "context_updates": [],
        "sla_flags": {},
    }

    async def fake_paginate(coll, query, **kwargs):
        if "pool_exhausted_alert_at_dt" in str(query):
            yield [lead]
        else:
            yield []

    engine = SLAEngineService()
    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        await engine._process_rule_new(now, now.isoformat(), {})
    assert not engine._task_ops


async def _no_eligible_then_alert():
    now_dt = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
    assigned_at = now_dt - timedelta(hours=2)
    lead = {
        "id": "new-3",
        "lead_status": "New",
        "pool_routing": True,
        "pool_key": "reserve-16",
        "created_at_dt": assigned_at,
        "assigned_at_dt": assigned_at,
        "context_updates": [],
        "sla_flags": {
            "new": {
                "no_eligible_tick_count": 2,
                "no_eligible_since_at_dt": assigned_at,
            }
        },
    }

    async def fake_paginate(coll, query, **kwargs):
        if "pool_routing" in str(query):
            yield [lead]
        else:
            yield []

    reassign = AsyncMock(return_value={"ok": False, "reason": "no_eligible", "exhausted": False})
    engine = SLAEngineService()

    with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
        with patch("crm.services.sla_engine.business_seconds_elapsed", return_value=3600):
            with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
                with patch("crm.services.sla_engine.reassign_new_lead_in_pool", reassign):
                    await engine._process_rule_new(now_dt, now_dt.isoformat(), {})

    exhausted = any(
        "pool_chain_exhausted_at_dt" in str(op._doc.get("$set") or {})
        for op in engine._lead_ops
    )
    assert exhausted
    assert reassign.await_count == 1


async def _off_window_skips():
    now = datetime(2026, 6, 7, 14, 0, tzinfo=IST).astimezone(timezone.utc)
    created = datetime(2026, 6, 7, 18, 0, tzinfo=IST).astimezone(timezone.utc)  # Sunday after hours
    lead = {
        "id": "new-4",
        "lead_status": "New",
        "created_at_dt": created,
        "assigned_at_dt": created,
        "context_updates": [],
        "sla_flags": {"new": {"pool_chain_exhausted_at_dt": created}},
    }

    async def fake_paginate(coll, query, **kwargs):
        if "pool_exhausted_alert_at_dt" in str(query):
            yield [lead]
        else:
            yield []

    engine = SLAEngineService()
    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        await engine._process_rule_new(now, now.isoformat(), {})
    assert not engine._task_ops
