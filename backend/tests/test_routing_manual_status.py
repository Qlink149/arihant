"""manual_status blocks auto-assignment when unavailable or away.

batch3 item1: these tests used to call utc_now() and patch
"crm.utils.business_time.is_business_hours_ist" - but assignment_router.py
imports is_business_hours_ist by name at module load time
(`from crm.utils.business_time import is_business_hours_ist`), so patching
the attribute on crm.utils.business_time never touched the reference
assignment_router actually calls. The mock silently did nothing, and the
three tests that expect True passed or failed depending on whether the
real wall-clock time happened to be inside business hours (10:00-17:30 IST,
every day - see business_time.py). Fixed by passing a frozen `now_dt` into
is_active_for_routing instead of mocking the check away, so each test is
deterministic regardless of when it runs.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from crm.services.assignment_router import ROUTING_BLOCKING_STATUSES, is_active_for_routing

IST = ZoneInfo("Asia/Kolkata")

# Monday, business hours (10:00-17:30 IST)
INSIDE_HOURS = datetime(2026, 9, 28, 12, 0, tzinfo=IST)
# Monday, outside business hours
OUTSIDE_HOURS = datetime(2026, 9, 28, 20, 0, tzinfo=IST)
# Sunday, business hours - business_time.py treats every day as a business
# day (Mon-Sun 10:00-17:30), so this must behave identically to a weekday.
SUNDAY_INSIDE_HOURS = datetime(2026, 9, 27, 12, 0, tzinfo=IST)


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
    with patch("crm.services.assignment_router.db", _mock_db("unavailable")), patch(
        "crm.utils.business_time.is_on_duty_today", return_value=True
    ):
        assert not await is_active_for_routing(user, INSIDE_HOURS)


def test_available_allows_routing_when_on_duty():
    asyncio.run(_available_allows_routing_when_on_duty())


async def _available_allows_routing_when_on_duty():
    user = {"id": "u1", "is_active": True}
    with patch("crm.services.assignment_router.db", _mock_db("available")), patch(
        "crm.utils.business_time.is_on_duty_today", return_value=True
    ):
        assert await is_active_for_routing(user, INSIDE_HOURS)


def test_on_break_does_not_block_routing():
    asyncio.run(_on_break_does_not_block_routing())


async def _on_break_does_not_block_routing():
    user = {"id": "u1", "is_active": True}
    with patch("crm.services.assignment_router.db", _mock_db("on_break")), patch(
        "crm.utils.business_time.is_on_duty_today", return_value=True
    ):
        assert await is_active_for_routing(user, INSIDE_HOURS)


def test_site_visit_does_not_block_routing():
    asyncio.run(_site_visit_does_not_block_routing())


async def _site_visit_does_not_block_routing():
    user = {"id": "u1", "is_active": True}
    with patch("crm.services.assignment_router.db", _mock_db("site_visit")), patch(
        "crm.utils.business_time.is_on_duty_today", return_value=True
    ):
        assert await is_active_for_routing(user, INSIDE_HOURS)


def test_away_blocks_routing():
    asyncio.run(_away_blocks_routing())


async def _away_blocks_routing():
    user = {"id": "u1", "is_active": True}
    with patch("crm.services.assignment_router.db", _mock_db("away")), patch(
        "crm.utils.business_time.is_on_duty_today", return_value=True
    ):
        assert not await is_active_for_routing(user, INSIDE_HOURS)


def test_available_blocked_outside_business_hours():
    """The business-hours gate itself, proven with a frozen out-of-hours time."""
    asyncio.run(_available_blocked_outside_business_hours())


async def _available_blocked_outside_business_hours():
    user = {"id": "u1", "is_active": True}
    with patch("crm.services.assignment_router.db", _mock_db("available")), patch(
        "crm.utils.business_time.is_on_duty_today", return_value=True
    ):
        assert not await is_active_for_routing(user, OUTSIDE_HOURS)


def test_available_allows_routing_on_sunday_inside_hours():
    """Sunday is a business day for this SOP (Mon-Sun 10:00-17:30 IST)."""
    asyncio.run(_available_allows_routing_on_sunday_inside_hours())


async def _available_allows_routing_on_sunday_inside_hours():
    user = {"id": "u1", "is_active": True}
    with patch("crm.services.assignment_router.db", _mock_db("available")), patch(
        "crm.utils.business_time.is_on_duty_today", return_value=True
    ):
        assert await is_active_for_routing(user, SUNDAY_INSIDE_HOURS)
