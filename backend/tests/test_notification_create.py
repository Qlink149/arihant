"""Tests for create_notification SSE publish and dedupe."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.notification_service import create_notification


def test_create_notification_publishes_sse():
    asyncio.run(_create_notification_publishes_sse())


async def _create_notification_publishes_sse():
    publish = AsyncMock()
    mock_db = MagicMock()
    mock_db.notifications.insert_one = AsyncMock()
    mock_db.notifications.find_one = AsyncMock(return_value=None)
    mock_db.leads.find_one = AsyncMock(return_value=None)

    with (
        patch("crm.services.notification_service.db", mock_db),
        patch("crm.services.notification_service.notifications_stream.publish", publish),
    ):
        doc = await create_notification(
            recipient_user_id="user-1",
            recipient_name="Rep One",
            title="Test",
            message="Hello",
            notification_type="reminder",
            lead_id="lead-1",
        )

    assert doc["recipient_user_id"] == "user-1"
    assert doc["title"] == "Test"
    mock_db.notifications.insert_one.assert_awaited_once()
    publish.assert_awaited_once()
    assert publish.await_args[0][0] == "user-1"


def test_create_notification_dedupe_skips_insert_and_publish():
    asyncio.run(_create_notification_dedupe_skips_insert_and_publish())


async def _create_notification_dedupe_skips_insert_and_publish():
    existing = {"id": "existing-1", "dedupe_key": "dup:key"}
    publish = AsyncMock()
    mock_db = MagicMock()
    mock_db.notifications.insert_one = AsyncMock()
    mock_db.notifications.find_one = AsyncMock(return_value=existing)
    mock_db.leads.find_one = AsyncMock(return_value=None)

    with (
        patch("crm.services.notification_service.db", mock_db),
        patch("crm.services.notification_service.notifications_stream.publish", publish),
    ):
        doc = await create_notification(
            recipient_user_id="user-1",
            recipient_name="Rep",
            title="Test",
            message="Hello",
            dedupe_key="dup:key",
        )

    assert doc == existing
    mock_db.notifications.insert_one.assert_not_awaited()
    publish.assert_not_awaited()
