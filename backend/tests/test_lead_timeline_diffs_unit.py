import asyncio
from datetime import datetime, timezone

import pytest

from crm.models.schemas.lead_schemas import LeadUpdatePatch
from crm.services.lead_service import update_lead


def test_lead_update_creates_field_diffs_in_timeline(monkeypatch):
    async def _run():
        class _Leads:
            def __init__(self, doc):
                self.doc = dict(doc)

            async def find_one(self, query, projection=None):
                if query.get("id") != self.doc.get("id"):
                    return None
                return dict(self.doc)

            async def update_one(self, query, update):
                if query.get("id") != self.doc.get("id"):
                    return None
                if "$set" in update:
                    for k, v in update["$set"].items():
                        self.doc[k] = v
                return None

        class _DummyDB:
            pass

        lead_id = "lead-1"
        base = {
            "id": lead_id,
            "first_name": "A",
            "last_name": "B",
            "lead_status": "Contacted",
            "temperature": None,
            "context_updates": [],
            "created_at": datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc).isoformat(),
            "updated_at": datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc).isoformat(),
        }

        db = _DummyDB()
        db.leads = _Leads(base)

        import crm.services.lead_service as lead_service

        monkeypatch.setattr(lead_service, "db", db)
        async def _noop_assert(*_a, **_k):  # noqa: ANN001
            return None

        monkeypatch.setattr(lead_service, "assert_assignee_allowed", _noop_assert)
        monkeypatch.setattr(lead_service, "determine_lead_intent", lambda *_a, **_k: "Unknown")
        monkeypatch.setattr(lead_service, "is_vip_lead", lambda *_a, **_k: False)
        monkeypatch.setattr(lead_service, "normalize_lead_for_response", lambda l: l)
        monkeypatch.setattr(lead_service, "log_lead_event", lambda *_a, **_k: None)
        monkeypatch.setattr(lead_service, "apply_nurture_temperature_rules", lambda existing, patch: patch)

        current_user = {"id": "u1", "full_name": "Tester"}

        # Change to Nurturing with temperature: should show both diffs.
        await update_lead(
            lead_id,
            LeadUpdatePatch(lead_status="Nurturing", temperature="Hot"),
            current_user,
        )

        updated = await db.leads.find_one({"id": lead_id}, {"_id": 0})
        last = (updated.get("context_updates") or [])[-1]
        assert last.get("type") == "updated"
        assert isinstance(last.get("changes"), list) and last["changes"]
        by_field = {c["field"]: c for c in last["changes"]}
        assert by_field["lead_status"]["from"] == "Contacted"
        assert by_field["lead_status"]["to"] == "Nurturing"
        assert by_field["temperature"]["from"] is None
        assert by_field["temperature"]["to"] == "Hot"

        # Generic update shows from->to too.
        await update_lead(
            lead_id,
            LeadUpdatePatch(location="Chennai"),
            current_user,
        )
        updated2 = await db.leads.find_one({"id": lead_id}, {"_id": 0})
        last2 = (updated2.get("context_updates") or [])[-1]
        by_field2 = {c["field"]: c for c in last2["changes"]}
        assert by_field2["location"]["from"] is None
        assert by_field2["location"]["to"] == "Chennai"

    asyncio.run(_run())

