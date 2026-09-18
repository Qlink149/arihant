"""MCUBE SLA-safe lead assignment helper."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.mcube.assign import apply_mcube_inbound_assignment
from crm.services.mcube_lead_intake import create_mcube_unknown_lead

MALATHY = {"id": "agent-malathy", "full_name": "Malathy", "email": "malathy@arihants.co.in"}
NARENDRAN = {"id": "agent-narendran", "full_name": "Narendran S", "email": "narendran@arihants.co.in"}
PRIYA = {"id": "owner-priya", "full_name": "Priya", "email": "priya@arihants.co.in"}


def test_assigns_unowned_lead_to_answering_agent():
    asyncio.run(_assigns_unowned_lead_to_answering_agent())


async def _assigns_unowned_lead_to_answering_agent():
    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(
        return_value={
            "id": "lead-1",
            "assigned_user_id": "",
            "first_name": "Open",
            "last_name": "Lead",
        }
    )
    mock_db.leads.update_one = AsyncMock()

    with (
        patch("crm.services.mcube.assign.db", mock_db),
        patch("crm.services.mcube.assign.create_notification", AsyncMock()),
    ):
        applied = await apply_mcube_inbound_assignment("lead-1", MALATHY, call_id="call-1")

    assert applied is True
    update = mock_db.leads.update_one.await_args.args[1]
    assert "updated_at" not in update.get("$set", {})
    assert update["$set"]["assigned_user_id"] == "agent-malathy"
    assert update["$push"]["context_updates"]["type"] == "assigned"


def test_reassigns_to_talker_and_notifies_previous_owner():
    asyncio.run(_reassigns_to_talker_and_notifies_previous_owner())


async def _reassigns_to_talker_and_notifies_previous_owner():
    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(
        return_value={
            "id": "lead-1",
            "assigned_user_id": PRIYA["id"],
            "assigned_to": "Priya",
            "first_name": "Cust",
            "last_name": "One",
        }
    )
    mock_db.leads.update_one = AsyncMock()
    notify = AsyncMock()

    with (
        patch("crm.services.mcube.assign.db", mock_db),
        patch("crm.services.mcube.assign.create_notification", notify),
    ):
        applied = await apply_mcube_inbound_assignment("lead-1", NARENDRAN, call_id="call-2")

    assert applied is True
    update = mock_db.leads.update_one.await_args.args[1]
    assert update["$push"]["context_updates"]["type"] == "transfer"
    assert update["$set"]["assigned_user_id"] == "agent-narendran"
    notify.assert_awaited_once()
    assert notify.await_args.kwargs["recipient_user_id"] == PRIYA["id"]
    assert "reassigned to Narendran S" in notify.await_args.kwargs["message"]


def test_skips_when_lead_already_owned_by_talker():
    asyncio.run(_skips_when_lead_already_owned_by_talker())


async def _skips_when_lead_already_owned_by_talker():
    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(
        return_value={
            "id": "lead-1",
            "assigned_user_id": NARENDRAN["id"],
            "assigned_to": "Narendran S",
            "first_name": "Cust",
            "last_name": "One",
        }
    )
    mock_db.leads.update_one = AsyncMock()

    with patch("crm.services.mcube.assign.db", mock_db):
        applied = await apply_mcube_inbound_assignment("lead-1", NARENDRAN, call_id="call-3")

    assert applied is False
    mock_db.leads.update_one.assert_not_awaited()


def test_create_unknown_lead_uses_answering_agent():
    asyncio.run(_create_unknown_lead_uses_answering_agent())


async def _create_unknown_lead_uses_answering_agent():
    admin = {"id": "admin-1", "full_name": "Roshni", "email": "roshni@arihantspaces.com"}

    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value=None)
    mock_db.leads.insert_one = AsyncMock()

    with (
        patch("crm.services.mcube_lead_intake.db", mock_db),
        patch("crm.services.mcube_lead_intake.resolve_admin_wa_assignee", AsyncMock(return_value=admin)),
        patch("crm.services.mcube_lead_intake.create_notification", AsyncMock()),
        patch("crm.services.mcube_lead_intake.apply_nurture_temperature_rules"),
        patch("crm.services.mcube_lead_intake.determine_lead_intent", return_value="medium"),
        patch("crm.services.mcube_lead_intake.is_vip_lead", return_value=False),
    ):
        lead = await create_mcube_unknown_lead(
            "9916043625",
            call_id="c1",
            assignee=NARENDRAN,
            notify=False,
        )

    assert lead["assigned_user_id"] == "agent-narendran"
