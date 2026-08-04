import csv
import io
import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import asyncio

from fastapi import HTTPException, UploadFile

from crm.constants.lead_kpi import fw_status_indicates_rnr
from crm.constants.lead_status import (
    is_interested_status,
    is_sv_followup_1_status,
    is_sv_followup_2_status,
    is_sv_followup_status,
    is_terminal_lead_status,
)
from crm.constants.lost_reason import (
    is_free_text_lost_status,
    is_lost_reason_status,
    normalize_lost_reason,
)
from crm.core.platform_ops import assert_assignee_allowed
from crm.core.state import db, logger, resolve_project_id, resolve_user_id_by_full_name
from crm.models.schemas.lead_schemas import LeadCreate, LeadResponse, LeadUpdatePatch
from crm.services.context_updates import dedupe_context_updates
from crm.services.lead_projections import (
    DUPLICATE_GROUP_PUSH,
    LEAD_LIST_SORT,
    LIST_LEAD_PROJECTION,
    apply_list_recent_note,
    hydrate_list_recent_notes,
    trim_context_updates_for_list,
)
from crm.services.lead_events import log_lead_event
from crm.services.notification_service import create_notification
from crm.services.lead_list_query import compose_leads_list_query
from crm.services.nurture_temperature import apply_nurture_temperature_rules
from crm.services.sla_helpers import create_sla_task_for_lead
from crm.utils.helpers import (
    coerce_datetime,
    determine_lead_intent,
    is_vip_lead,
    iso_utc_now,
    normalize_phone,
    parse_csv_date,
    utc_now,
)

_IST = ZoneInfo("Asia/Kolkata")


def _ist_follow_up_date(days_ahead: int, from_dt: Optional[datetime] = None) -> str:
    """Return YYYY-MM-DD for next_action_date (IST calendar)."""
    base = (from_dt or utc_now()).astimezone(_IST).date()
    return (base + timedelta(days=days_ahead)).isoformat()


def _normalize_context_updates_for_response(updates: List[dict]) -> List[dict]:
    normalized: List[dict] = []
    for entry in updates:
        item = dict(entry)
        ts_dt = coerce_datetime(item.get("timestamp_dt")) or coerce_datetime(item.get("timestamp"))
        if ts_dt is not None:
            item["timestamp_dt"] = ts_dt
            item["timestamp"] = ts_dt.isoformat().replace("+00:00", "Z")
        normalized.append(item)
    return normalized


def normalize_lead_for_response(lead: dict, *, list_view: bool = False) -> dict:
    if lead.get("strategic_next_moves") is None:
        lead["strategic_next_moves"] = []
    if list_view:
        apply_list_recent_note(lead)
    else:
        lead["context_updates"] = _normalize_context_updates_for_response(
            dedupe_context_updates(lead.get("context_updates") or [])
        )
    dt = lead.get("ai_last_generated_at_dt")
    if isinstance(dt, datetime):
        lead["ai_last_generated_at"] = dt
    elif lead.get("ai_last_generated_at"):
        lead["ai_last_generated_at"] = coerce_datetime(lead.get("ai_last_generated_at")) or lead.get(
            "ai_last_generated_at"
        )
    else:
        lead["ai_last_generated_at"] = None
    return lead


def _apply_contact_phones(lead_dict: Dict[str, Any]) -> None:
    """Normalize phone and work_phone in-place."""
    if "phone" in lead_dict:
        phone = lead_dict.get("phone")
        lead_dict["normalized_phone"] = normalize_phone(phone) if phone else None
    if "work_phone" in lead_dict:
        work = lead_dict.get("work_phone")
        lead_dict["normalized_work_phone"] = normalize_phone(work) if work else None


def _validate_site_visit_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="site_visit_count must be a non-negative integer")
    if count < 0:
        raise HTTPException(status_code=400, detail="site_visit_count must be a non-negative integer")
    return count


