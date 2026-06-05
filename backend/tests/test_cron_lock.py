"""Distributed cron lock for process_all_slas."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from crm.services.sla_engine import SLAEngineService, _CRON_LOCK_JOB
from crm.utils.helpers import utc_now


def test_second_run_skipped_when_lock_held():
    asyncio.run(_lock_held_skips())


async def _lock_held_skips():
    now = utc_now()
    engine = SLAEngineService()

    with patch("crm.services.sla_engine.db") as mock_db:
        mock_db.cron_locks.find_one_and_update = AsyncMock(
            return_value={"job": _CRON_LOCK_JOB, "locked_at": now - timedelta(minutes=1)}
        )
        result = await engine.process_all_slas()

    assert result.get("skipped") is True
    assert result.get("reason") == "lock_held"


def test_lock_released_on_exception():
    asyncio.run(_lock_released_in_finally())


async def _lock_released_in_finally():
    engine = SLAEngineService()

    with patch.object(engine, "_acquire_cron_lock", AsyncMock(return_value=True)):
        with patch.object(engine, "_load_name_to_user_id", AsyncMock(side_effect=RuntimeError("boom"))):
            with patch("crm.services.sla_engine.db") as mock_db:
                mock_db.cron_locks.delete_one = AsyncMock()
                try:
                    await engine.process_all_slas()
                except RuntimeError:
                    pass
                mock_db.cron_locks.delete_one.assert_awaited_once_with({"job": _CRON_LOCK_JOB})
