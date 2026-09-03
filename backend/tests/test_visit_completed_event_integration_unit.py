"""#53/#54: update_lead writes an append-only site_visit_events entry on every
transition into "Visit Completed", and bumps site_visit_count each time
(unlike the first-stamp-only visit_completed_at_dt reference field)."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from crm.models.schemas.lead_schemas import LeadUpdatePatch


def _make_db(lead_doc):
    class _DummyCollection:
        def __init__(self, doc):
            self._lead = dict(doc)

        async def find_one(self, query, projection=None):
            if query.get("id") != self._lead.get("id"):
                return None
            return dict(self._lead)

        async def update_one(self, query, update):
            if query.get("id") != self._lead.get("id"):
                return None
            if "$set" in update:
                self._lead.update(update["$set"])
            if "$unset" in update:
                for key in update["$unset"]:
                    self._lead.pop(key, None)
            return None

        async def update_many(self, query, update):
            class _Result:
                modified_count = 0

            return _Result()

    leads = _DummyCollection(lead_doc)

    class _DummyDB:
        pass

    db = _DummyDB()
    db.leads = leads
    db.tasks = leads
    return db, leads


def _patch_lead_service(db, record_mock):
    import crm.services.lead_service as lead_service

    return (
        patch.object(lead_service, "db", db),
        patch.object(lead_service, "assert_assignee_allowed", lambda *_a, **_k: None),
        patch.object(lead_service, "apply_nurture_temperature_rules", lambda *_a, **_k: None),
        patch.object(lead_service, "determine_lead_intent", lambda *_a, **_k: "Unknown"),
        patch.object(lead_service, "is_vip_lead", lambda *_a, **_k: False),
        patch.object(lead_service, "normalize_lead_for_response", lambda l: l),
        patch.object(lead_service, "log_lead_event", lambda *_a, **_k: None),
        patch.object(lead_service, "create_sla_task_for_lead", AsyncMock(return_value=None)),
        patch.object(lead_service, "record_site_visit_event", record_mock),
    )


def _base_lead(lead_id="lead-vc", status="Contacted", **extra):
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    lead = {
        "id": lead_id,
        "first_name": "Test",
        "last_name": "Lead",
        "lead_status": status,
        "context_updates": [],
        "created_at": now.isoformat(),
        "created_at_dt": now,
        "updated_at": now.isoformat(),
        "updated_at_dt": now,
    }
    lead.update(extra)
    return lead


async def _update(lead_id, patch_dict, status, record_mock, existing_extra=None):
    from crm.services.lead_service import update_lead

    lead = _base_lead(lead_id, status, **(existing_extra or {}))
    db, leads = _make_db(lead)
    patches = _patch_lead_service(db, record_mock)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
        current_user = {"id": "u1", "full_name": "Tester"}
        await update_lead(lead_id, LeadUpdatePatch(**patch_dict), current_user)
        updated = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    return updated


def test_first_visit_completed_transition_writes_event_and_bumps_count():
    record_mock = AsyncMock(return_value="event-1")

    async def _run():
        updated = await _update(
            "lead-vc1", {"lead_status": "Visit Completed"}, "Contacted", record_mock
        )
        assert updated["lead_status"] == "Visit Completed"
        assert updated["site_visit_count"] == 1
        assert updated.get("visit_completed_at_dt") is not None
        record_mock.assert_awaited_once()

    asyncio.run(_run())


def test_repeat_visit_completed_transition_still_bumps_count_and_logs_event():
    """Lead moves away from Visit Completed and back in — count/log must not be first-stamp-only."""
    record_mock = AsyncMock(return_value="event-2")

    async def _run():
        # existing lead already has visit_completed_at_dt set + count=1 from a prior visit
        existing_extra = {
            "visit_completed_at_dt": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "site_visit_count": 1,
        }
        updated = await _update(
            "lead-vc2",
            {"lead_status": "Visit Completed"},
            "Follow-up Scheduled",
            record_mock,
            existing_extra=existing_extra,
        )
        assert updated["lead_status"] == "Visit Completed"
        # Count increments again even though visit_completed_at_dt already existed.
        assert updated["site_visit_count"] == 2
        record_mock.assert_awaited_once()

    asyncio.run(_run())


def test_non_visit_status_transition_does_not_write_event():
    record_mock = AsyncMock(return_value="event-3")

    async def _run():
        await _update("lead-vc3", {"lead_status": "Nurturing"}, "Contacted", record_mock)
        record_mock.assert_not_awaited()

    asyncio.run(_run())