async def create_lead(lead: LeadCreate, current_user: dict) -> LeadResponse:
    lead_id = str(uuid.uuid4())
    normalized_phone = normalize_phone(lead.phone) if lead.phone else None

    if normalized_phone:
        existing = await db.leads.find_one({"normalized_phone": normalized_phone}, {"_id": 0})
        if existing:
            raise HTTPException(status_code=400, detail=f"Duplicate lead found with same phone number (ID: {existing['id']})")

    lead_dict = lead.model_dump()
    if lead_dict.get("site_visit_count") is None:
        lead_dict["site_visit_count"] = 0
    else:
        lead_dict["site_visit_count"] = _validate_site_visit_count(lead_dict["site_visit_count"])
    _apply_contact_phones(lead_dict)
    if not lead_dict.get("project_id"):
        lead_dict["project_id"] = resolve_project_id(lead_dict.get("project"))

    temp_patch = {"lead_status": lead_dict.get("lead_status", "New")}
    if lead_dict.get("temperature") is not None:
        temp_patch["temperature"] = lead_dict.get("temperature")
    apply_nurture_temperature_rules({}, temp_patch, is_create=True)
    lead_dict["temperature"] = temp_patch.get("temperature")

    manual_assignee_name: Optional[str] = None
    manual_assignee_id: Optional[str] = None
    presales_raw = (lead_dict.get("presales_agent") or "").strip()
    assigned_uid_raw = (lead_dict.get("assigned_user_id") or "").strip()
    if assigned_uid_raw or presales_raw:
        if assigned_uid_raw:
            user_doc = await db.users.find_one(
                {"id": assigned_uid_raw},
                {"_id": 0, "id": 1, "full_name": 1},
            )
            manual_assignee_name = (user_doc.get("full_name") if user_doc else None) or presales_raw
            manual_assignee_id = assigned_uid_raw if user_doc else await resolve_user_id_by_full_name(manual_assignee_name)
        else:
            manual_assignee_name = presales_raw
            manual_assignee_id = await resolve_user_id_by_full_name(manual_assignee_name)
        await assert_assignee_allowed(manual_assignee_name)

    now_dt = utc_now()
    now_iso = iso_utc_now()
    lead_dict.update(
        {
            "id": lead_id,
            "normalized_phone": normalized_phone,
            "intent": determine_lead_intent(lead_dict),
            "vip": is_vip_lead(lead_dict),
            "assigned_to": manual_assignee_name,
            "assigned_user_id": manual_assignee_id,
            "assigned_to_name": manual_assignee_name,
            "presales_agent": manual_assignee_name or lead_dict.get("presales_agent"),
            "ai_persona_summary": None,
            "strategic_next_moves": [],
            "ai_grounded_profile": None,
            "ai_last_generated_at": None,
            "ai_last_generated_at_dt": None,
            "context_updates": [
                {
                    "type": "created",
                    "timestamp": now_iso,
                    "timestamp_dt": now_dt,
                    "description": "Lead created",
                    "agent": current_user["full_name"],
                    "actor_user_id": current_user.get("id"),
                    "actor_name": current_user.get("full_name"),
                }
            ],
            "created_at": now_iso,
            "created_at_dt": now_dt,
            "updated_at": now_iso,
            "updated_at_dt": now_dt,
        }
    )

    await db.leads.insert_one(lead_dict)

    status_val = (lead_dict.get("lead_status") or "New").strip().lower()
    if status_val == "new" and not manual_assignee_name:
        from crm.services.assignment_router import route_new_lead

        await route_new_lead(lead_id)
        refreshed = await db.leads.find_one({"id": lead_id}, {"_id": 0})
        if refreshed:
            lead_dict.update(refreshed)

    lead_dict["created_at"] = coerce_datetime(lead_dict["created_at"]) or utc_now()
    lead_dict["updated_at"] = coerce_datetime(lead_dict["updated_at"]) or utc_now()
    normalize_lead_for_response(lead_dict)
    
    # Template 1: Auto-ack WhatsApp (fire and forget)
    from crm.services.whatsapp_service import send_lead_ack
    asyncio.create_task(send_lead_ack(lead_id, lead_dict))
    
    return LeadResponse(**lead_dict)


