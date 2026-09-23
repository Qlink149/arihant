"""T10 Escalation Queue: raise on whitelist via SLA engine; clear hooks; negative cases."""

import asyncio
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.escalation_queue import (
    CLEAR_ACTIONS,
    build_raise_state,
    clear_escalation_if_active,
    pair_is_queue_rule,
)
from crm.services.sla_engine import SLAEngineService
from crm.utils.helpers import utc_now


@contextmanager
def _phase3_enabled():
    with patch("crm.services.sla_engine.phase3_rules_enabled", return_value=True):
        yield


def _escalated_lead(**overrides):
    now = utc_now()
    base = {
        "id": "eq-lead-1",
        "first_name": "Esc",
        "last_name": "Lead",
        "lead_status": "Interested",
        "interested_entered_at_dt": now - timedelta(days=15),
        "assigned_to": "Rep",
        "assigned_user_id": "rep-1",
        "sla_flags": {},
        "escalation": {"active": True, "reasons": [{"sla_rule": "rnr", "sla_threshold": "escalate_d7"}]},
    }
    base.update(overrides)
    return base


def test_whitelist_pairs_include_rnr_d7_and_exclude_legacy_rnr_24h():
    assert pair_is_queue_rule("rnr", "escalate_d7")
    assert pair_is_queue_rule("interested", "escalate_14d")
    assert not pair_is_queue_rule("rnr", "24h")
    assert not pair_is_queue_rule("rnr", "reminder_a2")
    assert not pair_is_queue_rule("contacted", "48h")


def test_engine_raises_escalation_on_whitelisted_pair_process_all_slas_path():
    asyncio.run(_engine_raises_escalation_on_whitelisted_pair())


async def _engine_raises_escalation_on_whitelisted_pair():
    now = utc_now()
    lead = {
        "id": "eq-int-1",
        "first_name": "A",
        "last_name": "B",
        "lead_status": "Interested",
        "interested_entered_at_dt": now - timedelta(days=15),
        "assigned_to": "Rep",
        "assigned_user_id": "rep-1",
        "sla_flags": {},
    }
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "admin-1", "full_name": "Admin"}}

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    with _phase3_enabled():
        with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
            await engine._process_rule_interested(now, now.isoformat(), {"Rep": "rep-1"})

    raise_ops = [
        op
        for op in engine._lead_ops
        if (op._doc.get("$set") or {}).get("escalation.active") is True
    ]
    assert len(raise_ops) == 1
    reasons = raise_ops[0]._doc["$set"]["escalation.reasons"]
    assert any(r.get("sla_threshold") == "escalate_14d" for r in reasons)
    assert any(
        op._doc.get("sla_threshold") == "escalate_14d" for op in engine._task_ops
    )


def test_engine_does_not_raise_on_non_whitelisted_threshold():
    asyncio.run(_engine_does_not_raise_on_non_whitelisted_threshold())


async def _engine_does_not_raise_on_non_whitelisted_threshold():
    now = utc_now()
    lead = {
        "id": "eq-rnr-rem",
        "first_name": "R",
        "last_name": "N",
        "lead_status": "RNR",
        "pool_key": "reserve-16",
        "rnr_entered_at_dt": now - timedelta(hours=30),
        "assigned_to": "Rep",
        "assigned_user_id": "rep-1",
        "sla_flags": {},
        "escalation": {"active": False, "reasons": []},
    }
    engine = SLAEngineService()
    engine._escalation_targets = {"admin": {"id": "admin-1", "full_name": "Admin"}}
    mock_db = MagicMock()
    mock_db.tasks.update_many = AsyncMock()

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    with _phase3_enabled():
        with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
            with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
                with patch("crm.services.sla_engine.db", mock_db):
                    with patch(
                        "crm.services.sla_engine.reassign_lead_in_pool",
                        AsyncMock(return_value={"ok": False}),
                    ):
                        await engine._process_rule_rnr(now, now.isoformat(), {"Rep": "rep-1"})

    reminder_tasks = [
        op for op in engine._task_ops if op._doc.get("sla_threshold") == "reminder_a2"
    ]
    assert len(reminder_tasks) == 1
    raise_ops = [
        op
        for op in engine._lead_ops
        if (op._doc.get("$set") or {}).get("escalation.active") is True
    ]
    assert raise_ops == []


def test_clear_escalation_for_each_sop_action():
    asyncio.run(_clear_escalation_for_each_sop_action())


async def _clear_escalation_for_each_sop_action():
    """SOP clear actions: status_change, reassign, note, call, nudge (+ rnr_attempt, terminal)."""
    for action in sorted(CLEAR_ACTIONS):
        lead = _escalated_lead(id=f"eq-clear-{action}")
        mock_db = MagicMock()
        mock_db.leads.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

        with patch("crm.services.escalation_queue.db", mock_db):
            cleared = await clear_escalation_if_active(
                lead["id"],
                action=action,
                actor_user_id="u1",
                actor_name="Agent",
                lead=lead,
            )

        assert cleared is True
        mock_db.leads.update_one.assert_awaited_once()
        update = mock_db.leads.update_one.await_args[0][1]
        assert update["$set"]["escalation.active"] is False
        assert update["$push"]["context_updates"]["type"] == "escalation_clear"
        stored = "call" if action == "rnr_attempt" else action
        assert update["$push"]["context_updates"]["action"] == stored


def test_clear_escalation_ignored_for_unknown_action():
    asyncio.run(_clear_escalation_ignored_for_unknown_action())


