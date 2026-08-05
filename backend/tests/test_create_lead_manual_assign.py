"""Tests for manual assignee handling in create_lead."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from crm.models.schemas.lead_schemas import LeadCreate
from crm.services import lead_service


def test_create_lead_skips_route_when_manual_assignee_set():
    asyncio.run(_create_lead_skips_route_when_manual_assignee_set())


async def _create_lead_skips_route_when_manual_assignee_set():
    lead = LeadCreate(
        first_name="Test",
        last_name="User",
        phone="9999999999",
        lead_status="New",
        assigned_user_id="user-123",
        presales_agent="Jane Rep",
    )
    current_user = {"id": "admin-1", "full_name": "Admin"}

    inserted = {}

    async def fake_insert_one(doc):
        inserted.update(doc)

    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(side_effect=[None, inserted])
    mock_db.leads.insert_one = AsyncMock(side_effect=fake_insert_one)
    mock_db.users.find_one = AsyncMock(
        return_value={"id": "user-123", "full_name": "Jane Rep"}
    )

    with patch.object(lead_service, "db", mock_db):
        with patch.object(lead_service, "normalize_phone", return_value="9999999999"):
            with patch.object(lead_service, "resolve_project_id", return_value=None):
                with patch.object(lead_service, "determine_lead_intent", return_value="Unknown"):
                    with patch.object(lead_service, "is_vip_lead", return_value=False):
                        with patch.object(lead_service, "apply_nurture_temperature_rules"):
                            with patch.object(
                                lead_service, "assert_assignee_allowed", new_callable=AsyncMock
                            ):
                                with patch.object(
                                    lead_service,
                                    "resolve_user_id_by_full_name",
                                    new_callable=AsyncMock,
                                    return_value="user-123",
                                ):
                                    with patch(
                                        "crm.services.assignment_router.route_new_lead",
                                        new_callable=AsyncMock,
                                    ) as mock_route:
                                        await lead_service.create_lead(lead, current_user)

    mock_route.assert_not_called()
    assert inserted.get("assigned_to") == "Jane Rep"
    assert inserted.get("assigned_user_id") == "user-123"
    assert inserted.get("presales_agent") == "Jane Rep"


def test_create_lead_assigns_to_creator_when_no_assignee():
    asyncio.run(_create_lead_assigns_to_creator_when_no_assignee())


async def _create_lead_assigns_to_creator_when_no_assignee():
    lead = LeadCreate(
        first_name="Test",
        last_name="User",
        phone="9999999998",
        lead_status="New",
    )
    current_user = {"id": "rep-anusha", "full_name": "Anusha Omprakash"}

    inserted = {}

    async def fake_insert_one(doc):
        inserted.update(doc)

    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value=None)
    mock_db.leads.insert_one = AsyncMock(side_effect=fake_insert_one)

    with patch.object(lead_service, "db", mock_db):
        with patch.object(lead_service, "normalize_phone", return_value="9999999998"):
            with patch.object(lead_service, "resolve_project_id", return_value=None):
                with patch.object(lead_service, "determine_lead_intent", return_value="Unknown"):
                    with patch.object(lead_service, "is_vip_lead", return_value=False):
                        with patch.object(lead_service, "apply_nurture_temperature_rules"):
                            with patch.object(
                                lead_service, "assert_assignee_allowed", new_callable=AsyncMock
                            ):
                                with patch(
                                    "crm.services.assignment_router.route_new_lead",
                                    new_callable=AsyncMock,
                                ) as mock_route:
                                    await lead_service.create_lead(lead, current_user)

    mock_route.assert_not_called()
    assert inserted.get("assigned_to") == "Anusha Omprakash"
    assert inserted.get("assigned_user_id") == "rep-anusha"
    assert inserted.get("routing_state") == "assigned"
    assigned_ctx = [
        c for c in (inserted.get("context_updates") or []) if c.get("type") == "assigned"
    ]
    assert len(assigned_ctx) == 1
    assert "creator" in assigned_ctx[0].get("description", "").lower()