async def list_leads(
    project: Optional[str] = None,
    projects: Optional[list] = None,
    project_id: Optional[str] = None,
    temperature: Optional[str] = None,
    budget: Optional[str] = None,
    budgets: Optional[list] = None,
    location: Optional[str] = None,
    locations: Optional[list] = None,
    intent: Optional[str] = None,
    vip: Optional[bool] = None,
    status: Optional[str] = None,
    statuses: Optional[list] = None,
    search: Optional[str] = None,
    days: Optional[int] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
    sources: Optional[list] = None,
    source: Optional[str] = None,
    sales_owners: Optional[list] = None,
    sales_owner: Optional[str] = None,
    meta_qualified: Optional[bool] = None,
    site_visit_min: Optional[int] = None,
    site_visit_max: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    query_base: Optional[Dict[str, Any]] = None,
    include_total: bool = True,
) -> tuple[List[LeadResponse], int]:
    query = compose_leads_list_query(
        query_base,
        temperature=temperature,
        search=search,
        project=project,
        projects=projects,
        project_id=project_id,
        budget=budget,
        budgets=budgets,
        location=location,
        locations=locations,
        intent=intent,
        vip=vip,
        status=status,
        statuses=statuses,
        days=days,
        created_from=created_from,
        created_to=created_to,
        updated_from=updated_from,
        updated_to=updated_to,
        sources=sources,
        source=source,
        sales_owners=sales_owners,
        sales_owner=sales_owner,
        meta_qualified=meta_qualified,
        site_visit_min=site_visit_min,
        site_visit_max=site_visit_max,
    )

    total = await db.leads.count_documents(query) if include_total else 0
    cursor = (
        db.leads.find(query, LIST_LEAD_PROJECTION)
        .sort(LEAD_LIST_SORT)
        .skip(skip)
        .limit(limit)
    )
    leads = await cursor.to_list(limit)

    await hydrate_list_recent_notes(leads)

    for lead in leads:
        lead["created_at"] = coerce_datetime(lead.get("created_at")) or utc_now()
        lead["updated_at"] = coerce_datetime(lead.get("updated_at")) or utc_now()
        normalize_lead_for_response(lead, list_view=True)

    return [LeadResponse(**lead) for lead in leads], total


def duplicate_groups_base_pipeline(match_query: dict) -> List[dict]:
    """Stages grouping leads by normalized_phone with count > 1."""
    return [
        {
            "$match": {
                **match_query,
                "normalized_phone": {"$exists": True, "$nin": [None, ""]},
            }
        },
        {
            "$group": {
                "_id": "$normalized_phone",
                "count": {"$sum": 1},
                "leads": {"$push": DUPLICATE_GROUP_PUSH},
            }
        },
        {"$match": {"count": {"$gt": 1}}},
    ]


async def find_duplicate_lead_groups(
    query_base: Optional[Dict[str, Any]] = None,
    *,
    skip: int = 0,
    limit: int = 50,
) -> tuple[List[List[dict]], int]:
    """Return duplicate phone groups and total group count."""
    limit = min(max(limit, 1), 100)
    match_query = query_base or {}
    base_pipeline = duplicate_groups_base_pipeline(match_query)
    count_pipeline = base_pipeline + [{"$count": "n"}]
    count_rows = await db.leads.aggregate(count_pipeline).to_list(1)
    total_groups = count_rows[0]["n"] if count_rows else 0

    data_pipeline = base_pipeline + [
        {"$sort": {"count": -1}},
        {"$skip": skip},
        {"$limit": limit},
        {
            "$project": {
                "_id": 0,
                "leads": {"$slice": ["$leads", 20]},
            }
        },
    ]
    rows = await db.leads.aggregate(data_pipeline).to_list(limit)
    groups = [row.get("leads") or [] for row in rows]
    return groups, total_groups


async def get_lead_by_id(lead_id: str) -> dict:
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if isinstance(lead.get("created_at"), str):
        lead["created_at"] = coerce_datetime(lead.get("created_at")) or utc_now()
    if isinstance(lead.get("updated_at"), str):
        lead["updated_at"] = coerce_datetime(lead.get("updated_at")) or utc_now()

    return normalize_lead_for_response(lead)


