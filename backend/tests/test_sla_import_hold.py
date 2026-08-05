"""SLA hold for historical Freshworks imports until first status change."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from crm.constants.lead_status import sla_paused_exclusion_clause
from crm.models.schemas.lead_schemas import LeadCreate, LeadUpdatePatch
from crm.services.sla_engine import SLAEngineService
from crm.services.sla_helpers import create_sla_task_for_lead


def test_sla_paused_exclusion_clause():
    assert sla_paused_exclusion_clause() == {"$ne": True}


def test_rule_query_excludes_sla_paused():
    engine = SLAEngineService()
    q = engine._rule_query({"lead_status": "Contacted"})
    assert {"sla_paused": {"$ne": True}} in q["$and"]


def test_create_sla_task_skips_when_paused():
    async def _run():
        result = await create_sla_task_for_lead(
            {"id": "l1", "sla_paused": True, "assigned_user_id": "u1"},
            description="test",
            dedupe_key="sla:test:l1",
            sla_rule="sv_followup",
            sla_threshold="t0",
        )
        assert result is None

    asyncio.run(_run())


def test_update_lead_unlocks_sla_on_status_change():
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
                if "$unset" in update:
                    for k in update["$unset"]:
                        parts = k.split(".")
                        cur = self._lead
                        for part in parts[:-1]:
                            cur = cur.setdefault(part, {})
                        if len(parts) == 1:
                            self._lead.pop(parts[0], None)
                        else:
                            cur.pop(parts[-1], None)
                return None

            async def update_many(self, query, update):
                class _Result:
                    modified_count = 0

                return _Result()

        lead_id = "lead-paused"
        old_created = datetime(2024, 1, 1, tzinfo=timezone.utc)
        base_lead = {
            "id": lead_id,
            "first_name": "Old",
            "last_name": "Import",
            "lead_status": "Contacted",
            "sla_paused": True,
            "import_provenance": "freshworks",
            "contacted_at_dt": None,
            "context_updates": [],
            "created_at": old_created.isoformat(),
            "created_at_dt": old_created,
            "updated_at": old_created.isoformat(),
            "updated_at_dt": old_created,
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
            await update_lead(lead_id, LeadUpdatePatch(lead_status="Nurturing"), current_user)
            updated = await db.leads.find_one({"id": lead_id}, {"_id": 0})

        assert updated["sla_paused"] is False
        assert updated.get("sla_activated_at_dt") is not None
        assert updated["lead_status"] == "Nurturing"
        assert updated.get("nurture_entered_at_dt") is not None

    asyncio.run(_run())


def test_create_lead_does_not_set_sla_paused():
    async def _run():
        import crm.services.lead_service as lead_service
        from crm.services.lead_service import create_lead

        inserted = {}

        class _DummyLeads:
            async def find_one(self, query, projection=None):
                return None

            async def insert_one(self, doc):
                inserted.update(doc)

        class _DummyDB:
            leads = _DummyLeads()

        with patch.object(lead_service, "db", _DummyDB()), patch.object(
            lead_service, "assert_assignee_allowed", AsyncMock(return_value=None)
        ), patch.object(lead_service, "apply_nurture_temperature_rules", lambda *_a, **_k: None), patch.object(
            lead_service, "determine_lead_intent", lambda *_a, **_k: "Unknown"
        ), patch.object(lead_service, "is_vip_lead", lambda *_a, **_k: False), patch.object(
            lead_service, "normalize_lead_for_response", lambda l: l
        ), patch.object(lead_service, "log_lead_event", lambda *_a, **_k: None), patch(
            "crm.services.assignment_router.route_new_lead", AsyncMock(return_value=None)
        ):
            await create_lead(
                LeadCreate(first_name="New", last_name="Lead", phone="9999999999"),
                {"id": "u1", "full_name": "Tester"},
            )

        assert "sla_paused" not in inserted or inserted.get("sla_paused") is not True
        assert inserted.get("assigned_to") == "Tester"
        assert inserted.get("assigned_user_id") == "u1"

    asyncio.run(_run())


def test_import_csv_sets_provenance_not_sla_paused():
    async def _run():
        import crm.services.lead_service as lead_service
        from crm.services.lead_service import import_csv

        inserted = {}

        class _Upload:
            async def read(self):
                return (
                    "First name,Last Name,Mobile,Status\n"
                    "Csv,Lead,8888888888,New"
                ).encode("utf-8")

        class _DummyLeads:
            async def find_one(self, query, projection=None):
                return None

            async def insert_one(self, doc):
                inserted.update(doc)

        class _DummyDB:
            leads = _DummyLeads()

        with patch.object(lead_service, "db", _DummyDB()), patch.object(
            lead_service, "assert_assignee_allowed", lambda *_a, **_k: None
        ), patch.object(lead_service, "apply_nurture_temperature_rules", lambda *_a, **_k: None), patch.object(
            lead_service, "determine_lead_intent", lambda *_a, **_k: "Unknown"
        ), patch.object(lead_service, "is_vip_lead", lambda *_a, **_k: False), patch.object(
            lead_service, "resolve_user_id_by_full_name", AsyncMock(return_value=None)
        ), patch.object(lead_service, "resolve_project_id", lambda *_a, **_k: None):
            result = await import_csv(_Upload(), {"id": "u1", "full_name": "Admin"})

        assert result["imported"] == 1
        assert inserted.get("import_provenance") == "csv"
        assert inserted.get("sla_paused") is not True

    asyncio.run(_run())


def test_nurturing_review_query_excludes_sla_paused():
    async def _run():
        from crm.services import nurturing_review as nr

        captured = {}

        class _Cursor:
            def __init__(self, query):
                captured["query"] = query

            async def to_list(self, _limit):
                return []

        def _fake_find(query, projection):
            return _Cursor(query)

        mock_db = MagicMock()
        mock_db.leads.find = _fake_find

        with patch.object(nr, "db", mock_db):
            await nr.process_nurturing_review()

        assert captured["query"]["sla_paused"] == {"$ne": True}

    asyncio.run(_run())
