"""RNR reminder sibling cancel filter + cron lock acquire behavior."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from pymongo.errors import DuplicateKeyError

from crm.services.sla_engine import SLAEngineService, _rnr_open_reminder_query
from crm.utils.helpers import utc_now


def test_rnr_open_reminder_query_shape():
    q = _rnr_open_reminder_query("lead-xyz")
    assert q["lead_id"] == "lead-xyz"
    assert q["sla_rule"] == "rnr"
    assert q["source"] == "sla"
    assert "$regex" in q["sla_threshold"]
    assert "pending" in q["status"]["$in"]


def test_cron_lock_rejects_duplicate_key():
    asyncio.run(_cron_lock_rejects_duplicate_key())


async def _cron_lock_rejects_duplicate_key():
    engine = SLAEngineService()
    now = utc_now()
    fake_locks = MagicMock()
    fake_locks.find_one_and_update = AsyncMock(side_effect=DuplicateKeyError("dup"))

    with patch("crm.services.sla_engine.db") as mock_db:
        mock_db.cron_locks = fake_locks
        ok = await engine._acquire_cron_lock(now)
    assert ok is False


def test_cron_lock_requires_exact_locked_at():
    asyncio.run(_cron_lock_requires_exact_locked_at())


async def _cron_lock_requires_exact_locked_at():
    engine = SLAEngineService()
    now = utc_now()
    other = now - timedelta(seconds=1)
    fake_locks = MagicMock()
    fake_locks.find_one_and_update = AsyncMock(
        return_value={"job": "process_slas", "locked_at": other}
    )

    with patch("crm.services.sla_engine.db") as mock_db:
        mock_db.cron_locks = fake_locks
        ok = await engine._acquire_cron_lock(now)
    assert ok is False

    fake_locks.find_one_and_update = AsyncMock(
        return_value={"job": "process_slas", "locked_at": now}
    )
    with patch("crm.services.sla_engine.db") as mock_db:
        mock_db.cron_locks = fake_locks
        ok = await engine._acquire_cron_lock(now)
    assert ok is True
