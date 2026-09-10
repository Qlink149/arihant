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
