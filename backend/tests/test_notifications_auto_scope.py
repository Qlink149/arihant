"""Auto notification scoping and unread-only list behavior."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from crm.api.v1.endpoints.notifications import (
    _build_auto_notifications,
    _filter_redundant_auto_alerts,
    get_notifications,
)


def test_auto_notifications_scope_to_rep_leads():
    asyncio.run(_auto_notifications_scope_to_rep_leads())


async def _auto_notifications_scope_to_rep_leads():
    now = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
    rep_user = {"id": "u1", "full_name": "Malathy", "role": "sales_rep"}

    def fake_find(query, projection):
        m = MagicMock()
        # Rep scope should be present in lead queries.
        assert "$and" in query
        scope_clause = query["$and"][0]
        assert "$or" in scope_clause
        m.to_list = AsyncMock(return_value=[])
        m.limit = MagicMock(return_value=m)
        return m

    with patch("crm.api.v1.endpoints.notifications.db") as mock_db, patch(
        "crm.api.v1.endpoints.notifications.utc_now", return_value=now
    ), patch("crm.api.v1.endpoints.notifications.iso_utc_now", return_value=now.isoformat()):
        mock_db.leads.find = fake_find
        result = await _build_auto_notifications(rep_user)
    assert result == []


def test_rnr_auto_notification_query_uses_broad_status_regex():
    asyncio.run(_rnr_auto_notification_query_uses_broad_status_regex())


async def _rnr_auto_notification_query_uses_broad_status_regex():
    sentinel_clause = {"__rnr_metric_clause__": True}
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
    ), patch("crm.api.v1.endpoints.notifications.iso_utc_now", return_value=now.isoformat()), patch(
        "crm.api.v1.endpoints.notifications.rnr_metric_clause", return_value=sentinel_clause
    ):
        mock_db.leads.find = fake_find
        await _build_auto_notifications({"id": "admin", "role": "admin"})

    query_blob = str(captured_queries)
    assert "is_rnr" in query_blob or "__rnr_metric_clause__" in query_blob
    assert sentinel_clause in captured_queries[0].get("$and", [])


def test_filter_redundant_auto_alerts_drops_task_overdue_and_covered_leads():
    stored = [
        {
            "id": "n1",
            "type": "reminder",
            "notification_type": "reminder",
            "lead_id": "lead-1",
            "task_id": "task-1",
            "title": "Task Overdue",
        },
        {
            "id": "n2",
            "type": "reminder",
            "notification_type": "reminder",
            "lead_id": "lead-2",
            "title": "RNR Stale",
        },
    ]
    auto = [
        {"id": "auto-task-1", "type": "task_overdue", "task_id": "task-1", "lead_id": "lead-1"},
        {"id": "auto-rnr-lead-2", "type": "rnr_followup", "lead_id": "lead-2"},
        {"id": "auto-dormant-lead-3", "type": "dormant_lead", "lead_id": "lead-3"},
    ]
    filtered = _filter_redundant_auto_alerts(stored, auto)
    assert [n["id"] for n in filtered] == ["auto-dormant-lead-3"]


def test_get_notifications_unread_only_excludes_read_stored():
    asyncio.run(_get_notifications_unread_only_excludes_read_stored())


async def _get_notifications_unread_only_excludes_read_stored():
    current_user = {"id": "u1", "full_name": "Malathy", "role": "sales_rep"}
    captured = {}

    def fake_find(query, projection):
        captured["query"] = query
        m = MagicMock()
        m.sort = MagicMock(return_value=m)
        m.to_list = AsyncMock(return_value=[])
        return m

    with patch("crm.api.v1.endpoints.notifications.db") as mock_db, patch(
        "crm.api.v1.endpoints.notifications.utc_now",
        return_value=datetime.now(timezone.utc),
    ), patch(
        "crm.api.v1.endpoints.notifications._build_auto_notifications",
        AsyncMock(return_value=[]),
    ):
        mock_db.notifications.find = fake_find
        mock_db.users.find_one = AsyncMock(return_value={"notification_dismissals": []})
        await get_notifications(current_user=current_user, unread_only=True)

    assert "$and" in captured["query"]
    assert {"is_read": False} in captured["query"]["$and"]
