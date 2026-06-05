import csv
import io
import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile

from crm.constants.lead_status import is_sv_followup_status, is_terminal_lead_status
from crm.core.platform_ops import assert_assignee_allowed
from crm.core.state import db, resolve_project_id, resolve_user_id_by_full_name
from crm.models.schemas.lead_schemas import LeadCreate, LeadResponse, LeadUpdatePatch
from crm.services.context_updates import dedupe_context_updates
from crm.services.lead_projections import (
    DUPLICATE_GROUP_PUSH,
    LEAD_LIST_SORT,
    LIST_LEAD_PROJECTION,
    trim_context_updates_for_list,
)
from crm.services.lead_events import log_lead_event
from crm.services.lead_search import build_leads_list_query
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


def _parse_created_date_boundary(value: Optional[str], *, end_of_day: bool = False) -> Optional[str]:
    """Parse YYYY-MM-DD into inclusive UTC ISO boundary for created_at filtering."""
    if not value or not str(value).strip():
        return None
    raw = str(value).strip()[:10]
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return None
    if end_of_day:
        dt = datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)
    else:
        dt = datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


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
        lead["context_updates"] = trim_context_updates_for_list(lead.get("context_updates") or [])
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


async def create_lead(lead: LeadCreate, current_user: dict) -> LeadResponse:
    lead_id = str(uuid.uuid4())
    normalized_phone = normalize_phone(lead.phone) if lead.phone else None

    if normalized_phone:
        existing = await db.leads.find_one({"normalized_phone": normalized_phone}, {"_id": 0})
        if existing:
            raise HTTPException(status_code=400, detail=f"Duplicate lead found with same phone number (ID: {existing['id']})")

    lead_dict = lead.model_dump()
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
    return LeadResponse(**lead_dict)


