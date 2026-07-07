"""Lost reason validation for Unqualified / Closed Lost leads."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from crm.constants.lost_reason import normalize_lost_reason
from crm.models.schemas.lead_schemas import LeadUpdatePatch


def test_normalize_lost_reason_case_insensitive():
    assert normalize_lost_reason("budget") == "Budget"
    assert normalize_lost_reason("  Rental ") == "Rental"
    assert normalize_lost_reason("invalid reason") is None


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


def _patch_lead_service(db):
    import crm.services.lead_service as lead_service

    return patch.object(lead_service, "db", db), patch.object(
        lead_service, "assert_assignee_allowed", lambda *_a, **_k: None
    ), patch.object(lead_service, "apply_nurture_temperature_rules", lambda *_a, **_k: None), patch.object(
        lead_service, "determine_lead_intent", lambda *_a, **_k: "Unknown"
    ), patch.object(lead_service, "is_vip_lead", lambda *_a, **_k: False), patch.object(
        lead_service, "normalize_lead_for_response", lambda l: l
    ), patch.object(lead_service, "log_lead_event", lambda *_a, **_k: None), patch.object(
        lead_service, "create_sla_task_for_lead", AsyncMock(return_value=None)
    )


def _base_lead(lead_id="lead-lost", status="Contacted"):
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return {
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


async def _update(lead_id, patch_dict, status="Contacted", existing_extra=None):
    from crm.services.lead_service import update_lead

    lead = _base_lead(lead_id, status)
    if existing_extra:
        lead.update(existing_extra)
    db, leads = _make_db(lead)
    patches = _patch_lead_service(db)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        current_user = {"id": "u1", "full_name": "Tester"}
        result = await update_lead(lead_id, LeadUpdatePatch(**patch_dict), current_user)
        updated = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    return result, updated


def test_unqualified_with_valid_lost_reason():
    async def _run():
        _, updated = await _update(
            "lead-u1",
            {"lead_status": "Unqualified", "lost_reason": "Budget"},
        )
        assert updated["lead_status"] == "Unqualified"
        assert updated["lost_reason"] == "Budget"

    asyncio.run(_run())


def test_closed_lost_missing_lost_reason_raises():
    async def _run():
        with pytest.raises(HTTPException) as exc:
            await _update("lead-cl1", {"lead_status": "Closed Lost"})
        assert exc.value.status_code == 400
        assert "lost_reason" in str(exc.value.detail).lower()

    asyncio.run(_run())


def test_unqualified_invalid_lost_reason_raises():
    async def _run():
        with pytest.raises(HTTPException) as exc:
            await _update(
                "lead-u2",
                {"lead_status": "Unqualified", "lost_reason": "Random free text"},
            )
        assert exc.value.status_code == 400
        assert "invalid lost_reason" in str(exc.value.detail).lower()

    asyncio.run(_run())


def test_junk_accepts_free_text_lost_reason():
    async def _run():
        _, updated = await _update(
            "lead-j1",
            {"lead_status": "Junk", "lost_reason": "Any custom junk note"},
        )
        assert updated["lead_status"] == "Junk"
        assert updated["lost_reason"] == "Any custom junk note"

    asyncio.run(_run())


def test_patch_lost_reason_on_unqualified_invalid_raises():
    async def _run():
        with pytest.raises(HTTPException) as exc:
            await _update(
                "lead-u3",
                {"lost_reason": "not in list"},
                status="Unqualified",
                existing_extra={"lost_reason": "Budget"},
            )
        assert exc.value.status_code == 400

    asyncio.run(_run())


def test_patch_lost_reason_on_unqualified_valid():
    async def _run():
        _, updated = await _update(
            "lead-u4",
            {"lost_reason": "Location"},
            status="Unqualified",
            existing_extra={"lost_reason": "Budget"},
        )
        assert updated["lost_reason"] == "Location"

    asyncio.run(_run())
