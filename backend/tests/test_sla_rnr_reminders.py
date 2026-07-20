"""RNR SLA: cap 3 reminders, skip when an open reminder already exists."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.sla_engine import (
    IST,
    SLAEngineService,
    _RNR_REMINDER_MAX_BUCKETS,
    build_task_doc,
)
from crm.utils.helpers import utc_now


def test_rnr_reminder_max_buckets_constant():
    assert _RNR_REMINDER_MAX_BUCKETS == 3


def test_rnr_skips_when_open_reminder_exists():
    asyncio.run(_rnr_skips_when_open_reminder_exists())


async def _rnr_skips_when_open_reminder_exists():
    now = utc_now()
    # Far enough in the past that periods >= 1 (and likely > 3)
    lead = {
        "id": "rnr-lead-1",
        "first_name": "Ruchi",
        "last_name": "Khan",
        "lead_status": "RNR",
        "rnr_entered_at_dt": now - timedelta(days=20),
        "assigned_to": "Gowtham j",
        "assigned_user_id": "rep-1",
        "sla_flags": {},
    }
    captured = []

    def capture_task(*args, **kwargs):
        captured.append({"args": args, "kwargs": kwargs})

    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        # Reminder query has no escalate flag filter; escalation queries do
        q = str(query)
        if "escalate_" in q:
            yield []
        else:
            yield [lead]

    fake_tasks = MagicMock()
    fake_tasks.find_one = AsyncMock(return_value={"id": "existing-reminder"})

    with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
        with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
            with patch("crm.services.sla_engine.db") as mock_db:
                mock_db.tasks = fake_tasks
                mock_db.leads = MagicMock()
                with patch.object(engine, "_queue_task", side_effect=capture_task):
                    await engine._process_rule_rnr(
                        now, now.isoformat(), {"Gowtham j": "rep-1"}
                    )

    reminder_calls = [
        c for c in captured if (c["kwargs"].get("sla_threshold") or "").startswith("reminder_")
    ]
    assert reminder_calls == []
    fake_tasks.find_one.assert_awaited()


def test_rnr_queues_capped_bucket_with_ist_due_date():
    asyncio.run(_rnr_queues_capped_bucket_with_ist_due_date())


async def _rnr_queues_capped_bucket_with_ist_due_date():
    now = utc_now()
    lead = {
        "id": "rnr-lead-2",
        "first_name": "Ruchi",
        "last_name": "Khan",
        "lead_status": "RNR",
        "rnr_entered_at_dt": now - timedelta(days=20),
        "assigned_to": "Gowtham j",
        "assigned_user_id": "rep-1",
        "sla_flags": {},
    }
    captured = []

    def capture_task(*args, **kwargs):
        captured.append({"args": args, "kwargs": kwargs})

    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        q = str(query)
        if "escalate_" in q:
            yield []
        else:
            yield [lead]

    fake_tasks = MagicMock()
    fake_tasks.find_one = AsyncMock(return_value=None)

    with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
        with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
            with patch("crm.services.sla_engine.db") as mock_db:
                mock_db.tasks = fake_tasks
                mock_db.leads = MagicMock()
                with patch.object(engine, "_queue_task", side_effect=capture_task):
                    await engine._process_rule_rnr(
                        now, now.isoformat(), {"Gowtham j": "rep-1"}
                    )

    reminder_calls = [
        c for c in captured if (c["kwargs"].get("sla_threshold") or "").startswith("reminder_")
    ]
    assert len(reminder_calls) == 1
    call = reminder_calls[0]
    assert call["kwargs"]["sla_threshold"] == "reminder_3"
    assert call["kwargs"]["due_date"] == now.astimezone(IST).date().isoformat()
    # dedupe key is 2nd positional arg after lead, description
    assert call["args"][2] == "sla:rnr:reminder:rnr-lead-2:3"


def test_rnr_skips_bucket_when_flag_already_set():
    asyncio.run(_rnr_skips_bucket_when_flag_already_set())


async def _rnr_skips_bucket_when_flag_already_set():
    now = utc_now()
    lead = {
        "id": "rnr-lead-3",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "RNR",
        "rnr_entered_at_dt": now - timedelta(days=20),
        "assigned_to": "Rep",
        "assigned_user_id": "rep-1",
        "sla_flags": {"rnr": {"reminder_3_at_dt": now}},
    }
    captured = []

    def capture_task(*args, **kwargs):
        captured.append(kwargs)

    engine = SLAEngineService()

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        q = str(query)
        if "escalate_" in q:
            yield []
        else:
            yield [lead]

    fake_tasks = MagicMock()
    fake_tasks.find_one = AsyncMock(return_value=None)

    with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
        with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
            with patch("crm.services.sla_engine.db") as mock_db:
                mock_db.tasks = fake_tasks
                with patch.object(engine, "_queue_task", side_effect=capture_task):
                    await engine._process_rule_rnr(now, now.isoformat(), {"Rep": "rep-1"})

    assert not any(
        (c.get("sla_threshold") or "").startswith("reminder_") for c in captured
    )


def test_build_task_doc_accepts_ist_due_date():
    now = utc_now()
    today_ist = now.astimezone(IST).date().isoformat()
    task = build_task_doc(
        lead={
            "id": "l1",
            "first_name": "A",
            "last_name": "B",
            "assigned_to": "Rep",
            "assigned_user_id": "rep-1",
        },
        description="RNR Reminder",
        dedupe_key="sla:rnr:reminder:l1:1",
        now_dt=now,
        now_iso=now.isoformat(),
        name_to_user_id={"Rep": "rep-1"},
        due_date=today_ist,
        sla_rule="rnr",
        sla_threshold="reminder_1",
    )
    assert task is not None
    assert task["due_date"] == today_ist
    assert task["sla_threshold"] == "reminder_1"
