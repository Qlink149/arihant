"""Site visit count auto-increment when lead enters Visit Completed."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from crm.models.schemas.lead_schemas import LeadUpdatePatch


def test_update_lead_increments_site_visit_count_on_first_visit_completed():
    async def _run():
        import crm.services.lead_service as lead_service
        from crm.services.lead_service import update_lead

        class _DummyCollection:
            def __init__(self, lead_doc):
                self._lead = dict(lead_doc)

            async def find_one(self, query, projection=None):
                if query.get("id") != self._lead.get("id"):
                    return None
                return dict(self._lead)

            async def update_one(self, query, update):
                if query.get("id") != self._lead.get("id"):
                    return None
                if "$set" in update:
                    for k, v in update["$set"].items():
                        self._lead[k] = v
                return None

            async def update_many(self, query, update):
                class _Result:
                    modified_count = 0

                return _Result()

        lead_id = "lead-sv"
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        base_lead = {
            "id": lead_id,
            "first_name": "Test",
            "last_name": "Lead",
            "lead_status": "Site Visit Scheduled",
            "site_visit_count": 0,
            "visit_completed_at_dt": None,
            "context_updates": [],
            "created_at": now.isoformat(),
            "created_at_dt": now,
            "updated_at": now.isoformat(),
            "updated_at_dt": now,
        }

        leads = _DummyCollection(base_lead)

        class _DummyDB:
            pass

        db = _DummyDB()
        db.leads = leads
        db.tasks = leads

        with patch.object(lead_service, "db", db), patch.object(
            lead_service, "assert_assignee_allowed", lambda *_a, **_k: None
        ), patch.object(lead_service, "apply_nurture_temperature_rules", lambda *_a, **_k: None), patch.object(
            lead_service, "determine_lead_intent", lambda *_a, **_k: "Unknown"
        ), patch.object(lead_service, "is_vip_lead", lambda *_a, **_k: False), patch.object(
            lead_service, "normalize_lead_for_response", lambda l: l
        ), patch.object(lead_service, "log_lead_event", lambda *_a, **_k: None), patch.object(
            lead_service, "create_sla_task_for_lead", AsyncMock(return_value=None)
        ):
            current_user = {"id": "u1", "full_name": "Tester"}
            await update_lead(lead_id, LeadUpdatePatch(lead_status="Visit Completed"), current_user)
            updated = await db.leads.find_one({"id": lead_id}, {"_id": 0})

        assert updated["lead_status"] == "Visit Completed"
        assert updated["site_visit_count"] == 1
        assert updated.get("visit_completed_at_dt") is not None

    asyncio.run(_run())


def test_update_lead_does_not_double_increment_site_visit_count():
    async def _run():
        import crm.services.lead_service as lead_service
        from crm.services.lead_service import update_lead

        class _DummyCollection:
            def __init__(self, lead_doc):
                self._lead = dict(lead_doc)

            async def find_one(self, query, projection=None):
                if query.get("id") != self._lead.get("id"):
                    return None
                return dict(self._lead)

            async def update_one(self, query, update):
                if "$set" in update:
                    self._lead.update(update["$set"])
                return None

            async def update_many(self, query, update):
                class _Result:
                    modified_count = 0

                return _Result()

        lead_id = "lead-sv2"
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        base_lead = {
            "id": lead_id,
            "first_name": "Test",
            "last_name": "Lead",
            "lead_status": "Visit Completed",
            "site_visit_count": 2,
            "visit_completed_at_dt": now,
            "context_updates": [],
            "created_at": now.isoformat(),
            "created_at_dt": now,
            "updated_at": now.isoformat(),
            "updated_at_dt": now,
        }

        leads = _DummyCollection(base_lead)
        db = MagicMock()
        db.leads = leads
        db.tasks = leads

        with patch.object(lead_service, "db", db), patch.object(
            lead_service, "assert_assignee_allowed", lambda *_a, **_k: None
        ), patch.object(lead_service, "apply_nurture_temperature_rules", lambda *_a, **_k: None), patch.object(
            lead_service, "determine_lead_intent", lambda *_a, **_k: "Unknown"
        ), patch.object(lead_service, "is_vip_lead", lambda *_a, **_k: False), patch.object(
            lead_service, "normalize_lead_for_response", lambda l: l
        ), patch.object(lead_service, "log_lead_event", lambda *_a, **_k: None), patch.object(
            lead_service, "create_sla_task_for_lead", AsyncMock(return_value=None)
        ):
            current_user = {"id": "u1", "full_name": "Tester"}
            await update_lead(lead_id, LeadUpdatePatch(budget="2-5 Cr"), current_user)
            updated = await db.leads.find_one({"id": lead_id}, {"_id": 0})

        assert updated["site_visit_count"] == 2

    asyncio.run(_run())
