"""Follow-up date sync and task-backed dashboard filters."""

from __future__ import annotations

from typing import List, Optional, Set

from crm.core.state import db
from crm.services.lead_search import merge_query

_PENDING_STATUSES = ("pending",)


def _normalize_due_date(value: Optional[str]) -> str:
    if not value:
        return ""
    return str(value).strip()[:10]


async def earliest_pending_task_due_date(lead_id: str) -> Optional[str]:
    """Earliest pending task due_date (YYYY-MM-DD) for a lead, or None."""
    if not lead_id:
        return None
    task = await db.tasks.find_one(
        {"lead_id": lead_id, "status": {"$in": list(_PENDING_STATUSES)}},
        {"_id": 0, "due_date": 1},
        sort=[("due_date", 1), ("due_at_dt", 1)],
    )
    if not task:
        return None
    due = _normalize_due_date(task.get("due_date"))
    return due or None


async def recompute_lead_next_action_date(lead_id: str) -> Optional[str]:
    """Set lead next_action_date from earliest pending task, or clear when none."""
    if not lead_id:
        return None
    due = await earliest_pending_task_due_date(lead_id)
    if due:
        await db.leads.update_one({"id": lead_id}, {"$set": {"next_action_date": due}})
    else:
        await db.leads.update_one({"id": lead_id}, {"$unset": {"next_action_date": ""}})
    return due


async def pending_task_due_lead_ids(
    today_str: str,
    *,
    due_today: bool = False,
    overdue: bool = False,
    scope_lead_ids: Optional[List[str]] = None,
) -> List[str]:
    """Lead ids with pending tasks due today and/or overdue (IST date strings)."""
    if not due_today and not overdue:
        return []
    if scope_lead_ids is not None and len(scope_lead_ids) == 0:
        return []
    clauses: list[dict] = [
        {"status": {"$in": list(_PENDING_STATUSES)}},
        {"lead_id": {"$exists": True, "$nin": [None, ""]}},
    ]
    if scope_lead_ids is not None:
        clauses.append({"lead_id": {"$in": scope_lead_ids}})
    due_clauses: list[dict] = []
    if due_today:
        due_clauses.append({"due_date": today_str})
    if overdue:
        due_clauses.append({"due_date": {"$lt": today_str}})
    if len(due_clauses) == 1:
        clauses.append(due_clauses[0])
    else:
        clauses.append({"$or": due_clauses})
    query = merge_query(*clauses)
    ids: Set[str] = set()
    async for doc in db.tasks.find(query, {"_id": 0, "lead_id": 1}):
        lid = (doc.get("lead_id") or "").strip()
        if lid:
            ids.add(lid)
    return sorted(ids)


def _follow_up_eligible_clause() -> dict:
    """Active pipeline excluding terminal and Gone Cold (inactive bucket)."""
    from crm.constants.lead_status import CLOSED_LEAD_STATUS_REGEX

    return {
        "lead_status": {
            "$not": {
                "$regex": rf"(?:{CLOSED_LEAD_STATUS_REGEX.pattern}|gone\s*cold)",
                "$options": "i",
            },
        }
    }


def follow_up_today_clause(ctx: dict, task_lead_ids: Optional[List[str]] = None) -> dict:
    """Active pipeline leads due today via next_action_date or pending tasks."""
    today_str = ctx["today_str"]
    date_match: list[dict] = [{"next_action_date": today_str}]
    if task_lead_ids:
        date_match.append({"id": {"$in": task_lead_ids}})
    return merge_query(
        _follow_up_eligible_clause(),
        {"$or": date_match},
    )


def missed_follow_up_clause(ctx: dict, task_lead_ids: Optional[List[str]] = None) -> dict:
    """Active pipeline leads with overdue next_action_date or overdue pending tasks."""
    today_str = ctx["today_str"]
    date_match: list[dict] = [
        {
            "next_action_date": {"$exists": True, "$ne": None, "$lt": today_str},
        }
    ]
    if task_lead_ids:
        date_match.append({"id": {"$in": task_lead_ids}})
    return merge_query(
        _follow_up_eligible_clause(),
        {"$or": date_match},
    )


def _active_pipeline_clause() -> dict:
    from crm.constants.lead_status import CLOSED_LEAD_STATUS_REGEX

    return {
        "lead_status": {
            "$not": {"$regex": CLOSED_LEAD_STATUS_REGEX.pattern, "$options": "i"},
        }
    }
