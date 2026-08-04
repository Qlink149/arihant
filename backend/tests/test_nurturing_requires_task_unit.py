from datetime import datetime, timezone

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException

from crm.api.v1.endpoints.tasks import ContextUpdateCreate, TaskCreate
from crm.models.schemas.lead_schemas import LeadUpdatePatch
from crm.services.lead_service import update_lead


def test_nurturing_transition_blocks_general_note_until_new_task(monkeypatch):
    """
    Business rule:
    - Transition into lead_status=Nurturing activates a gate requiring a fresh task.
    - While gate active, general_note context updates are blocked (409).
    - Creating a task satisfies gate, then general_note is allowed.
    """
    async def _run():
        from crm.api.v1.endpoints import tasks as tasks_endpoints

        class _DummyCollection:
            def __init__(self, lead_doc):
                self._lead = dict(lead_doc)
                self._tasks = []

            async def find_one(self, query, projection=None):
                if query.get("id") != self._lead.get("id"):
                    return None
                return dict(self._lead)

            async def update_one(self, query, update):
                # extremely small in-memory update support for our test
                if query.get("id") != self._lead.get("id"):
                    return None
                if "$set" in update:
                    for k, v in update["$set"].items():
                        self._lead[k] = v
                if "$push" in update:
                    for k, v in update["$push"].items():
                        self._lead.setdefault(k, []).append(v)
                return None

            async def insert_one(self, doc):
                self._tasks.append(dict(doc))
                return None

            async def update_many(self, query, update):
                class _Result:
                    modified_count = 0

                return _Result()

        lead_id = "lead-1"
        base_lead = {
            "id": lead_id,
            "first_name": "A",
            "last_name": "B",
            "lead_status": "Contacted",
            "context_updates": [],
            "created_at": datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc).isoformat(),
            "updated_at": datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc).isoformat(),
        }

        leads = _DummyCollection(base_lead)
        tasks = _DummyCollection(base_lead)  # only insert_one used

        class _DummyDB:
            pass

        db = _DummyDB()
        db.leads = leads
        db.tasks = tasks
        db.notifications = _DummyCollection(base_lead)

        # Patch endpoint module globals
        monkeypatch.setattr(tasks_endpoints, "db", db)

        async def _resolve_lead_or_403(lead_id, current_user):
            lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
            if not lead:
                raise HTTPException(status_code=404, detail="Lead not found")
            return lead

        monkeypatch.setattr(tasks_endpoints, "resolve_lead_or_403", _resolve_lead_or_403)

        # Patch lead_service db + dependencies used inside update_lead
        import crm.services.lead_service as lead_service

        monkeypatch.setattr(lead_service, "db", db)
        monkeypatch.setattr(lead_service, "assert_assignee_allowed", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(lead_service, "apply_nurture_temperature_rules", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(lead_service, "determine_lead_intent", lambda *_args, **_kwargs: "Unknown")
        monkeypatch.setattr(lead_service, "is_vip_lead", lambda *_args, **_kwargs: False)
        monkeypatch.setattr(lead_service, "normalize_lead_for_response", lambda l: l)
        monkeypatch.setattr(lead_service, "log_lead_event", lambda *_args, **_kwargs: None)

        current_user = {"id": "u1", "full_name": "Tester"}

        # 1) Transition into Nurturing activates gate
        await update_lead(lead_id, LeadUpdatePatch(lead_status="Nurturing"), current_user)
        updated = await db.leads.find_one({"id": lead_id}, {"_id": 0})
        assert updated["lead_status"] == "Nurturing"
        assert updated.get("nurture_task_required_since_dt") is not None
        assert not updated.get("nurture_task_required_task_id")

        # 2) general_note is blocked (409)
        with pytest.raises(HTTPException) as err:
            await tasks_endpoints.add_context_update(
                lead_id,
                ContextUpdateCreate(note="hello", update_type="general_note"),
                background_tasks=BackgroundTasks(),
                current_user=current_user,
            )
        assert err.value.status_code == 409
        assert "Create a follow-up task first" in (err.value.detail or "")

        # 3) Creating a task satisfies gate (we call endpoint add_task)
        async def _noop_assert(*_args, **_kwargs):  # noqa: ANN001
            return None

        monkeypatch.setattr(tasks_endpoints, "assert_assignee_allowed", _noop_assert)

        async def _resolve_user_id_by_full_name(_name):  # noqa: ANN001
            return "u1"

        monkeypatch.setattr(tasks_endpoints, "resolve_user_id_by_full_name", _resolve_user_id_by_full_name)
        monkeypatch.setattr(tasks_endpoints, "log_lead_event", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            "crm.services.lead_follow_up.recompute_lead_next_action_date",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "crm.services.lead_follow_up.clear_missed_follow_up_after_activity",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "crm.services.lead_follow_up.complete_overdue_pending_tasks",
            AsyncMock(return_value=0),
        )
        monkeypatch.setattr(
            tasks_endpoints,
            "recompute_lead_next_action_date",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            tasks_endpoints,
            "create_notification",
            AsyncMock(return_value=None),
        )

        await tasks_endpoints.add_task(
            lead_id,
            TaskCreate(description="Follow up", due_date="2026-05-02"),
            current_user=current_user,
        )
        updated2 = await db.leads.find_one({"id": lead_id}, {"_id": 0})
        assert updated2.get("nurture_task_required_task_id"), "task should satisfy gate"

    asyncio.run(_run())

