"""Escalation Queue whitelist, raise/clear, and list filter helpers (SOP 7).

History lives on the lead as context_updates (type escalation_raise / escalation_clear)
so it shows in the ordinary timeline. Active state is denormalized on lead.escalation
for a one-row-per-lead Virtual Customer filter.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from crm.constants.roles import can_filter_escalated_leads
from crm.core.state import db, iso_utc_now, utc_now
from crm.utils.helpers import coerce_datetime

# Exactly the 13 SOP §7 pairs after Phase 3 T1 (RNR D7 replaces 24h/48h).
ESCALATION_QUEUE_RULES: frozenset[Tuple[str, str]] = frozenset(
    {
        ("new", "pool_exhausted_alert"),
        ("rnr", "escalate_d7"),
        ("rnr", "15d"),
        ("contacted", "72h"),
        ("contacted", "reassign_exhausted"),
        ("nurturing", "hot_escalate_14d"),
        ("interested", "escalate_14d"),
        ("visit_completed", "escalate_72h"),
        ("sv_followup_1", "escalate_72h"),
        ("sv_followup_2", "escalate_72h"),
        ("negotiation", "admin_15d"),
        ("reengaged", "48h"),
        ("future_prospect", "manager_review"),
    }
)

ESCALATION_LABELS: Dict[Tuple[str, str], str] = {
    ("new", "pool_exhausted_alert"): "New lead — pool exhausted",
    ("rnr", "escalate_d7"): "RNR lead unreachable for 6 days across two agents. Reassign or decide next action.",
    ("rnr", "15d"): "RNR lead unchanged for 15+ days — escalate to admin.",
    ("contacted", "72h"): "Contacted lead unactioned 72h",
    ("contacted", "reassign_exhausted"): "Contacted 7-day reassign — no agent available",
    ("nurturing", "hot_escalate_14d"): "Hot nurturing lead — no status change in 14 days",
    ("interested", "escalate_14d"): "Interested lead — no status change in 2 weeks",
    ("visit_completed", "escalate_72h"): "Visit completed — no follow-up logged in 72 hours",
    ("sv_followup_1", "escalate_72h"): "SV Follow-up 1 task pending 72 hours",
    ("sv_followup_2", "escalate_72h"): "SV Follow-up 2 task pending 72 hours",
    ("negotiation", "admin_15d"): "Negotiation overdue — Admin review required (15 days)",
    ("reengaged", "48h"): "Re-engaged — Admin alert (48h)",
    ("future_prospect", "manager_review"): "Admin review — 3 review cycles reached",
}

CLEAR_ACTIONS = frozenset(
    {"status_change", "reassign", "note", "call", "nudge", "terminal", "rnr_attempt"}
)

# Map SOP "call" to stored action; Log Attempt uses rnr_attempt but displays as call.
CLEAR_ACTION_CALL = "call"


def pair_is_queue_rule(sla_rule: str, sla_threshold: str) -> bool:
    return (str(sla_rule or "").strip(), str(sla_threshold or "").strip()) in ESCALATION_QUEUE_RULES


def escalation_label(sla_rule: str, sla_threshold: str) -> str:
    return ESCALATION_LABELS.get(
        (sla_rule, sla_threshold),
        f"{sla_rule}/{sla_threshold}",
    )


def build_raise_state(lead: dict, sla_rule: str, sla_threshold: str, now_dt) -> Tuple[dict, dict]:
    """Return ($set fields, context_updates entry) for a whitelist raise."""
    existing = lead.get("escalation") if isinstance(lead.get("escalation"), dict) else {}
    reasons = list(existing.get("reasons") or [])
    already = any(
        (r.get("sla_rule") == sla_rule and r.get("sla_threshold") == sla_threshold) for r in reasons if isinstance(r, dict)
    )
    if not already:
        reasons.append(
            {
                "sla_rule": sla_rule,
                "sla_threshold": sla_threshold,
                "label": escalation_label(sla_rule, sla_threshold),
                "raised_at_dt": now_dt,
            }
        )
    raised_at = coerce_datetime(existing.get("raised_at_dt")) if existing.get("active") else None
    if not raised_at:
        raised_at = now_dt
    now_iso = iso_utc_now()
    entry = {
        "type": "escalation_raise",
        "timestamp": now_iso,
        "timestamp_dt": now_dt,
        "description": f"Escalation raised: {escalation_label(sla_rule, sla_threshold)}",
        "agent": "SLA Engine",
        "actor_name": "SLA Engine",
        "actor_user_id": "",
        "sla_rule": sla_rule,
        "sla_threshold": sla_threshold,
    }
    set_fields = {
        "escalation.active": True,
        "escalation.reasons": reasons,
        "escalation.raised_at_dt": raised_at,
    }
    return set_fields, entry


def build_clear_state(
    *,
    action: str,
    actor_user_id: str = "",
    actor_name: str = "",
    now_dt=None,
) -> Tuple[dict, dict]:
    now_dt = now_dt or utc_now()
    now_iso = iso_utc_now()
    stored_action = CLEAR_ACTION_CALL if action == "rnr_attempt" else action
    entry = {
        "type": "escalation_clear",
        "timestamp": now_iso,
        "timestamp_dt": now_dt,
        "description": f"Escalation cleared ({stored_action})",
        "agent": actor_name or "User",
        "actor_name": actor_name or "User",
        "actor_user_id": actor_user_id or "",
        "cleared_by_user_id": actor_user_id or "",
        "cleared_by_name": actor_name or "User",
        "action": stored_action,
        "cleared_at_dt": now_dt,
    }
    set_fields = {
        "escalation.active": False,
        "escalation.reasons": [],
        "escalation.raised_at_dt": None,
    }
    return set_fields, entry


async def clear_escalation_if_active(
    lead_id: str,
    *,
    action: str,
    actor_user_id: str = "",
    actor_name: str = "",
    lead: Optional[dict] = None,
) -> bool:
    """Clear an open queue escalation. Returns True if a write happened."""
    if action not in CLEAR_ACTIONS and action != "rnr_attempt":
        return False
    doc = lead or await db.leads.find_one({"id": lead_id}, {"_id": 0, "id": 1, "escalation": 1})
    if not doc:
        return False
    esc = doc.get("escalation") if isinstance(doc.get("escalation"), dict) else {}
    if not esc.get("active"):
        return False
    now_dt = utc_now()
    set_fields, entry = build_clear_state(
        action=action,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        now_dt=now_dt,
    )
    now_iso = iso_utc_now()
    set_fields["updated_at"] = now_iso
    set_fields["updated_at_dt"] = now_dt
    await db.leads.update_one(
        {"id": lead_id, "escalation.active": True},
        {"$set": set_fields, "$push": {"context_updates": entry}},
    )
    return True


def assert_escalated_filter_allowed(current_user: dict) -> None:
    from fastapi import HTTPException
    from crm.constants.roles import can_filter_escalated_leads

    if not can_filter_escalated_leads(current_user.get("role")):
        raise HTTPException(status_code=403, detail="Escalation access required")


def escalated_list_clause() -> Dict[str, Any]:
    return {"escalation.active": True}
