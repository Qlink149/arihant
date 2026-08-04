"""Tests for missed follow-up clearing after activity + clause hygiene."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.lead_follow_up import (
    clear_missed_follow_up_after_activity,
    missed_follow_up_clause,
)


def test_missed_follow_up_clause_excludes_empty_nad():
    clause = missed_follow_up_clause({"today_str": "2026-07-28"}, task_lead_ids=None)
    or_branch = clause["$and"][-1]["$or"][0]
    assert or_branch["next_action_date"]["$nin"] == [None, ""]
    assert or_branch["next_action_date"]["$lt"] == "2026-07-28"


def test_clear_missed_follow_up_completes_overdue_and_recomputes():
    asyncio.run(_clear_missed_follow_up_completes_overdue_and_recomputes())


async def _clear_missed_follow_up_completes_overdue_and_recomputes():
    mock_db = MagicMock()
    mock_db.tasks.update_many = AsyncMock(
        return_value=MagicMock(modified_count=2)
    )
    mock_db.leads.find_one = AsyncMock(
        return_value={"next_action_date": "2026-07-20"}
    )
    mock_db.leads.update_one = AsyncMock()

    with patch("crm.services.lead_follow_up.db", mock_db):
        with patch(
            "crm.services.lead_follow_up.earliest_pending_task_due_date",
            AsyncMock(return_value=None),
        ):
            with patch(
                "crm.services.lead_follow_up.recompute_lead_next_action_date",
                AsyncMock(return_value=None),
            ) as recompute:
                result = await clear_missed_follow_up_after_activity(
                    "lead-1",
                    today_str="2026-07-28",
                    actor_name="Rep",
                )

    assert result["completed_tasks"] == 2
    assert result["cleared_stale_nad"] is True
    recompute.assert_awaited_once_with("lead-1")
    mock_db.tasks.update_many.assert_awaited()
    # Force-clear stale NAD
    assert mock_db.leads.update_one.await_count >= 1