async def _clear_escalation_ignored_for_unknown_action():
    lead = _escalated_lead()
    mock_db = MagicMock()
    mock_db.leads.update_one = AsyncMock()

    with patch("crm.services.escalation_queue.db", mock_db):
        cleared = await clear_escalation_if_active(
            lead["id"],
            action="sla_system_reassign",
            actor_user_id="system",
            actor_name="SLA Engine",
            lead=lead,
        )

    assert cleared is False
    mock_db.leads.update_one.assert_not_awaited()


def test_sla_rnr_d4_pool_reassign_does_not_clear_escalation():
    asyncio.run(_sla_rnr_d4_pool_reassign_does_not_clear_escalation())


async def _sla_rnr_d4_pool_reassign_does_not_clear_escalation():
    now = utc_now()
    lead = {
        "id": "eq-d4-1",
        "first_name": "D",
        "last_name": "4",
        "lead_status": "RNR",
        "pool_key": "reserve-16",
        "rnr_entered_at_dt": now - timedelta(hours=80),
        "assigned_to": "Rep",
        "assigned_user_id": "rep-1",
        "sla_flags": {},
        "escalation": {
            "active": True,
            "raised_at_dt": now - timedelta(hours=1),
            "reasons": [{"sla_rule": "rnr", "sla_threshold": "escalate_d7"}],
        },
    }
    engine = SLAEngineService()
    mock_db = MagicMock()
    mock_db.tasks.update_many = AsyncMock()

    async def fake_paginate(collection, query, projection=None, batch_size=200):
        yield [lead]

    clear_mock = AsyncMock(return_value=True)

    with _phase3_enabled():
        with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
            with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
                with patch("crm.services.sla_engine.db", mock_db):
                    with patch(
                        "crm.services.sla_engine.reassign_lead_in_pool",
                        AsyncMock(
                            return_value={
                                "ok": True,
                                "assigned_user_id": "rep-2",
                                "assigned_to": "Rep2",
                                "previous_assigned_user_id": "rep-1",
                                "previous_assigned_to": "Rep",
                            }
                        ),
                    ):
                        with patch("crm.services.sla_engine.create_notification", AsyncMock()):
                            with patch(
                                "crm.services.escalation_queue.clear_escalation_if_active",
                                clear_mock,
                            ):
                                await engine._process_rule_rnr(
                                    now, now.isoformat(), {"Rep": "rep-1"}
                                )

    clear_mock.assert_not_awaited()


def test_mcube_inbound_call_does_not_clear_escalation_outbound_does():
    asyncio.run(_mcube_inbound_call_does_not_clear_escalation_outbound_does())


async def _mcube_inbound_call_does_not_clear_escalation_outbound_does():
    from crm.services.mcube.process import _process_inbound_payload

    lead = {
        "id": "eq-mcube-1",
        "first_name": "M",
        "last_name": "C",
        "assigned_user_id": "rep-1",
        "assigned_to": "Rep",
        "escalation": {"active": True},
        "context_updates": [],
    }
    agent = {"id": "rep-1", "full_name": "Rep", "email": "rep@example.com"}
    base_payload = {
        "token": "test",
        "callid": "c-1",
        "callfrom": "911111111111",
        "empnumber": "999",
        "dialstatus": "ANSWER",
        "starttime": "2026-09-23 10:00:00",
        "endtime": "2026-09-23 10:01:00",
        "filename": "",
        "empemail": "rep@example.com",
    }

    clear_mock = AsyncMock(return_value=True)

    async def run_payload(direction: str):
        payload = {**base_payload, "direction": direction}
        call = {
            "id": f"call-{direction}",
            "call_id": f"call-{direction}",
            "direction": direction,
            "is_finalized": True,
        }
        with patch(
            "crm.services.mcube.process.match_user_by_agent",
            AsyncMock(return_value=agent),
        ):
            with patch(
                "crm.services.mcube.process.match_lead_by_customer_phone",
                AsyncMock(return_value=(lead, "exact", [lead["id"]])),
            ):
                with patch("crm.services.mcube.process.db") as mock_db:
                    mock_db.leads.find_one = AsyncMock(return_value=lead)
                    with patch(
                        "crm.services.mcube.process.upsert_call_from_inbound",
                        AsyncMock(return_value=call),
                    ):
                        with patch(
                            "crm.services.mcube.process.apply_mcube_inbound_assignment",
                            AsyncMock(return_value=True),
                        ):
                            with patch(
                                "crm.services.mcube.process.record_call_on_lead",
                                AsyncMock(),
                            ):
                                with patch(
                                    "crm.services.escalation_queue.clear_escalation_if_active",
                                    clear_mock,
                                ):
                                    await _process_inbound_payload(
                                        payload, event_id=f"evt-{direction}"
                                    )

    await run_payload("inbound")
    clear_mock.assert_not_awaited()

    clear_mock.reset_mock()
    await run_payload("outbound")
    clear_mock.assert_awaited_once()
    assert clear_mock.await_args.kwargs.get("action") == "call"


def test_build_raise_state_idempotent_for_same_pair():
    now = utc_now()
    lead = {"id": "x", "escalation": {"active": True, "reasons": []}}
    set1, _ = build_raise_state(lead, "rnr", "escalate_d7", now)
    lead2 = {**lead, **{k.replace("escalation.", ""): v for k, v in set1.items() if k.startswith("escalation.")}}
    lead2["escalation"] = set1.get("escalation.reasons") and {
        "active": set1["escalation.active"],
        "reasons": set1["escalation.reasons"],
        "raised_at_dt": set1["escalation.raised_at_dt"],
    }
    set2, entry2 = build_raise_state(lead2, "rnr", "escalate_d7", now)
    assert len(set2["escalation.reasons"]) == 1
    assert entry2["type"] == "escalation_raise"
