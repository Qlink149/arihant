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


def test_cron_lock_requires_matching_owner_token():
    asyncio.run(_cron_lock_requires_matching_owner_token())


async def _cron_lock_requires_matching_owner_token():
    engine = SLAEngineService()
    now = utc_now()
    fake_locks = MagicMock()

    # Wrong owner → reject (another writer won the race)
    fake_locks.find_one_and_update = AsyncMock(
        return_value={
            "job": "process_slas",
            "locked_at": now,
            "owner": "someone-else",
        }
    )
    with patch("crm.services.sla_engine.db") as mock_db:
        mock_db.cron_locks = fake_locks
        ok = await engine._acquire_cron_lock(now)
    assert ok is False

    # Echo back whatever owner we $set → accept
    async def echo_owner(filter, update, **kwargs):
        owner = update["$set"]["owner"]
        return {
            "job": "process_slas",
            "locked_at": now,
            "expires_at": update["$set"]["expires_at"],
            "owner": owner,
        }

    fake_locks.find_one_and_update = AsyncMock(side_effect=echo_owner)
    with patch("crm.services.sla_engine.db") as mock_db:
        mock_db.cron_locks = fake_locks
        ok = await engine._acquire_cron_lock(now)
    assert ok is True


def test_cron_lock_succeeds_when_locked_at_truncated_to_ms():
    """Mongo BSON Date drops microseconds; owner token must still prove ownership."""
    asyncio.run(_cron_lock_succeeds_when_locked_at_truncated_to_ms())


async def _cron_lock_succeeds_when_locked_at_truncated_to_ms():
    engine = SLAEngineService()
    now = utc_now()
    # Ensure we have sub-ms precision that Mongo would drop
    if now.microsecond % 1000 == 0:
        now = now + timedelta(microseconds=123)

    async def echo_truncated(filter, update, **kwargs):
        owner = update["$set"]["owner"]
        locked_at = update["$set"]["locked_at"]
        truncated = locked_at.replace(microsecond=(locked_at.microsecond // 1000) * 1000)
        return {
            "job": "process_slas",
            "locked_at": truncated,
            "expires_at": update["$set"]["expires_at"],
            "owner": owner,
        }

    fake_locks = MagicMock()
    fake_locks.find_one_and_update = AsyncMock(side_effect=echo_truncated)

    with patch("crm.services.sla_engine.db") as mock_db:
        mock_db.cron_locks = fake_locks
        ok = await engine._acquire_cron_lock(now)
    assert ok is True
