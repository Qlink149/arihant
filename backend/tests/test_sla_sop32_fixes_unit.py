"""SOP v3.2 verification fixes in the SLA layer:
  - re-entry into a stage can create its tasks again (dedupe keys released on stage change)
  - Contacted 48h task / 72h alert only for leads with no outcome logged in THIS stay
  - SLA tasks default to the IST due date (queues compare IST)
  - Future Prospect review counters restart on re-entry
  - Contacted 7-day reassign raises Admin when no other agent is available (business hours, 3 ticks)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crm.services import sla_helpers
from crm.services.sla_engine import (
    CONTACTED_REASSIGN_INTERVAL_DAYS,
    SLAEngineService,
    build_task_doc,
    outcome_logged_this_stay,
)
from crm.utils.helpers import utc_now


# ------------------------------------------------------------ dedupe release
@pytest.mark.asyncio
async def test_release_moves_keys_for_this_lead_only(monkeypatch):
    mock_db = MagicMock()
    mock_db.tasks.update_many = AsyncMock()
    mock_db.notifications.update_many = AsyncMock()
    monkeypatch.setattr(sla_helpers, "db", mock_db)

    await sla_helpers.release_sla_dedupe_keys("lead-9")

    t_filter, t_update = mock_db.tasks.update_many.await_args.args
    assert t_filter == {"lead_id": "lead-9", "source": "sla", "dedupe_key": {"$exists": True}}
    # the old key is kept for audit under dedupe_key_retired, then dropped from dedupe_key
    assert t_update == [{"$set": {"dedupe_key_retired": "$dedupe_key"}}, {"$unset": "dedupe_key"}]

    n_filter, n_update = mock_db.notifications.update_many.await_args.args
    assert n_filter["lead_id"] == "lead-9"
    assert n_update == t_update
    import re

    pat = re.compile(n_filter["dedupe_key"]["$regex"])
    for key in ("notif:sla:negotiation:48h:L1", "notif:sla:contacted:72h:L1:u9", "rnr_d4:new:L1", "contacted_reassign:prev:L1:2026-10-07"):
        assert pat.search(key), key
    # unrelated notification keys are left alone
    for key in ("lead_status_changed:L1", "lead_assigned:L1:u2", "mention:abc"):
        assert not pat.search(key), key


@pytest.mark.asyncio
async def test_status_change_releases_sla_dedupe_keys():
    """update_lead frees the keys on a stage change, and not on a plain field edit."""
    import importlib.util
    from pathlib import Path

    from crm.models.schemas.lead_schemas import LeadUpdatePatch
    import crm.services.lead_service as lead_service

    spec = importlib.util.spec_from_file_location(
        "mq_fixture", Path(__file__).parent / "test_meta_qualified_update_unit.py"
    )
    mq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mq)

    async def run(patch_obj):
        db, _ = mq._make_db(mq._base_lead(status="Contacted", source="Direct Walk-in"))
        patches = mq._patch_lead_service(db)
        mq._enter_all(patches)
        release = AsyncMock()
        try:
            with patch.object(lead_service, "release_sla_dedupe_keys", release):
                await lead_service.update_lead("lead-mq", patch_obj, {"id": "u1", "full_name": "T"})
        finally:
            mq._stop_all(patches)
        return release

    moved = await run(LeadUpdatePatch(lead_status="Nurturing", nurture_temperature="Warm"))
    moved.assert_awaited_once_with("lead-mq")
    edited = await run(LeadUpdatePatch(budget="2 Cr"))
    edited.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_change_survives_release_failure():
    import importlib.util
    from pathlib import Path

    from crm.models.schemas.lead_schemas import LeadUpdatePatch
    import crm.services.lead_service as lead_service

    spec = importlib.util.spec_from_file_location(
        "mq_fixture2", Path(__file__).parent / "test_meta_qualified_update_unit.py"
    )
    mq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mq)
    db, leads = mq._make_db(mq._base_lead(status="Contacted", source="Direct Walk-in"))
    patches = mq._patch_lead_service(db)
    mq._enter_all(patches)
    try:
        with patch.object(lead_service, "release_sla_dedupe_keys", AsyncMock(side_effect=RuntimeError("db down"))):
            await lead_service.update_lead(
                "lead-mq", LeadUpdatePatch(lead_status="Nurturing", nurture_temperature="Hot"), {"id": "u1", "full_name": "T"}
            )
    finally:
        mq._stop_all(patches)
    assert leads._lead["lead_status"] == "Nurturing"  # the status change itself is never blocked


# --------------------------------------------------------- outcome this stay
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "lead,expected",
    [
        ({}, False),
        ({"logged_outcome": ""}, False),
        # outcome logged after entering Contacted -> counts
        ({"logged_outcome": "Interested", "logged_outcome_at_dt": NOW, "contacted_at_dt": NOW - timedelta(hours=5)}, True),
        # outcome from an EARLIER stay -> does not count for the new one
        ({"logged_outcome": "Interested", "logged_outcome_at_dt": NOW - timedelta(days=9), "contacted_at_dt": NOW - timedelta(hours=5)}, False),
        # legacy lead: outcome with no timestamp keeps the old behaviour
        ({"logged_outcome": "Interested", "contacted_at_dt": NOW - timedelta(hours=5)}, True),
    ],
)
def test_outcome_logged_this_stay(lead, expected):
    assert outcome_logged_this_stay(lead) is expected


async def _run_contacted_rule(lead):
    engine = SLAEngineService()
    engine._queue_task = MagicMock()

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
        await engine._process_rule_contacted(NOW, NOW.isoformat(), {})
    return engine._queue_task


@pytest.mark.asyncio
async def test_contacted_48h_and_72h_skipped_when_outcome_logged_this_stay():
    lead = {"id": "c1", "logged_outcome": "Needs Time", "logged_outcome_at_dt": NOW - timedelta(hours=1),
            "contacted_at_dt": NOW - timedelta(hours=80)}
    queue = await _run_contacted_rule(lead)
    queue.assert_not_called()


@pytest.mark.asyncio
async def test_contacted_tasks_fire_when_only_a_stale_outcome_exists():
    lead = {"id": "c1", "logged_outcome": "Needs Time", "logged_outcome_at_dt": NOW - timedelta(days=20),
            "contacted_at_dt": NOW - timedelta(hours=80)}
    queue = await _run_contacted_rule(lead)
    thresholds = {c.kwargs.get("sla_threshold") for c in queue.call_args_list}
    assert thresholds == {"48h", "72h"}


@pytest.mark.asyncio
async def test_contacted_tasks_fire_without_any_outcome():
    queue = await _run_contacted_rule({"id": "c1", "contacted_at_dt": NOW - timedelta(hours=80)})
    assert queue.call_count == 2


# ------------------------------------------------------------- IST due date
def test_sla_task_due_date_is_the_ist_day():
    # 20:00 UTC on 7 Oct is 01:30 IST on 8 Oct: the due date must be the IST day
    now_dt = datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc)
    task = build_task_doc(
        lead={"id": "l1", "assigned_to": "R", "assigned_user_id": "u1"},
        description="x", dedupe_key="k", now_dt=now_dt, now_iso=now_dt.isoformat(), name_to_user_id={},
    )
    assert task["due_date"] == "2026-10-08"
    # and an afternoon UTC time is the same calendar day in both zones
    noon = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)
    t2 = build_task_doc(
        lead={"id": "l1", "assigned_to": "R", "assigned_user_id": "u1"},
        description="x", dedupe_key="k2", now_dt=noon, now_iso=noon.isoformat(), name_to_user_id={},
    )
    assert t2["due_date"] == "2026-10-07"


def test_explicit_due_date_is_respected():
    now_dt = datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc)
    task = build_task_doc(
        lead={"id": "l1", "assigned_to": "R", "assigned_user_id": "u1"},
        description="x", dedupe_key="k", now_dt=now_dt, now_iso=now_dt.isoformat(),
        name_to_user_id={}, due_date="2026-10-20",
    )
    assert task["due_date"] == "2026-10-20"


# -------------------------------------------------- FP counters on re-entry
@pytest.mark.asyncio
async def test_future_prospect_entry_resets_review_counters():
    import importlib.util
    from pathlib import Path

    from crm.models.schemas.lead_schemas import LeadUpdatePatch
    import crm.services.lead_service as lead_service

    spec = importlib.util.spec_from_file_location("mq_fixture3", Path(__file__).parent / "test_meta_qualified_update_unit.py")
    mq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mq)
    db, leads = mq._make_db(mq._base_lead(status="Contacted", source="Direct Walk-in"))
    unsets = []
    orig = leads.update_one

    async def spy(query, update):
        if "$unset" in update:
            unsets.append(set(update["$unset"]))
        return await orig(query, update)

    leads.update_one = spy
    patches = mq._patch_lead_service(db)
    mq._enter_all(patches)
    try:
        await lead_service.update_lead("lead-mq", LeadUpdatePatch(lead_status="Future Prospect"), {"id": "u1", "full_name": "T"})
    finally:
        mq._stop_all(patches)
    assert any({"fp_cycle_count", "fp_last_checkin_task_created_at_dt", "sla_flags.future_prospect"} <= u for u in unsets)


# --------------------------------------------- Contacted 7d: no agent -> Admin
def _lead7(**ov):
    now = utc_now()
    base = {
        "id": "c1", "first_name": "A", "last_name": "B", "lead_status": "Contacted",
        "contacted_at_dt": now - timedelta(days=CONTACTED_REASSIGN_INTERVAL_DAYS + 1),
        "assigned_to": "Rep1", "assigned_user_id": "u1", "project_id": "reserve-16", "sla_flags": {},
    }
    base.update(ov)
    return base


async def _run7(lead, *, hours_ok: bool):
    now = utc_now()
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "a1", "full_name": "Admin"}}
    engine._queue_task = MagicMock()

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    with patch("crm.services.sla_engine._paginate_leads", fake_paginate), patch(
        "crm.services.sla_engine._lead_has_pending_task", AsyncMock(return_value=False)
    ), patch(
        "crm.services.sla_engine.reassign_lead_in_pool",
        AsyncMock(return_value={"ok": False, "reason": "no_eligible", "exhausted": False}),
    ), patch("crm.services.sla_engine.create_notification", AsyncMock()), patch(
        "crm.services.sla_engine.is_business_hours_ist", return_value=hours_ok
    ):
        await engine._process_contacted_reassign(now, now.isoformat(), {"Rep1": "u1"})
    return engine


@pytest.mark.asyncio
async def test_contacted_7d_no_agent_first_ticks_only_count():
    engine = await _run7(_lead7(), hours_ok=True)
    engine._queue_task.assert_not_called()
    assert len(engine._lead_ops) == 1  # the tick is recorded


@pytest.mark.asyncio
async def test_contacted_7d_no_agent_raises_admin_after_three_ticks():
    lead = _lead7(sla_flags={"contacted": {"no_eligible_tick_count": 2}})
    engine = await _run7(lead, hours_ok=True)
    engine._queue_task.assert_called_once()
    kw = engine._queue_task.call_args.kwargs
    assert kw["escalation_target"] == "admin" and kw["sla_threshold"] == "reassign_exhausted"


@pytest.mark.asyncio
async def test_contacted_7d_no_agent_outside_business_hours_never_raises():
    """After hours nobody is routable - that must not turn into Admin tasks."""
    lead = _lead7(sla_flags={"contacted": {"no_eligible_tick_count": 50}})
    engine = await _run7(lead, hours_ok=False)
    engine._queue_task.assert_not_called()
    assert not engine._lead_ops


# ------------------------------------------------------------ SLA hold
def test_sla_engine_skips_held_leads():
    engine = SLAEngineService()
    q = engine._rule_query({"lead_status": "Contacted"})
    assert {"sla_paused": {"$ne": True}} in q["$and"]


@pytest.mark.asyncio
async def test_csv_import_puts_leads_on_sla_hold_and_status_change_releases_it():
    """SOP 2.3: held at import; the first status change (update_lead) clears the hold."""
    import importlib.util
    from contextlib import ExitStack
    from pathlib import Path

    import crm.services.lead_service as lead_service

    spec = importlib.util.spec_from_file_location("csv_fixture2", Path(__file__).parent / "test_import_csv_unit.py")
    csv_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(csv_mod)

    db = csv_mod._DummyDB()
    with ExitStack() as stack:
        csv_mod._apply_patches(stack, db)
        result = await lead_service.import_csv(
            csv_mod._Upload("First name,Last Name,Mobile,Status\nCsv,Lead,8888888803,New"),
            {"id": "u1", "full_name": "Admin"},
        )
    assert result["imported"] == 1
    assert db.leads.inserted[0]["sla_paused"] is True
