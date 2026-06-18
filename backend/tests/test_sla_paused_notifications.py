"""Notifications must respect sla_paused import hold on leads."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from crm.api.v1.endpoints.notifications import _build_auto_notifications
from crm.api.v1.endpoints.reminders import process_reminders
from crm.models.schemas.lead_schemas import LeadUpdatePatch
from crm.services.notification_service import create_notification


def test_create_notification_skips_reminder_for_sla_paused_lead():
    asyncio.run(_create_notification_skips_reminder_for_sla_paused_lead())


async def _create_notification_skips_reminder_for_sla_paused_lead():
    publish = AsyncMock()
    mock_db = MagicMock()
    mock_db.notifications.insert_one = AsyncMock()
    mock_db.notifications.find_one = AsyncMock(return_value=None)
    mock_db.leads.find_one = AsyncMock(return_value={"sla_paused": True})

    with (
        patch("crm.services.notification_service.db", mock_db),
        patch("crm.services.notification_service.notifications_stream.publish", publish),
    ):
        doc = await create_notification(
            recipient_user_id="user-1",
            recipient_name="Rep",
            title="Follow-up Due",
            message="Stale lead",
            notification_type="reminder",
            lead_id="lead-paused",
        )

    assert doc is None
    mock_db.notifications.insert_one.assert_not_awaited()
    publish.assert_not_awaited()


def test_create_notification_allows_new_lead_assigned_for_sla_paused_lead():
    asyncio.run(_create_notification_allows_new_lead_assigned_for_sla_paused_lead())


async def _create_notification_allows_new_lead_assigned_for_sla_paused_lead():
    publish = AsyncMock()
    mock_db = MagicMock()
    mock_db.notifications.insert_one = AsyncMock()
    mock_db.notifications.find_one = AsyncMock(return_value=None)
    mock_db.leads.find_one = AsyncMock(return_value={"sla_paused": True})

    with (
        patch("crm.services.notification_service.db", mock_db),
        patch("crm.services.notification_service.notifications_stream.publish", publish),
    ):
        doc = await create_notification(
            recipient_user_id="user-1",
            recipient_name="Rep",
            title="New Lead Assigned",
            message="Lead assigned",
            notification_type="new_lead_assigned",
            lead_id="lead-paused",
        )

    assert doc is not None
    assert doc["notification_type"] == "new_lead_assigned"
    mock_db.notifications.insert_one.assert_awaited_once()
    publish.assert_awaited_once()


def test_create_notification_allows_lead_status_changed_for_sla_paused_lead():
    asyncio.run(_create_notification_allows_lead_status_changed_for_sla_paused_lead())


async def _create_notification_allows_lead_status_changed_for_sla_paused_lead():
    publish = AsyncMock()
    mock_db = MagicMock()
    mock_db.notifications.insert_one = AsyncMock()
    mock_db.notifications.find_one = AsyncMock(return_value=None)
    mock_db.leads.find_one = AsyncMock(return_value={"sla_paused": True})

    with (
        patch("crm.services.notification_service.db", mock_db),
        patch("crm.services.notification_service.notifications_stream.publish", publish),
    ):
        doc = await create_notification(
            recipient_user_id="user-1",
            recipient_name="Rep",
            title="Lead activated",
            message="SLA tracking started",
            notification_type="lead_status_changed",
            lead_id="lead-paused",
            dedupe_key="lead_status_changed:lead-paused",
        )

    assert doc is not None
    assert doc["notification_type"] == "lead_status_changed"
    mock_db.notifications.insert_one.assert_awaited_once()


def test_build_auto_notifications_excludes_sla_paused():
    asyncio.run(_build_auto_notifications_excludes_sla_paused())


async def _build_auto_notifications_excludes_sla_paused():
    captured_queries = []
    now = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)

    def fake_find(query, projection):
        captured_queries.append(query)
        m = MagicMock()
        m.to_list = AsyncMock(return_value=[])
        m.limit = MagicMock(return_value=m)
        return m

    with patch("crm.api.v1.endpoints.notifications.db") as mock_db, patch(
        "crm.api.v1.endpoints.notifications.utc_now", return_value=now
    ), patch("crm.api.v1.endpoints.notifications.iso_utc_now", return_value=now.isoformat()):
        mock_db.leads.find = fake_find
        await _build_auto_notifications({"id": "admin", "role": "admin"})

    query_blob = str(captured_queries)
    assert "sla_paused" in query_blob


def test_process_reminders_lead_query_excludes_sla_paused():
    asyncio.run(_process_reminders_lead_query_excludes_sla_paused())


async def _process_reminders_lead_query_excludes_sla_paused():
    captured_queries = []
    now = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)

    def fake_leads_find(query, projection):
        captured_queries.append(query)
        m = MagicMock()
        m.to_list = AsyncMock(return_value=[])
        return m

    mock_db = MagicMock()
    mock_db.reminder_rules.find = MagicMock(
        return_value=MagicMock(
            to_list=AsyncMock(
                return_value=[
                    {
                        "id": "r1",
                        "name": "Follow-up Due",
                        "trigger": "followup_due",
                        "days_threshold": 2,
                        "is_active": True,
                        "send_whatsapp": False,
                        "lead_statuses": ["Follow Up 1"],
                    }
                ]
            )
        )
    )
    mock_db.users.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[])))
    mock_db.leads.find = fake_leads_find
    mock_db.reminders.find_one = AsyncMock(return_value=None)

    with patch("crm.api.v1.endpoints.reminders.db", mock_db), patch(
        "crm.api.v1.endpoints.reminders.utc_now", return_value=now
    ), patch("crm.api.v1.endpoints.reminders.iso_utc_now", return_value=now.isoformat()):
        await process_reminders()

    assert captured_queries
    assert "sla_paused" in str(captured_queries[0])


def test_update_lead_sends_activation_notification_once():
    asyncio.run(_update_lead_sends_activation_notification_once())


async def _update_lead_sends_activation_notification_once():
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
        "assigned_to": "Rep One",
        "assigned_user_id": "u-rep",
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

    create_notif = AsyncMock(return_value={"id": "n1"})

    with patch.object(lead_service, "db", db), patch.object(
        lead_service, "assert_assignee_allowed", lambda *_a, **_k: None
    ), patch.object(lead_service, "apply_nurture_temperature_rules", lambda *_a, **_k: None), patch.object(
        lead_service, "determine_lead_intent", lambda *_a, **_k: "Unknown"
    ), patch.object(lead_service, "is_vip_lead", lambda *_a, **_k: False), patch.object(
        lead_service, "normalize_lead_for_response", lambda l: l
    ), patch.object(lead_service, "log_lead_event", lambda *_a, **_k: None), patch.object(
        lead_service, "create_sla_task_for_lead", AsyncMock(return_value=None)
    ), patch.object(lead_service, "create_notification", create_notif):
        current_user = {"id": "u1", "full_name": "Tester"}
        await update_lead(lead_id, LeadUpdatePatch(lead_status="Nurturing"), current_user)
        updated = await db.leads.find_one({"id": lead_id}, {"_id": 0})

    assert updated["sla_paused"] is False
    create_notif.assert_awaited_once()
    kwargs = create_notif.await_args.kwargs
    assert kwargs["notification_type"] == "lead_status_changed"
    assert kwargs["dedupe_key"] == f"lead_status_changed:{lead_id}"
    assert "Contacted" in kwargs["message"]
    assert "Nurturing" in kwargs["message"]
