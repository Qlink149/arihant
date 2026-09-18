"""MCUBE inbound process + SLA non-interference (mocked Mongo)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.mcube.calls import map_inbound_fields
from crm.services.mcube.process import _process_inbound_payload
from crm.services.mcube.timeline import append_call_timeline_entry
from crm.utils.helpers import utc_now

FIXTURE = Path(__file__).parent / "fixtures" / "mcube_inbound_hangup_arihant.json"


def _fixture_payload() -> dict:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {k.lower(): v for k, v in data.items()}


def test_map_live_hangup_fixture():
    mapped = map_inbound_fields(_fixture_payload())
    assert mapped["call_id"] == "951445294217889356146aa0fdbe07b05"
    assert mapped["customer_number_10"] == "9514452942"
    assert mapped["agent_number_10"] == "9841544444"
    assert mapped["empemail"] == "malathy@arihants.co.in"
    assert mapped["status"] == "ANSWERED"
    assert mapped["is_answered"] is True
    assert mapped["duration_seconds"] == 193
    assert mapped["recording_available"] is True
    assert "recordings.mcube.com" in mapped["recording_url"]
    assert mapped["is_finalized"] is True


def test_append_call_timeline_entry_does_not_set_updated_at():
    asyncio.run(_append_call_timeline_entry_does_not_set_updated_at())


async def _append_call_timeline_entry_does_not_set_updated_at():
    mock_db = MagicMock()
    mock_db.leads.update_one = AsyncMock()
    call_dt = utc_now()
    with patch("crm.services.mcube.timeline.db", mock_db):
        await append_call_timeline_entry(
            "lead-1",
            {"type": "call", "description": "test"},
            call_dt,
        )
    args, kwargs = mock_db.leads.update_one.call_args
    assert args[0] == {"id": "lead-1"}
    update = args[1]
    assert "$push" in update
    assert update["$set"] == {"last_call_at_dt": call_dt}
    assert "updated_at" not in update.get("$set", {})
    assert "updated_at_dt" not in update.get("$set", {})


def test_process_inbound_sla_non_interference():
    asyncio.run(_process_inbound_sla_non_interference())


async def _process_inbound_sla_non_interference():
    payload = _fixture_payload()
    frozen = utc_now()
    lead = {
        "id": "lead-mcube-1",
        "first_name": "Cust",
        "last_name": "One",
        "lead_status": "Nurturing",
        "assigned_user_id": "owner-1",
        "assigned_to": "Owner",
        "updated_at_dt": frozen,
        "context_updates": [],
    }
    user = {
        "id": "agent-1",
        "full_name": "Malathy",
        "email": "malathy@arihants.co.in",
    }

    mock_db = MagicMock()
    mock_db.calls.find_one = AsyncMock(return_value=None)
    mock_db.calls.insert_one = AsyncMock()
    mock_db.calls.update_one = AsyncMock()
    mock_db.leads.find_one = AsyncMock(return_value={**lead, "context_updates": []})
    mock_db.leads.update_one = AsyncMock()
    mock_db.lead_events.insert_one = AsyncMock()
    mock_db.notifications.find_one = AsyncMock(return_value=None)
    mock_db.notifications.insert_one = AsyncMock()

    with (
        patch("crm.services.mcube.process.MCUBE_ENABLED", True),
        patch("crm.services.mcube.process.match_lead_by_customer_phone", AsyncMock(return_value=(lead, "phone_primary", [lead["id"]]))),
        patch("crm.services.mcube.process.match_user_by_agent", AsyncMock(return_value=user)),
        patch("crm.services.mcube.process.apply_mcube_inbound_assignment", AsyncMock(return_value=True)),
        patch("crm.services.mcube.calls.db", mock_db),
        patch("crm.services.mcube.timeline.db", mock_db),
        patch("crm.services.mcube.process.db", mock_db),
        patch("crm.services.lead_events.db", mock_db),
        patch("crm.services.notification_service.db", mock_db),
        patch("crm.services.notification_service.notifications_stream.publish", AsyncMock()),
    ):
        result = await _process_inbound_payload(payload, event_id="evt-1")

    assert result["ok"] is True
    assert result["lead_id"] == lead["id"]
    # Lead updates must never include updated_at_dt
    for call in mock_db.leads.update_one.await_args_list:
        update = call.args[1]
        set_fields = update.get("$set") or {}
        assert "updated_at" not in set_fields
        assert "updated_at_dt" not in set_fields
    assert lead["updated_at_dt"] is frozen


def test_ambiguous_match_does_not_attach_lead_id_on_call_doc_path():
    asyncio.run(_ambiguous())


async def _ambiguous():
    payload = _fixture_payload()
    payload["dialstatus"] = "NoAnswer"
    mock_db = MagicMock()
    mock_db.calls.find_one = AsyncMock(return_value=None)
    mock_db.calls.insert_one = AsyncMock()
    find_cursor = MagicMock()
    find_cursor.to_list = AsyncMock(return_value=[{"id": "admin-1", "full_name": "Admin"}])
    mock_db.users.find = MagicMock(return_value=find_cursor)
    mock_db.notifications.find_one = AsyncMock(return_value=None)
    mock_db.notifications.insert_one = AsyncMock()

    with (
        patch("crm.services.mcube.process.MCUBE_ENABLED", True),
        patch(
            "crm.services.mcube.process.match_lead_by_customer_phone",
            AsyncMock(return_value=(None, "ambiguous", ["a", "b"])),
        ),
        patch("crm.services.mcube.process.match_user_by_agent", AsyncMock(return_value=None)),
        patch("crm.services.mcube.process.apply_mcube_inbound_assignment", AsyncMock(return_value=False)),
        patch("crm.services.mcube.calls.db", mock_db),
        patch("crm.services.mcube.process.db", mock_db),
        patch("crm.services.mcube.match.db", mock_db),
        patch("crm.services.notification_service.db", mock_db),
        patch("crm.services.notification_service.notifications_stream.publish", AsyncMock()),
    ):
        result = await _process_inbound_payload(payload, event_id="evt-2")

    assert result["lead_id"] is None
    assert result["lead_match_method"] == "ambiguous"
    # insert_one should have been called with no lead_id / lead_id None
    inserted = mock_db.calls.insert_one.await_args.args[0]
    assert inserted.get("lead_id") in (None, "")
    assert inserted.get("lead_match_method") == "ambiguous"


def test_ping_payload_skipped_without_calls_insert():
    asyncio.run(_ping_payload_skipped_without_calls_insert())


async def _ping_payload_skipped_without_calls_insert():
    with patch("crm.services.mcube.process.MCUBE_ENABLED", True):
        result = await _process_inbound_payload({"token": "only"}, event_id="evt-ping")
    assert result["skipped"] is True
    assert result["skip_reason"] == "skipped_ping"


def test_unmatched_finalized_auto_creates_lead_and_timeline():
    asyncio.run(_unmatched_finalized_auto_creates_lead_and_timeline())


async def _unmatched_finalized_auto_creates_lead_and_timeline():
    payload = _fixture_payload()
    payload["callid"] = "auto-create-call-1"
    payload["callfrom"] = "9916043625"
    new_lead = {
        "id": "lead-auto-1",
        "first_name": "Inbound",
        "last_name": "3625",
        "lead_status": "New",
        "assigned_user_id": "admin-roshni",
        "assigned_to": "Admin",
        "context_updates": [],
    }
    user = {"id": "agent-1", "full_name": "Narendran", "email": "narendran@arihants.co.in"}

    mock_db = MagicMock()
    mock_db.calls.find_one = AsyncMock(return_value=None)
    mock_db.calls.insert_one = AsyncMock()
    mock_db.leads.find_one = AsyncMock(return_value={**new_lead, "context_updates": []})
    mock_db.leads.update_one = AsyncMock()
    mock_db.lead_events.insert_one = AsyncMock()
    mock_db.notifications.find_one = AsyncMock(return_value=None)
    mock_db.notifications.insert_one = AsyncMock()

    with (
        patch("crm.services.mcube.process.MCUBE_ENABLED", True),
        patch("crm.services.mcube.process.MCUBE_AUTO_CREATE_LEADS", True),
        patch(
            "crm.services.mcube.process.match_lead_by_customer_phone",
            AsyncMock(return_value=(None, "unmatched", [])),
        ),
        patch(
            "crm.services.mcube.process.create_mcube_unknown_lead",
            AsyncMock(return_value=new_lead),
        ) as create_lead_mock,
        patch("crm.services.mcube.process.match_user_by_agent", AsyncMock(return_value=user)),
        patch("crm.services.mcube.process.apply_mcube_inbound_assignment", AsyncMock(return_value=True)),
        patch("crm.services.mcube.calls.db", mock_db),
        patch("crm.services.mcube.timeline.db", mock_db),
        patch("crm.services.mcube.process.db", mock_db),
        patch("crm.services.lead_events.db", mock_db),
        patch("crm.services.notification_service.db", mock_db),
        patch("crm.services.notification_service.notifications_stream.publish", AsyncMock()),
    ):
        result = await _process_inbound_payload(payload, event_id="evt-auto")

    assert result["auto_created_lead"] is True
    assert result["lead_match_method"] == "mcube_auto_create"
    assert result["timeline_written"] is True
    inserted = mock_db.calls.insert_one.await_args.args[0]
    assert inserted.get("lead_id") == "lead-auto-1"
    push_update = mock_db.leads.update_one.await_args_list[-1].args[1]
    entry = push_update["$push"]["context_updates"]
    assert entry["type"] == "call"
    assert entry.get("recording_url")
    create_lead_mock.assert_awaited_once()
    kwargs = create_lead_mock.await_args.kwargs
    assert kwargs.get("assignee") == user


def test_finalized_call_applies_inbound_assignment_to_answering_agent():
    asyncio.run(_finalized_call_applies_inbound_assignment_to_answering_agent())


async def _finalized_call_applies_inbound_assignment_to_answering_agent():
    payload = _fixture_payload()
    lead = {
        "id": "lead-open",
        "first_name": "Open",
        "last_name": "Lead",
        "lead_status": "New",
        "assigned_user_id": "",
        "context_updates": [],
    }
    answering = {"id": "agent-1", "full_name": "Malathy", "email": "malathy@arihants.co.in"}

    mock_db = MagicMock()
    mock_db.calls.find_one = AsyncMock(return_value=None)
    mock_db.calls.insert_one = AsyncMock()
    mock_db.leads.find_one = AsyncMock(return_value={**lead, "context_updates": []})
    mock_db.leads.update_one = AsyncMock()
    mock_db.lead_events.insert_one = AsyncMock()
    mock_db.notifications.find_one = AsyncMock(return_value=None)
    mock_db.notifications.insert_one = AsyncMock()

    with (
        patch("crm.services.mcube.process.MCUBE_ENABLED", True),
        patch(
            "crm.services.mcube.process.match_lead_by_customer_phone",
            AsyncMock(return_value=(lead, "phone_primary", [lead["id"]])),
        ),
        patch("crm.services.mcube.process.match_user_by_agent", AsyncMock(return_value=answering)),
        patch("crm.services.mcube.process.apply_mcube_inbound_assignment", AsyncMock(return_value=True)) as assign_mock,
        patch("crm.services.mcube.calls.db", mock_db),
        patch("crm.services.mcube.timeline.db", mock_db),
        patch("crm.services.mcube.process.db", mock_db),
        patch("crm.services.lead_events.db", mock_db),
        patch("crm.services.notification_service.db", mock_db),
        patch("crm.services.notification_service.notifications_stream.publish", AsyncMock()),
    ):
        await _process_inbound_payload(payload, event_id="evt-open")

    assign_mock.assert_awaited_once_with("lead-open", answering, call_id=payload["callid"])


def test_connecting_partial_does_not_assign_lead():
    asyncio.run(_connecting_partial_does_not_assign_lead())


async def _connecting_partial_does_not_assign_lead():
    payload = _fixture_payload()
    payload["dialstatus"] = "CONNECTING"
    payload.pop("endtime", None)
    payload.pop("filename", None)
    payload.pop("duration", None)
    lead = {
        "id": "lead-open",
        "first_name": "Open",
        "last_name": "Lead",
        "lead_status": "New",
        "assigned_user_id": "",
        "context_updates": [],
    }
    answering = {"id": "agent-1", "full_name": "Malathy", "email": "malathy@arihants.co.in"}

    mock_db = MagicMock()
    mock_db.calls.find_one = AsyncMock(return_value=None)
    mock_db.calls.insert_one = AsyncMock()
    mock_db.leads.find_one = AsyncMock(return_value={**lead, "context_updates": []})
    mock_db.leads.update_one = AsyncMock()

    with (
        patch("crm.services.mcube.process.MCUBE_ENABLED", True),
        patch(
            "crm.services.mcube.process.match_lead_by_customer_phone",
            AsyncMock(return_value=(lead, "phone_primary", [lead["id"]])),
        ),
        patch("crm.services.mcube.process.match_user_by_agent", AsyncMock(return_value=answering)),
        patch("crm.services.mcube.process.apply_mcube_inbound_assignment", AsyncMock(return_value=True)) as assign_mock,
        patch("crm.services.mcube.calls.db", mock_db),
        patch("crm.services.mcube.process.db", mock_db),
    ):
        result = await _process_inbound_payload(payload, event_id="evt-connecting")

    assert result.get("timeline_written") is False
    assign_mock.assert_not_awaited()
