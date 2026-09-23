"""Auto-upgrade Nurturing Warm → Hot on positive signals."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.nurture_temperature import upgrade_nurturing_warm_to_hot_on_lead


def test_upgrade_warm_nurturing_to_hot():
    asyncio.run(_upgrade_warm_nurturing_to_hot())


async def _upgrade_warm_nurturing_to_hot():
    mock_db = MagicMock()
    mock_db.leads.update_one = AsyncMock()
    lead = {"lead_status": "Nurturing", "temperature": "Warm"}
    with patch("crm.services.nurture_temperature.db", mock_db):
        ok = await upgrade_nurturing_warm_to_hot_on_lead("l1", lead, source="test")
    assert ok
    mock_db.leads.update_one.assert_called_once()
    update = mock_db.leads.update_one.call_args[0][1]
    assert update["$set"]["temperature"] == "Hot"


def test_upgrade_skips_already_hot():
    asyncio.run(_upgrade_skips_already_hot())


async def _upgrade_skips_already_hot():
    with patch("crm.services.nurture_temperature.db") as mock_db:
        mock_db.leads.update_one = AsyncMock()
        ok = await upgrade_nurturing_warm_to_hot_on_lead(
            "l1", {"lead_status": "Nurturing", "temperature": "Hot"}, source="test"
        )
    assert not ok
    mock_db.leads.update_one.assert_not_called()


def test_upgrade_skips_non_nurturing():
    asyncio.run(_upgrade_skips_non_nurturing())


async def _upgrade_skips_non_nurturing():
    with patch("crm.services.nurture_temperature.db") as mock_db:
        mock_db.leads.update_one = AsyncMock()
        ok = await upgrade_nurturing_warm_to_hot_on_lead(
            "l1", {"lead_status": "Contacted", "temperature": "Warm"}, source="test"
        )
    assert not ok


def test_upgrade_skips_neutral_warm_on_wrong_status():
    asyncio.run(_upgrade_skips_neutral())


async def _upgrade_skips_neutral():
    with patch("crm.services.nurture_temperature.db") as mock_db:
        mock_db.leads.update_one = AsyncMock()
        ok = await upgrade_nurturing_warm_to_hot_on_lead(
            "l1", {"lead_status": "Interested", "temperature": "Warm"}, source="test"
        )
    assert not ok


def test_interested_status_does_not_force_hot():
    asyncio.run(_interested_status_does_not_force_hot())


async def _interested_status_does_not_force_hot():
    from crm.models.schemas.lead_schemas import LeadUpdatePatch
    from crm.services.lead_service import update_lead

    existing = {
        "id": "l2",
        "lead_status": "Nurturing",
        "temperature": "Warm",
        "first_name": "A",
        "last_name": "B",
        "context_updates": [],
    }
    updated = {**existing, "lead_status": "Interested", "temperature": None}
    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(side_effect=[existing, updated])
    mock_db.leads.update_one = AsyncMock()
    mock_db.tasks = MagicMock()
    mock_db.tasks.update_many = AsyncMock()

    user = {"id": "u1", "full_name": "Rep", "role": "rep"}
    with patch("crm.services.lead_service.db", mock_db), patch(
        "crm.services.lead_service.log_lead_event", AsyncMock()
    ), patch("crm.services.lead_service.create_notification", AsyncMock()), patch(
        "crm.services.lead_service.record_site_visit_event", AsyncMock()
    ), patch("crm.services.nudge_pending.clear_nudge_pending_if_assignee", AsyncMock()):
        await update_lead("l2", LeadUpdatePatch(lead_status="Interested"), user)

    set_doc = mock_db.leads.update_one.call_args[0][1]["$set"]
    ctx = set_doc.get("context_updates") or []
    assert not any(
        "Warm → Hot" in (e.get("description") or "") for e in ctx if isinstance(e, dict)
    )
