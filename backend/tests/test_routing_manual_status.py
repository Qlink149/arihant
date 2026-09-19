"""manual_status blocks auto-assignment when unavailable or away."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.assignment_router import ROUTING_BLOCKING_STATUSES, is_active_for_routing
from crm.utils.helpers import utc_now


def _mock_db(manual_status: str):
    mock_db = MagicMock()
    mock_db.user_activity.find_one = AsyncMock(return_value={"manual_status": manual_status})
    return mock_db


def test_blocking_statuses_constant():
    assert ROUTING_BLOCKING_STATUSES == {"unavailable", "away"}


def test_unavailable_blocks_routing():
    asyncio.run(_unavailable_blocks_routing())


async def _unavailable_blocks_routing():
    user = {"id": "u1", "is_active": True}
    now = utc_now()
    with patch("crm.services.assignment_router.db", _mock_db("unavailable")), patch(
        "crm.utils.business_time.is_business_hours_ist", return_value=True
    ), patch("crm.utils.business_time.is_on_duty_today", return_value=True):
        assert not await is_active_for_routing(user, now)


def test_available_allows_routing_when_on_duty():
    asyncio.run(_available_allows_routing_when_on_duty())


async def _available_allows_routing_when_on_duty():
    user = {"id": "u1", "is_active": True}
    now = utc_now()
    with patch("crm.services.assignment_router.db", _mock_db("available")), patch(
        "crm.utils.business_time.is_business_hours_ist", return_value=True
    ), patch("crm.utils.business_time.is_on_duty_today", return_value=True):
        assert await is_active_for_routing(user, now)


def test_on_break_does_not_block_routing():
    asyncio.run(_on_break_does_not_block_routing())


async def _on_break_does_not_block_routing():
    user = {"id": "u1", "is_active": True}
    now = utc_now()
    with patch("crm.services.assignment_router.db", _mock_db("on_break")), patch(
        "crm.utils.business_time.is_business_hours_ist", return_value=True
    ), patch("crm.utils.business_time.is_on_duty_today", return_value=True):
        assert await is_active_for_routing(user, now)


def test_site_visit_does_not_block_routing():
    asyncio.run(_site_visit_does_not_block_routing())


async def _site_visit_does_not_block_routing():
    user = {"id": "u1", "is_active": True}
    now = utc_now()
    with patch("crm.services.assignment_router.db", _mock_db("site_visit")), patch(
        "crm.utils.business_time.is_business_hours_ist", return_value=True
    ), patch("crm.utils.business_time.is_on_duty_today", return_value=True):
        assert await is_active_for_routing(user, now)


def test_away_blocks_routing():
    asyncio.run(_away_blocks_routing())


async def _away_blocks_routing():
    user = {"id": "u1", "is_active": True}
    now = utc_now()
    with patch("crm.services.assignment_router.db", _mock_db("away")), patch(
        "crm.utils.business_time.is_business_hours_ist", return_value=True
    ), patch("crm.utils.business_time.is_on_duty_today", return_value=True):
        assert not await is_active_for_routing(user, now)