async def update_lead(lead_id: str, lead_update: LeadUpdatePatch, current_user: dict) -> LeadResponse:
    existing = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Lead not found")

    patch = lead_update.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "phone" in patch or "work_phone" in patch:
        merged_phones = {
            "phone": patch.get("phone", existing.get("phone")),
            "work_phone": patch.get("work_phone", existing.get("work_phone")),
        }
        _apply_contact_phones(merged_phones)
        if "phone" in patch:
            patch["normalized_phone"] = merged_phones["normalized_phone"]
        if "work_phone" in patch:
            patch["normalized_work_phone"] = merged_phones["normalized_work_phone"]

    if "site_visit_count" in patch:
        patch["site_visit_count"] = _validate_site_visit_count(patch["site_visit_count"])

    if "project" in patch and patch.get("project"):
        patch["project_id"] = resolve_project_id(patch.get("project"))

    if "assigned_to" in patch and "assigned_to_name" not in patch:
        patch["assigned_to_name"] = patch["assigned_to"]

    assignee_changed = False
    for field in ("assigned_to", "assigned_to_name", "presales_agent"):
        if field in patch:
            await assert_assignee_allowed(patch.get(field))
            if existing.get(field) != patch.get(field):
                assignee_changed = True

    now_dt = utc_now()
    now_iso = iso_utc_now()

    prev_status = (existing.get("lead_status") or "").strip()
    next_status = (patch.get("lead_status") or prev_status).strip()
    status_changed = ("lead_status" in patch) and (prev_status.lower() != next_status.lower())
    is_sla_activation = False

    # Contacted outcome logging (client confirmed): structured enum, not free text.
    if "logged_outcome" in patch or "logged_outcome_reason" in patch:
        effective_status = next_status or prev_status
        if effective_status.strip().lower() != "contacted":
            raise HTTPException(status_code=400, detail="logged_outcome is only allowed when lead_status is Contacted")
        allowed = {
            "Interested",
            "Not Interested",
            "Follow-up Scheduled",
            "Others",
        }
        outcome = (patch.get("logged_outcome") or "").strip()
        if outcome not in allowed:
            raise HTTPException(
                status_code=400,
                detail="Invalid logged_outcome. Allowed values: Interested, Not Interested, Follow-up Scheduled, Others",
            )
        if outcome == "Others" and not (patch.get("logged_outcome_reason") or "").strip():
            raise HTTPException(status_code=400, detail="logged_outcome_reason is required when logged_outcome is Others")

        # If a valid outcome is logged, cancel pending Contacted SLA tasks immediately.
        tasks_coll = getattr(db, "tasks", None)
        if tasks_coll is not None:
            await tasks_coll.update_many(
                {"lead_id": lead_id, "source": "sla", "status": "pending", "sla_rule": "contacted"},
                {"$set": {"status": "cancelled", "updated_at": now_iso, "updated_at_dt": now_dt}},
            )

    # Lost reason (client confirmed): mandatory when marking certain terminal/lost statuses.
    if "lead_status" in patch:
        next_lower = next_status.strip().lower()
        if is_lost_reason_status(next_status) or is_free_text_lost_status(next_status):
            reason = (patch.get("lost_reason") or existing.get("lost_reason") or "").strip()
            if not reason:
                raise HTTPException(status_code=400, detail="lost_reason is required when marking lead as lost/junk")
            if is_lost_reason_status(next_status):
                normalized = normalize_lost_reason(reason)
                if not normalized:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid lost_reason. Select a value from the lost reason list.",
                    )
                patch["lost_reason"] = normalized

    if "lost_reason" in patch and "lead_status" not in patch:
        effective_status = (existing.get("lead_status") or "").strip()
        if is_lost_reason_status(effective_status):
            reason = (patch.get("lost_reason") or "").strip()
            if not reason:
                raise HTTPException(status_code=400, detail="lost_reason is required for this lead status")
            normalized = normalize_lost_reason(reason)
            if not normalized:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid lost_reason. Select a value from the lost reason list.",
                )
            patch["lost_reason"] = normalized

    # Global ghost-job cleanup policy (client confirmed):
    # On ANY stage transition, cancel all pending SLA tasks for this lead.
    if status_changed:
        tasks_coll = getattr(db, "tasks", None)
        if tasks_coll is not None:
            await tasks_coll.update_many(
                {"lead_id": lead_id, "source": "sla", "status": "pending"},
                {"$set": {"status": "cancelled", "updated_at": now_iso, "updated_at_dt": now_dt}},
            )

        is_sla_activation = bool(existing.get("sla_paused"))
        if is_sla_activation:
            patch["sla_paused"] = False
            patch["sla_activated_at_dt"] = now_dt

        # Stage-entry timestamps (dedicated reference fields; do not reset on subsequent updates)
        if fw_status_indicates_rnr(next_status) or next_status.strip().lower() == "rnr":
            # Fresh RNR cycle on every enter — reset clock + clear RNR SLA flags
            patch["rnr_entered_at_dt"] = now_dt
            await db.leads.update_one(
                {"id": lead_id},
                {"$unset": {"sla_flags.rnr": ""}},
            )
        if next_status.lower() == "contacted":
            if is_sla_activation or not existing.get("contacted_at_dt"):
                patch["contacted_at_dt"] = now_dt
            await db.leads.update_one(
                {"id": lead_id},
                {
                    "$unset": {
                        "sla_flags.new.alert_admin_2h_at_dt": "",
                        "sla_flags.new.reassign_30m_at_dt": "",
                    }
                },
            )
        if is_interested_status(next_status) and (is_sla_activation or not existing.get("interested_entered_at_dt")):
            patch["interested_entered_at_dt"] = now_dt
        if next_status.lower() == "gone cold":
            patch["gone_cold_entered_at_dt"] = now_dt
            await db.leads.update_one(
                {"id": lead_id},
                {"$unset": {"sla_flags.gone_cold.reevaluate_30d_at_dt": ""}},
            )
        if "negotiat" in next_status.lower() and (is_sla_activation or not existing.get("negotiation_entered_at_dt")):
            patch["negotiation_entered_at_dt"] = now_dt
        if is_terminal_lead_status(next_status):
            patch["is_rnr"] = False
        if next_status.lower() == "visit completed" and (is_sla_activation or not existing.get("visit_completed_at_dt")):
            patch["visit_completed_at_dt"] = now_dt
            patch["visit_sla_reference_dt"] = now_dt
            if "site_visit_count" not in patch:
                current_count = existing.get("site_visit_count")
                if current_count is None:
                    current_count = 0
                patch["site_visit_count"] = int(current_count) + 1
        if status_changed and next_status.lower() == "visit completed":
            patch["next_action_date"] = _ist_follow_up_date(3, now_dt)
        if status_changed and is_interested_status(next_status):
            patch["next_action_date"] = _ist_follow_up_date(7, now_dt)
        if status_changed and is_sv_followup_1_status(next_status):
            patch["sv_followup_1_entered_at_dt"] = now_dt
            patch["next_action_date"] = _ist_follow_up_date(3, now_dt)
        if status_changed and is_sv_followup_2_status(next_status):
            patch["sv_followup_2_entered_at_dt"] = now_dt
            patch["next_action_date"] = _ist_follow_up_date(7, now_dt)
        if next_status.lower() == "future prospect" and (is_sla_activation or not existing.get("future_prospect_entered_at_dt")):
            patch["future_prospect_entered_at_dt"] = now_dt
        if "re-engaged" in next_status.lower() or next_status.lower() == "reengaged":
            patch["reengaged_at_dt"] = now_dt
            await db.leads.update_one(
                {"id": lead_id},
                {"$unset": {"sla_flags.reengaged": ""}},
            )

    # Visit reschedule handling (client confirmed):
    # If visit_date_dt changes, cancel existing pending pre-24h SLA task and clear SLA flag so it can re-queue.
    if "visit_date_dt" in patch:
        old_visit = coerce_datetime(existing.get("visit_date_dt"))
        new_visit = coerce_datetime(patch.get("visit_date_dt"))
        if old_visit != new_visit:
            tasks_coll = getattr(db, "tasks", None)
            if tasks_coll is not None:
                await tasks_coll.update_many(
                    {
                        "lead_id": lead_id,
                        "source": "sla",
                        "status": "pending",
                        "sla_rule": "visit_scheduled",
                        "sla_threshold": "pre_24h",
                    },
                    {"$set": {"status": "cancelled", "updated_at": now_iso, "updated_at_dt": now_dt}},
                )
            await db.leads.update_one(
                {"id": lead_id},
                {"$unset": {"sla_flags.visit_scheduled.pre_24h_at_dt": ""}},
            )

    extra_ctx = []
    if assignee_changed:
        old_assignee = existing.get("assigned_to") or existing.get("presales_agent") or "—"
        new_assignee = patch.get("assigned_to") or patch.get("presales_agent") or old_assignee
        extra_ctx.append(
            {
                "type": "assigned",
                "timestamp": now_iso,
                "timestamp_dt": now_dt,
                "description": f"Assignee changed: {old_assignee} → {new_assignee}",
                "agent": current_user["full_name"],
                "actor_user_id": current_user.get("id"),
                "actor_name": current_user.get("full_name"),
            }
        )

    if "pipeline_category" in patch:
        old_pc = existing.get("pipeline_category")
        new_pc = patch.get("pipeline_category")
        if old_pc != new_pc:
            extra_ctx.append(
                {
                    "type": "note",
                    "timestamp": now_iso,
                    "timestamp_dt": now_dt,
                    "description": f"Pipeline category: {(old_pc or '—')} → {(new_pc or '—')}",
                    "agent": current_user["full_name"],
                    "actor_user_id": current_user.get("id"),
                    "actor_name": current_user.get("full_name"),
                }
            )

    # We'll generate a robust field-diff timeline entry after applying validation/rules,
    # so that diffs reflect the final stored values (especially temperature for Nurturing).
    diff_ignore = {
        "updated_at",
        "updated_at_dt",
        "created_at",
        "created_at_dt",
        "context_updates",
        "intent",
        "vip",
        "ai_configured",
        "ai_stale",
        "ai_generation_pending",
    }
    diff_candidate_fields = {k for k in patch.keys() if k not in diff_ignore}
    # Ensure we capture nurture label changes even when auto-populated by rules.
    if "lead_status" in patch or "temperature" in patch:
        diff_candidate_fields.add("lead_status")
        diff_candidate_fields.add("temperature")

    # Nurturing workflow gate: when a lead transitions into Nurturing, require a fresh follow-up task
    # before allowing new general notes. This resets on re-entry and clears when leaving Nurturing.
    if "lead_status" in patch:
        was_nurturing = prev_status.lower() == "nurturing".lower()
        is_nurturing = next_status.lower() == "nurturing".lower()
        if not was_nurturing and is_nurturing:
            patch["nurture_entered_at_dt"] = now_dt
            patch["nurture_task_required_since_dt"] = now_dt
            patch["nurture_task_required_task_id"] = None
        elif was_nurturing and not is_nurturing:
            patch["nurture_entered_at_dt"] = None
            patch["nurture_task_required_since_dt"] = None
            patch["nurture_task_required_task_id"] = None

    patch["updated_at"] = now_iso
    patch["updated_at_dt"] = now_dt

    apply_nurture_temperature_rules(existing, patch)
    merged = {**existing, **patch}
    patch["intent"] = determine_lead_intent(merged)
    patch["vip"] = is_vip_lead(merged)

    # Build structured field diffs (from -> to) for any changed fields in this update.
    def _norm(v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        return v

    changes = []
    for field in sorted(diff_candidate_fields):
        before = _norm(existing.get(field))
        after = _norm(patch.get(field, existing.get(field)))
        if before != after:
            changes.append({"field": field, "from": before, "to": after})

    summary_fields = [c["field"] for c in changes]
    description = f"Updated: {', '.join(summary_fields)}" if summary_fields else "Updated"

    context_update = {
        "type": "updated",
        "timestamp": now_iso,
        "timestamp_dt": now_dt,
        "description": description,
        "changes": changes,
        "agent": current_user["full_name"],
        "actor_user_id": current_user.get("id"),
        "actor_name": current_user.get("full_name"),
    }

    patch["context_updates"] = existing.get("context_updates", []) + extra_ctx + [context_update]

    await db.leads.update_one({"id": lead_id}, {"$set": patch})

    # After stage change cancels SLA tasks, sync next_action_date unless this
    # transition explicitly set a new follow-up date (Visit Completed / Interested / SV).
    if status_changed and "next_action_date" not in patch:
        try:
            from crm.services.lead_follow_up import recompute_lead_next_action_date

            await recompute_lead_next_action_date(lead_id)
        except Exception as e:
            logger.warning(
                "recompute next_action_date after status change failed lead=%s: %s",
                lead_id,
                e,
            )

    if is_sla_activation:
        lead_name = f"{existing.get('first_name', '')} {existing.get('last_name', '')}".strip()
        assignee_name = (
            patch.get("assigned_to")
            or patch.get("presales_agent")
            or existing.get("assigned_to")
            or existing.get("presales_agent")
            or ""
        )
        assignee_user_id = (
            patch.get("assigned_user_id")
            or existing.get("assigned_user_id")
            or await resolve_user_id_by_full_name(assignee_name)
        )
        if assignee_user_id:
            await create_notification(
                recipient_user_id=assignee_user_id,
                recipient_name=assignee_name,
                title="Lead activated",
                message=f"{lead_name}: {prev_status} → {next_status} — SLA tracking started",
                notification_type="lead_status_changed",
                lead_id=lead_id,
                lead_name=lead_name,
                severity="medium",
                urgency="action_needed",
                dedupe_key=f"lead_status_changed:{lead_id}",
            )

    if status_changed and ("re-engaged" in next_status.lower() or next_status.lower() == "reengaged"):
        merged_lead = {**existing, **patch}
        await create_sla_task_for_lead(
            merged_lead,
            description="Re-engaged lead — qualify intent",
            dedupe_key=f"sla:reengaged:qualify:{lead_id}",
            sla_rule="reengaged",
            sla_threshold="t0",
            stage="reengaged",
        )

    if assignee_changed:
        await log_lead_event(
            "assignee_changed",
            lead_id=lead_id,
            actor_user_id=current_user.get("id"),
            actor_name=current_user.get("full_name"),
            payload={
                "from": existing.get("assigned_to") or existing.get("presales_agent"),
                "to": patch.get("assigned_to") or patch.get("presales_agent"),
            },
        )

    updated = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    updated["created_at"] = coerce_datetime(updated.get("created_at")) or utc_now()
    updated["updated_at"] = coerce_datetime(updated.get("updated_at")) or utc_now()
    normalize_lead_for_response(updated)

    return LeadResponse(**updated)


def _parse_meta_qualified_raw(value: Any) -> Optional[bool]:
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if s in {"yes", "y", "true", "1"}:
        return True
    if s in {"no", "n", "false", "0"}:
        return False
    return None


def _parse_site_visit_count_raw(value: Any) -> int:
    if value is None or str(value).strip() == "":
        return 0
    try:
        count = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0
    return max(0, count)


def _row_get(row: dict, *keys: str) -> str:
    for key in keys:
        val = row.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


async def import_csv(
    file: UploadFile,
    current_user: dict,
) -> dict:
    contents = await file.read()
    decoded = contents.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))
    rows = list(reader)

    imported = 0
    duplicates = 0
    errors = []

    for row in rows:
        try:
            now_iso = iso_utc_now()
            now_dt = utc_now()
            first_name = (row.get("First name") or row.get("First Name") or "").strip()
            last_name = (row.get("Last name") or row.get("Last Name") or "").strip()
            if not first_name and not last_name:
                continue

            phone = _row_get(row, "Mobile", "Phone")
            work_phone = _row_get(row, "Work")
            email_raw = _row_get(row, "Email IDs", "Email", "Emails")
            email = email_raw.split(",")[0].strip() if email_raw else None

            project = _row_get(row, "Project")
            status_val = _row_get(row, "Status", "Lead Status") or "New"
            source = _row_get(row, "Source", "Lead Source")
            original_source = _row_get(row, "Original source", "Original Source")
            most_recent_source = _row_get(row, "Most recent source", "Most Recent Source")
            sales_owner = _row_get(row, "Sales owner", "Presales Agent")
            recent_note = _row_get(row, "Recent note", "Presales Description")
            created_at_raw = _row_get(row, "Created at", "Created At")
            external_id = _row_get(row, "ID")
            unit_size = _row_get(row, "Unit Size", "Unit size", "Preferred Unit")
            configuration = _row_get(row, "Configuration", "Apartment Type", "BHK")
            if not configuration and unit_size:
                configuration = unit_size
            site_visit_count = _parse_site_visit_count_raw(
                _row_get(row, "No. of Site Visits", "Site Visits", "Site visit count")
            )
            meta_qualified = _parse_meta_qualified_raw(_row_get(row, "Meta Qualified", "Meta qualified"))

            created_at = parse_csv_date(created_at_raw) if created_at_raw else now_iso
            created_at_dt = coerce_datetime(created_at) or now_dt

            lead_dict = {
                "id": str(uuid.uuid4()),
                "external_id": external_id or None,
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone or None,
                "work_phone": work_phone or None,
                "email": email,
                "project": project or None,
                "project_id": resolve_project_id(project) if project else None,
                "lead_status": status_val,
                "lead_source": source or None,
                "original_source": original_source or None,
                "most_recent_source": most_recent_source or None,
                "budget": _row_get(row, "Budget") or None,
                "configuration": configuration or None,
                "unit_size": unit_size or None,
                "location": _row_get(row, "Location", "Location Interested") or None,
                "ethnicity": _row_get(row, "Ethnicity") or None,
                "designation": _row_get(row, "Designation") or None,
                "reason_for_purchase": _row_get(row, "Reason For Purchase") or None,
                "possession_requirement": _row_get(row, "Possession Requirement") or None,
                "current_residence_type": _row_get(row, "Current Residence Type") or None,
                "campaign_name": _row_get(row, "Campaign Name", "Campaign") or None,
                "presales_agent": sales_owner or None,
                "presales_description": recent_note or None,
                "next_action_date": _row_get(row, "Next Action Date") or None,
                "site_visit_count": site_visit_count,
                "meta_qualified": meta_qualified,
                "created_at": created_at,
                "created_at_dt": created_at_dt,
                "updated_at": now_iso,
                "updated_at_dt": now_dt,
            }

            _apply_contact_phones(lead_dict)

            if lead_dict.get("normalized_phone"):
                existing = await db.leads.find_one({"normalized_phone": lead_dict["normalized_phone"]})
                if existing:
                    duplicates += 1
                    continue

            csv_temp = (row.get("Temperature") or row.get("temperature") or "").strip() or None
            temp_patch = {"lead_status": status_val}
            if csv_temp:
                temp_patch["temperature"] = csv_temp
            apply_nurture_temperature_rules({}, temp_patch, is_create=True)
            lead_dict["temperature"] = temp_patch.get("temperature")
            lead_dict["intent"] = determine_lead_intent(lead_dict)
            lead_dict["vip"] = is_vip_lead(lead_dict)
            if sales_owner:
                await assert_assignee_allowed(sales_owner)
            lead_dict["assigned_to"] = sales_owner
            lead_dict["assigned_user_id"] = await resolve_user_id_by_full_name(sales_owner)
            lead_dict["assigned_to_name"] = sales_owner or None
            lead_dict["ai_persona_summary"] = None
            lead_dict["strategic_next_moves"] = []
            lead_dict["ai_grounded_profile"] = None
            lead_dict["ai_last_generated_at"] = None
            lead_dict["ai_last_generated_at_dt"] = None
            lead_dict["import_provenance"] = "csv"
            lead_dict["context_updates"] = [
                {
                    "type": "imported",
                    "timestamp": created_at,
                    "timestamp_dt": created_at_dt,
                    "description": f"Lead imported from {source}" if source else "Lead imported from CSV",
                    "agent": current_user["full_name"],
                    "actor_user_id": current_user["id"],
                }
            ]

            if recent_note:
                lead_dict["context_updates"].append(
                    {
                        "type": "call",
                        "timestamp": now_iso,
                        "timestamp_dt": now_dt,
                        "description": recent_note,
                        "agent": sales_owner or "Agent",
                        "actor_user_id": lead_dict.get("assigned_user_id"),
                    }
                )

            await db.leads.insert_one(lead_dict)
            imported += 1
        except Exception as e:
            errors.append(str(e))

    return {"imported": imported, "duplicates": duplicates, "errors": errors}