async def list_leads(
    project: Optional[str] = None,
    project_id: Optional[str] = None,
    temperature: Optional[str] = None,
    budget: Optional[str] = None,
    location: Optional[str] = None,
    intent: Optional[str] = None,
    vip: Optional[bool] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    days: Optional[int] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    query_base: Optional[Dict[str, Any]] = None,
) -> tuple[List[LeadResponse], int]:
    created_at_from_iso = _parse_created_date_boundary(created_from, end_of_day=False)
    created_at_to_iso = _parse_created_date_boundary(created_to, end_of_day=True)

    days_cutoff_iso = None
    if days and not (created_at_from_iso or created_at_to_iso):
        days_cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    query = build_leads_list_query(
        query_base,
        temperature=temperature,
        search=search,
        project=project,
        project_id=project_id,
        budget=budget,
        location=location,
        intent=intent,
        vip=vip,
        status=status,
        days_cutoff_iso=days_cutoff_iso,
        created_at_from_iso=created_at_from_iso,
        created_at_to_iso=created_at_to_iso,
    )

    total = await db.leads.count_documents(query)
    cursor = (
        db.leads.find(query, LIST_LEAD_PROJECTION)
        .sort(LEAD_LIST_SORT)
        .skip(skip)
        .limit(limit)
    )
    leads = await cursor.to_list(limit)

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
        lost_statuses = {"closed lost", "junk", "dropped", "unqualified"}
        if next_status.strip().lower() in lost_statuses:
            reason = (patch.get("lost_reason") or existing.get("lost_reason") or "").strip()
            if not reason:
                raise HTTPException(status_code=400, detail="lost_reason is required when marking lead as lost/junk")

    # Global ghost-job cleanup policy (client confirmed):
    # On ANY stage transition, cancel all pending SLA tasks for this lead.
    if status_changed:
        tasks_coll = getattr(db, "tasks", None)
        if tasks_coll is not None:
            await tasks_coll.update_many(
                {"lead_id": lead_id, "source": "sla", "status": "pending"},
                {"$set": {"status": "cancelled", "updated_at": now_iso, "updated_at_dt": now_dt}},
            )

        # Stage-entry timestamps (dedicated reference fields; do not reset on subsequent updates)
        if next_status.lower() == "rnr" and not existing.get("rnr_entered_at_dt"):
            patch["rnr_entered_at_dt"] = now_dt
        if next_status.lower() == "contacted":
            if not existing.get("contacted_at_dt"):
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
        if is_sv_followup_status(next_status) and not existing.get("sv_followup_entered_at_dt"):
            patch["sv_followup_entered_at_dt"] = now_dt
        if next_status.lower() == "gone cold":
            patch["gone_cold_entered_at_dt"] = now_dt
            await db.leads.update_one(
                {"id": lead_id},
                {"$unset": {"sla_flags.gone_cold.reevaluate_30d_at_dt": ""}},
            )
        if "negotiat" in next_status.lower() and not existing.get("negotiation_entered_at_dt"):
            patch["negotiation_entered_at_dt"] = now_dt
        if is_terminal_lead_status(next_status):
            patch["is_rnr"] = False
        if next_status.lower() == "visit completed" and not existing.get("visit_completed_at_dt"):
            patch["visit_completed_at_dt"] = now_dt
            patch["visit_sla_reference_dt"] = now_dt
        if next_status.lower() == "future prospect" and not existing.get("future_prospect_entered_at_dt"):
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

    if status_changed and next_status.lower() == "visit completed":
        merged_lead = {**existing, **patch}
        await create_sla_task_for_lead(
            merged_lead,
            description="Post-visit follow-up — push for booking",
            dedupe_key=f"sla:visit_completed:t0:{lead_id}",
            sla_rule="visit_completed",
            sla_threshold="t0",
            stage="visit_completed",
        )
    if status_changed and is_sv_followup_status(next_status):
        merged_lead = {**existing, **patch}
        await create_sla_task_for_lead(
            merged_lead,
            description="SV Follow Up — confirm booking intent",
            dedupe_key=f"sla:sv_followup:t0:{lead_id}",
            sla_rule="sv_followup",
            sla_threshold="t0",
            stage="sv_followup",
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


async def import_csv(
    file: UploadFile,
    current_user: dict,
    replace_all: bool = False,
    confirm_replace: Optional[str] = None,
) -> dict:
    contents = await file.read()
    decoded = contents.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))
    rows = list(reader)

    if replace_all:
        await db.leads.delete_many({})
        await log_lead_event(
            "csv_replace_all",
            actor_user_id=current_user.get("id"),
            actor_name=current_user.get("full_name"),
            payload={
                "uploaded_by": current_user.get("email"),
                "row_count": len(rows),
                "timestamp": iso_utc_now(),
            },
        )

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

            phone = (row.get("Mobile") or row.get("Phone") or "").strip()
            email_raw = (row.get("Email IDs") or row.get("Email") or "").strip()
            email = email_raw.split(",")[0].strip() if email_raw else None

            project = (row.get("Project") or "").strip()
            status_val = (row.get("Status") or row.get("Lead Status") or "New").strip()
            source = (row.get("Source") or row.get("Lead Source") or "").strip()
            sales_owner = (row.get("Sales owner") or row.get("Presales Agent") or "").strip()
            recent_note = (row.get("Recent note") or row.get("Presales Description") or "").strip()
            created_at_raw = (row.get("Created at") or "").strip()
            external_id = (row.get("ID") or "").strip()

            created_at = parse_csv_date(created_at_raw) if created_at_raw else now_iso
            created_at_dt = coerce_datetime(created_at) or now_dt

            lead_dict = {
                "id": str(uuid.uuid4()),
                "external_id": external_id,
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone,
                "email": email,
                "project": project,
                "project_id": resolve_project_id(project),
                "lead_status": status_val,
                "lead_source": source,
                "budget": (row.get("Budget") or "").strip() or None,
                "configuration": (row.get("Configuration") or "").strip() or None,
                "location": (row.get("Location") or "").strip() or None,
                "ethnicity": (row.get("Ethnicity") or "").strip() or None,
                "designation": (row.get("Designation") or "").strip() or None,
                "reason_for_purchase": (row.get("Reason For Purchase") or "").strip() or None,
                "possession_requirement": (row.get("Possession Requirement") or "").strip() or None,
                "current_residence_type": (row.get("Current Residence Type") or "").strip() or None,
                "campaign_name": (row.get("Campaign Name") or "").strip() or None,
                "presales_agent": sales_owner,
                "presales_description": recent_note,
                "next_action_date": (row.get("Next Action Date") or "").strip() or None,
                "created_at": created_at,
                "created_at_dt": created_at_dt,
                "updated_at": now_iso,
                "updated_at_dt": now_dt,
            }

            normalized_phone = normalize_phone(lead_dict.get("phone", ""))
            lead_dict["normalized_phone"] = normalized_phone

            if not replace_all and normalized_phone:
                existing = await db.leads.find_one({"normalized_phone": normalized_phone})
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

    return {"imported": imported, "duplicates": duplicates, "errors": errors, "replaced_existing": replace_all}


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
