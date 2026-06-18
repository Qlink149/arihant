"""Unit tests for follow-up sync helpers."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.lead_follow_up import (
    pending_task_due_lead_ids,
    recompute_lead_next_action_date,
)


def test_pending_task_due_lead_ids_today():
    async def _run():
        mock_cursor = MagicMock()
        mock_cursor.__aiter__ = lambda self: self
        mock_cursor._rows = iter([{"lead_id": "l1"}, {"lead_id": "l2"}, {"lead_id": ""}])

        async def _anext(_self):
            try:
                return next(_self._rows)
            except StopIteration:
                raise StopAsyncIteration

        mock_cursor.__anext__ = _anext
        mock_db = MagicMock()
        mock_db.tasks.find = MagicMock(return_value=mock_cursor)

        with patch("crm.services.lead_follow_up.db", mock_db):
            ids = await pending_task_due_lead_ids("2026-06-17", due_today=True)
        assert ids == ["l1", "l2"]

    asyncio.run(_run())


def test_recompute_lead_next_action_date_sets_earliest_task():
    async def _run():
        mock_db = MagicMock()
        mock_db.tasks.find_one = AsyncMock(return_value={"due_date": "2026-06-20"})
        mock_db.leads.update_one = AsyncMock()

        with patch("crm.services.lead_follow_up.db", mock_db):
            due = await recompute_lead_next_action_date("lead-1")

        assert due == "2026-06-20"
        mock_db.leads.update_one.assert_awaited_once()
        call = mock_db.leads.update_one.await_args
        assert call[0][0] == {"id": "lead-1"}
        assert call[0][1]["$set"]["next_action_date"] == "2026-06-20"

    asyncio.run(_run())


def test_recompute_lead_next_action_date_clears_when_no_tasks():
    async def _run():
        mock_db = MagicMock()
        mock_db.tasks.find_one = AsyncMock(return_value=None)
        mock_db.leads.update_one = AsyncMock()

        with patch("crm.services.lead_follow_up.db", mock_db):
            due = await recompute_lead_next_action_date("lead-2")

        assert due is None
        call = mock_db.leads.update_one.await_args
        assert "$unset" in call[0][1]

    asyncio.run(_run())
