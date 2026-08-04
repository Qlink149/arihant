"""Enrich task documents with lead context for list/detail UIs."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from crm.core.state import db
from crm.services.context_updates import dedupe_context_updates
from crm.services.lead_projections import TASK_ENRICHMENT_LEAD_PROJECTION

LEAD_PROJECTION = TASK_ENRICHMENT_LEAD_PROJECTION

REASON_MAX_LEN = 160

SLA_REASON_BY_KEY: Dict[tuple, str] = {
    ("new", "1h"): "New lead has not been contacted within 1 hour.",
    ("new", "30m"): "New lead has not been contacted within 1 hour.",
    ("new", "2h"): "New lead requires admin attention (2+ hours without contact).",
    ("rnr", "24h"): "RNR lead unchanged for 24+ hours — Admin review required.",
    ("rnr", "48h"): "RNR lead unchanged for 48+ hours — Admin review required.",
    ("rnr", "15d"): "RNR lead unchanged for 15+ days — escalate to admin.",
    ("contacted", "48h"): "Contacted lead has had no update for 48+ hours.",
    ("contacted", "72h"): "Contacted lead has had no update for 72+ hours — admin alert.",
    ("nurturing", "hot_2d"): "Hot nurturing lead with no activity for 2+ days.",
    ("nurturing", "warm_4d"): "Warm nurturing lead with no activity for 4+ days.",
    ("visit_scheduled", "missing_date"): "Site visit scheduled but visit date is missing.",
    ("visit_scheduled", "pre_24h"): "Site visit is within 24 hours — send client reminder.",
    ("visit_scheduled", "post_24h"): "Site visit was 24+ hours ago — post-visit follow-up needed.",
    ("visit_completed", "3d"): "Site visit completed 3+ days ago — follow up today.",
    ("sv_followup_1", "7d"): "SV Follow-up 1 — 7-day follow-up due.",
    ("sv_followup_2", "20d"): "SV Follow-up 2 — 20-day follow-up due; admin notified.",
    ("sv_followup", "72h"): "SV Follow Up — confirm booking intent (72h overdue).",
    ("sv_followup", "7d"): "SV Follow Up — 7-day follow-up cap reached.",
    ("negotiation", "48h"): "Negotiation stage with no update for 48+ hours.",
    ("negotiation", "stalled_7d"): "Negotiation stalled — no activity for 7 days.",
    ("negotiation", "admin_15d"): "Negotiation overdue — Admin review required (15 days).",
    ("gone_cold", "30d"): "Gone cold lead inactive for 30+ days — re-engage or close.",
    ("future_prospect", "90d"): "Future prospect due for 90-day check-in.",
}


def lead_display_name(lead: dict) -> str:
    return f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()


def latest_note_from_lead(lead: dict) -> Optional[str]:
    updates = dedupe_context_updates(lead.get("context_updates") or [])
    for entry in updates:
        desc = (entry.get("description") or "").strip()
        if desc:
            return desc
    presales = (lead.get("presales_description") or "").strip()
    return presales or None


def _truncate(text: str, max_len: int = REASON_MAX_LEN) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def sla_task_reason(task: dict) -> Optional[str]:
    rule = (task.get("sla_rule") or "").strip().lower()
    threshold = (task.get("sla_threshold") or "").strip().lower()
    if not rule:
        return None
    if threshold.startswith("reminder_"):
        return "RNR lead needs a follow-up reminder."
    key = (rule, threshold)
    if key in SLA_REASON_BY_KEY:
        return SLA_REASON_BY_KEY[key]
    desc = (task.get("description") or "").strip()
    if desc:
        return f"Automated SLA task: {desc}."
    return "Automated SLA task."


def compute_task_reason(task: dict, latest_note: Optional[str]) -> Optional[str]:
    if (task.get("source") or "").lower() == "sla":
        reason = sla_task_reason(task)
        if reason:
            return reason
    desc = (task.get("description") or "").strip()
    if desc and task.get("lead_id"):
        # For normal (non-SLA) tasks, showing the lead's latest note can be misleading because
        # it's the same across all tasks on that lead (e.g., "Task: ... Assigned to: X").
        # Prefer the task's own description to keep the list accurate.
        return desc
    if latest_note:
        return _truncate(latest_note)
    return None


def enrich_task_dict(task: dict, lead: Optional[dict]) -> dict:
    out = dict(task)
    if not lead:
        if not out.get("task_reason"):
            out["task_reason"] = compute_task_reason(out, out.get("latest_note"))
        return out

    name = lead_display_name(lead)
    if name:
        out["lead_name"] = name
    project = (lead.get("project") or "").strip()
    if project:
        out["project"] = project

    note = latest_note_from_lead(lead)
    if note:
        out["latest_note"] = _truncate(note, REASON_MAX_LEN)

    out["task_reason"] = compute_task_reason(out, note)
    return out


async def enrich_tasks(tasks: List[dict]) -> List[dict]:
    if not tasks:
        return []

    lead_ids = list({t["lead_id"] for t in tasks if t.get("lead_id")})
    leads_by_id: Dict[str, dict] = {}
    if lead_ids:
        cursor = db.leads.find({"id": {"$in": lead_ids}}, LEAD_PROJECTION)
        async for lead in cursor:
            leads_by_id[lead["id"]] = lead

    return [enrich_task_dict(t, leads_by_id.get(t.get("lead_id") or "")) for t in tasks]
