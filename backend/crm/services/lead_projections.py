"""MongoDB field projections and list-view timeline trimming for lead APIs."""
from __future__ import annotations

from typing import Any, Dict, List

from crm.services.context_updates import dedupe_context_updates
from crm.utils.helpers import coerce_datetime

# My Dashboard lead list (unchanged field set + sort keys)
MY_DASHBOARD_LEAD_PROJECTION: Dict[str, int] = {
    "_id": 0,
    "id": 1,
    "first_name": 1,
    "last_name": 1,
    "project": 1,
    "phone": 1,
    "temperature": 1,
    "lead_status": 1,
    "vip": 1,
    "assigned_to": 1,
    "assigned_to_name": 1,
    "next_action_date": 1,
    "updated_at": 1,
    "updated_at_dt": 1,
    "created_at_dt": 1,
}

# Task enrichment (reason text from timeline / presales)
TASK_ENRICHMENT_LEAD_PROJECTION: Dict[str, int] = {
    "_id": 0,
    "id": 1,
    "first_name": 1,
    "last_name": 1,
    "project": 1,
    "context_updates": 1,
    "presales_description": 1,
}

# Virtual Customer / GET /leads list
LIST_LEAD_PROJECTION: Dict[str, int] = {
    "_id": 0,
    "id": 1,
    "first_name": 1,
    "last_name": 1,
    "phone": 1,
    "normalized_phone": 1,
    "lead_status": 1,
    "temperature": 1,
    "vip": 1,
    "project": 1,
    "lead_source": 1,
    "next_action_date": 1,
    "assigned_to": 1,
    "assigned_to_name": 1,
    "presales_agent": 1,
    "assigned_user_id": 1,
    "presales_description": 1,
    "context_updates": 1,
    "created_at": 1,
    "updated_at": 1,
    "created_at_dt": 1,
    "updated_at_dt": 1,
}

DUPLICATE_GROUP_PUSH: Dict[str, str] = {
    "id": "$id",
    "first_name": "$first_name",
    "last_name": "$last_name",
    "phone": "$phone",
    "normalized_phone": "$normalized_phone",
    "project": "$project",
    "lead_source": "$lead_source",
}

LEAD_LIST_SORT = [
    ("updated_at_dt", -1),
    ("updated_at", -1),
    ("created_at_dt", -1),
]


def trim_context_updates_for_list(updates: List[dict]) -> List[dict]:
    """Newest note-bearing timeline entry only (matches frontend getRecentNote)."""
    deduped = dedupe_context_updates(updates or [])
    for entry in deduped:
        if (entry.get("description") or "").strip():
            item = dict(entry)
            ts_dt = coerce_datetime(item.get("timestamp_dt")) or coerce_datetime(item.get("timestamp"))
            if ts_dt is not None:
                item["timestamp_dt"] = ts_dt
                item["timestamp"] = ts_dt.isoformat().replace("+00:00", "Z")
            return [item]
    return []