async def merge_leads(lead_id: str, duplicate_id: str, current_user: dict) -> dict:
    primary = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    duplicate = await db.leads.find_one({"id": duplicate_id}, {"_id": 0})
    if not primary or not duplicate:
        raise HTTPException(status_code=404, detail="Lead not found")

    merged_context = primary.get("context_updates", []) + duplicate.get("context_updates", [])
    now_iso = iso_utc_now()
    now_dt = utc_now()
    merged_context.append(
        {
            "type": "merged",
            "timestamp": now_iso,
            "timestamp_dt": now_dt,
            "description": f"Merged with duplicate lead {duplicate_id}",
            "agent": current_user["full_name"],
            "actor_user_id": current_user["id"],
        }
    )
    merged_context = dedupe_context_updates(merged_context)

    await db.leads.update_one(
        {"id": lead_id},
        {"$set": {"context_updates": merged_context, "updated_at": now_iso, "updated_at_dt": now_dt}},
    )

    await db.leads.delete_one({"id": duplicate_id})
    return {"message": "Leads merged successfully"}


async def backfill_lead_stats(*, batch_size: int = 500) -> Dict[str, Any]:
    """
    One-time maintenance: sync next_action_date from pending tasks,
    normalize temperature casing, report assignment field gaps.
    """
    from crm.services.lead_follow_up import recompute_lead_next_action_date

    next_action_updated = 0
    temperature_updated = 0
    assignment_gaps = 0

    cursor = db.leads.find(
        {},
        {"_id": 0, "id": 1, "temperature": 1, "assigned_user_id": 1, "assigned_to": 1, "assigned_to_name": 1},
    )
    batch: list[str] = []
    async for lead in cursor:
        lid = lead.get("id")
        if not lid:
            continue

        temp = lead.get("temperature")
        if isinstance(temp, str) and temp.strip():
            normalized = temp.strip().title()
            if normalized in ("Hot", "Warm") and normalized != temp:
                await db.leads.update_one({"id": lid}, {"$set": {"temperature": normalized}})
                temperature_updated += 1

        has_name = any(lead.get(f) for f in ("assigned_to", "assigned_to_name", "presales_agent"))
        if has_name and not lead.get("assigned_user_id"):
            assignment_gaps += 1

        batch.append(lid)
        if len(batch) >= batch_size:
            for lead_id in batch:
                await recompute_lead_next_action_date(lead_id)
                next_action_updated += 1
            batch = []

    for lead_id in batch:
        await recompute_lead_next_action_date(lead_id)
        next_action_updated += 1

    return {
        "next_action_dates_recomputed": next_action_updated,
        "temperature_normalized": temperature_updated,
        "assignment_gaps_without_user_id": assignment_gaps,
    }
