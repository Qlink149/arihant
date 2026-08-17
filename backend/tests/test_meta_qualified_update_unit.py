"""Lead create/update wiring for Meta Qualified + one CAPI send."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from crm.models.schemas.lead_schemas import LeadCreate, LeadUpdatePatch


def _make_db(lead_doc):
    class _DummyCollection:
        def __init__(self, doc):
            self._lead = dict(doc)

        async def find_one(self, query, projection=None):
            if "normalized_phone" in query:
                return None
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
                    self._lead.pop(key.split(".")[0], None)
            return None

        async def update_many(self, query, update):
            class _Result:
                modified_count = 0

            return _Result()

        async def insert_one(self, doc):
            self._lead = dict(doc)
            return None

    leads = _DummyCollection(lead_doc)

    class _DummyDB:
        pass

    db = _DummyDB()
    db.leads = leads
    db.tasks = leads
    db.users = leads
    return db, leads


def _patch_lead_service(db):
    import crm.services.lead_service as lead_service

    return (
        patch.object(lead_service, "db", db),
        patch.object(lead_service, "assert_assignee_allowed", AsyncMock(return_value=None)),
        patch.object(lead_service, "apply_nurture_temperature_rules", lambda *_a, **_k: None),
        patch.object(lead_service, "determine_lead_intent", lambda *_a, **_k: "Unknown"),
        patch.object(lead_service, "is_vip_lead", lambda *_a, **_k: False),
        patch.object(lead_service, "normalize_lead_for_response", lambda l: l),
        patch.object(lead_service, "log_lead_event", AsyncMock(return_value=None)),
        patch.object(lead_service, "create_sla_task_for_lead", AsyncMock(return_value=None)),
        patch.object(lead_service, "resolve_project_id", return_value=None),
        patch.object(lead_service, "normalize_phone", side_effect=lambda p: p),
        patch.object(lead_service, "schedule_qualified_lead_capi"),
        patch("crm.services.whatsapp_service.send_lead_ack", new_callable=AsyncMock),
    )


def _enter_all(patches):
    return [p.start() for p in patches]


def _stop_all(patches):
    for p in patches:
        p.stop()


def _base_lead(*, lead_id="lead-mq", status="New", source="Facebook Lead Form", meta_qualified=None):
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    return {
        "id": lead_id,
        "first_name": "Test",
        "last_name": "Lead",
        "lead_status": status,
        "lead_source": source,
        "original_source": source,
        "meta_qualified": meta_qualified,
        "context_updates": [],
        "created_at": now.isoformat(),
        "created_at_dt": now,
        "updated_at": now.isoformat(),
        "updated_at_dt": now,
    }


@pytest.mark.asyncio
async def test_update_new_to_contacted_sets_flag_and_sends_capi():
    from crm.services.lead_service import update_lead

    db, leads = _make_db(_base_lead(status="New", source="Facebook Lead Form"))
    patches = _patch_lead_service(db)
    mocks = _enter_all(patches)
    schedule = mocks[-2]
    try:
        result = await update_lead(
            "lead-mq",
            LeadUpdatePatch(lead_status="Contacted"),
            {"id": "u1", "full_name": "Tester"},
        )
    finally:
        _stop_all(patches)

    assert result.meta_qualified is True
    assert leads._lead["meta_qualified"] is True
    schedule.assert_called_once()


@pytest.mark.asyncio
async def test_update_rnr_to_interested_sets_flag_and_sends_capi():
    from crm.services.lead_service import update_lead

    db, leads = _make_db(_base_lead(status="RNR", source="facebook_ad"))
    patches = _patch_lead_service(db)
    mocks = _enter_all(patches)
    schedule = mocks[-2]
    try:
        result = await update_lead(
            "lead-mq",
            LeadUpdatePatch(lead_status="Interested"),
            {"id": "u1", "full_name": "Tester"},
        )
    finally:
        _stop_all(patches)

    assert result.meta_qualified is True
    assert leads._lead["meta_qualified"] is True
    schedule.assert_called_once()


@pytest.mark.asyncio
async def test_update_website_contacted_does_not_set_or_send():
    from crm.services.lead_service import update_lead

    db, leads = _make_db(_base_lead(status="New", source="website"))
    patches = _patch_lead_service(db)
    mocks = _enter_all(patches)
    schedule = mocks[-2]
    try:
        result = await update_lead(
            "lead-mq",
            LeadUpdatePatch(lead_status="Contacted"),
            {"id": "u1", "full_name": "Tester"},
        )
    finally:
        _stop_all(patches)

    assert result.meta_qualified is not True
    assert leads._lead.get("meta_qualified") is not True
    schedule.assert_not_called()


@pytest.mark.asyncio
async def test_manual_yes_on_meta_lead_sends_capi_without_status_change():
    from crm.services.lead_service import update_lead

    db, _leads = _make_db(_base_lead(status="New", source="Facebook Lead Form", meta_qualified=None))
    patches = _patch_lead_service(db)
    mocks = _enter_all(patches)
    schedule = mocks[-2]
    try:
        result = await update_lead(
            "lead-mq",
            LeadUpdatePatch(meta_qualified=True),
            {"id": "u1", "full_name": "Tester"},
        )
    finally:
        _stop_all(patches)

    assert result.meta_qualified is True
    schedule.assert_called_once()


@pytest.mark.asyncio
async def test_manual_yes_on_website_lead_saves_flag_without_capi():
    from crm.services.lead_service import update_lead

    db, leads = _make_db(_base_lead(status="New", source="website"))
    patches = _patch_lead_service(db)
    mocks = _enter_all(patches)
    schedule = mocks[-2]
    try:
        result = await update_lead(
            "lead-mq",
            LeadUpdatePatch(meta_qualified=True),
            {"id": "u1", "full_name": "Tester"},
        )
    finally:
        _stop_all(patches)

    assert result.meta_qualified is True
    assert leads._lead["meta_qualified"] is True
    schedule.assert_not_called()


@pytest.mark.asyncio
async def test_already_yes_does_not_send_again_on_later_status():
    from crm.services.lead_service import update_lead

    db, _leads = _make_db(
        _base_lead(status="Contacted", source="Facebook Lead Form", meta_qualified=True)
    )
    patches = _patch_lead_service(db)
    mocks = _enter_all(patches)
    schedule = mocks[-2]
    try:
        await update_lead(
            "lead-mq",
            LeadUpdatePatch(lead_status="Interested"),
            {"id": "u1", "full_name": "Tester"},
        )
    finally:
        _stop_all(patches)

    schedule.assert_not_called()


@pytest.mark.asyncio
async def test_create_contacted_meta_lead_sets_flag_and_sends():
    from crm.services.lead_service import create_lead

    db, leads = _make_db({"id": "unused"})
    patches = _patch_lead_service(db)
    mocks = _enter_all(patches)
    schedule = mocks[-2]
    try:
        result = await create_lead(
            LeadCreate(
                first_name="Zap",
                last_name="Lead",
                phone="919999900000",
                lead_status="Contacted",
                lead_source="Facebook Lead Form",
            ),
            {"id": "u1", "full_name": "Tester"},
        )
    finally:
        _stop_all(patches)

    assert result.meta_qualified is True
    assert leads._lead.get("meta_qualified") is True
    schedule.assert_called_once()


@pytest.mark.asyncio
async def test_create_new_meta_lead_does_not_send():
    from crm.services.lead_service import create_lead

    db, leads = _make_db({"id": "unused"})
    patches = _patch_lead_service(db)
    mocks = _enter_all(patches)
    schedule = mocks[-2]
    try:
        result = await create_lead(
            LeadCreate(
                first_name="Zap",
                last_name="Lead",
                phone="919999900001",
                lead_status="New",
                lead_source="Facebook Lead Form",
            ),
            {"id": "u1", "full_name": "Tester"},
        )
    finally:
        _stop_all(patches)

    assert result.meta_qualified is not True
    assert leads._lead.get("meta_qualified") is not True
    schedule.assert_not_called()
