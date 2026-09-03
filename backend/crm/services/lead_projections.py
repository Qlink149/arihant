"""MongoDB field projections and list-view timeline trimming for lead APIs."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from crm.core.state import db
from crm.services.context_updates import dedupe_context_updates
from crm.utils.helpers import coerce_datetime

# My Dashboard lead list (unchanged field set + sort keys)
MY_DASHBOARD_LEAD_PROJECTION: Dict[str, int] = {
    "_id": 0,
    "id": 1,
    "first_name": 1,
    "last_name": 1,
    "project": 1,
    "projects": 1,
    "project_ids": 1,
    "re_enquiry": 1,
    "re_enquired_at": 1,
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
    "work_phone": 1,
    "normalized_phone": 1,
    "normalized_work_phone": 1,
    "lead_status": 1,
    "temperature": 1,
    "vip": 1,
    "project": 1,
    "projects": 1,
    "project_ids": 1,
    "re_enquiry": 1,
    "re_enquired_at": 1,
    "lead_source": 1,
    "original_source": 1,
    "most_recent_source": 1,
    "budget": 1,
    "location": 1,
    "configuration": 1,
    "unit_size": 1,
    "site_visit_count": 1,
    "meta_qualified": 1,
    "next_action_date": 1,
    "assigned_to": 1,
    "assigned_to_name": 1,
    "presales_agent": 1,
    "assigned_user_id": 1,
    "presales_description": 1,
    "recent_note": 1,
    "whatsapp_replied": 1,
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
    "projects": "$projects",
    "re_enquiry": "$re_enquiry",
    "lead_source": "$lead_source",
}

LEAD_LIST_SORT = [
    ("updated_at_dt", -1),
    ("updated_at", -1),
    ("created_at_dt", -1),
]

# Full projection for CSV export (includes notes and CRM metadata)
EXPORT_LEAD_PROJECTION: Dict[str, int] = {
    "_id": 0,
    "id": 1,
    "external_id": 1,
    "first_name": 1,
    "last_name": 1,
    "phone": 1,
    "work_phone": 1,
    "email": 1,
    "lead_status": 1,
    "lost_reason": 1,
    "lead_source": 1,
    "original_source": 1,
    "most_recent_source": 1,
    "assigned_to": 1,
    "assigned_to_name": 1,
    "presales_agent": 1,
    "created_at": 1,
    "updated_at": 1,
    "created_at_dt": 1,
    "updated_at_dt": 1,
    "project": 1,
    "projects": 1,
    "project_ids": 1,
    "re_enquiry": 1,
    "budget": 1,
    "location": 1,
    "configuration": 1,
    "unit_size": 1,
    "site_visit_count": 1,
    "meta_qualified": 1,
    "reason_for_purchase": 1,
    "possession_requirement": 1,
    "intent": 1,
    "temperature": 1,
    "vip": 1,
    "presales_description": 1,
    "campaign_name": 1,
    "next_action_date": 1,
    "context_updates": 1,
}


def list_recent_note_from_lead(lead: dict) -> Optional[str]:
    """Latest timeline note for list views (matches frontend getRecentNote)."""
    trimmed = trim_context_updates_for_list(lead.get("context_updates") or [])
    if trimmed:
        desc = (trimmed[0].get("description") or "").strip()
        if desc:
            return desc
    stored = (lead.get("recent_note") or "").strip()
    if stored:
        return stored
    presales = (lead.get("presales_description") or "").strip()
    return presales or None


def apply_list_recent_note(lead: dict) -> None:
    """Attach recent_note and a single timeline snippet for list API responses."""
    note = list_recent_note_from_lead(lead)
    lead["recent_note"] = note
    trimmed = trim_context_updates_for_list(lead.get("context_updates") or [])
    if trimmed:
        lead["context_updates"] = trimmed
    elif note:
        lead["context_updates"] = [{"description": note}]
    else:
        lead["context_updates"] = []


async def hydrate_list_recent_notes(leads: List[dict]) -> None:
    """Load recent timeline snippets for list rows without full lead documents."""
    if not leads:
        return
    lead_ids = [lead["id"] for lead in leads if lead.get("id")]
    if not lead_ids:
        return
    rows = await db.leads.find(
        {"id": {"$in": lead_ids}},
        {
            "_id": 0,
            "id": 1,
            "context_updates": {"$slice": -40},
            "presales_description": 1,
            "recent_note": 1,
        },
    ).to_list(len(lead_ids))
    by_id = {row["id"]: row for row in rows}
    for lead in leads:
        extra = by_id.get(lead["id"])
        if not extra:
            apply_list_recent_note(lead)
            continue
        merged = {
            **lead,
            "context_updates": extra.get("context_updates") or [],
            "presales_description": lead.get("presales_description") or extra.get("presales_description"),
            "recent_note": extra.get("recent_note") or lead.get("recent_note"),
        }
        apply_list_recent_note(merged)
        lead["recent_note"] = merged.get("recent_note")
        lead["context_updates"] = merged.get("context_updates") or []


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
