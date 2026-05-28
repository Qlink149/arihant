import csv
import io
import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile

from crm.core.platform_ops import assert_assignee_allowed
from crm.core.state import db, resolve_project_id, resolve_user_id_by_full_name
from crm.models.schemas.lead_schemas import LeadCreate, LeadResponse, LeadUpdatePatch
from crm.services.context_updates import dedupe_context_updates
from crm.services.lead_events import log_lead_event
from crm.services.lead_search import build_leads_list_query
from crm.services.nurture_temperature import apply_nurture_temperature_rules
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


def normalize_lead_for_response(lead: dict) -> dict:
    if lead.get("strategic_next_moves") is None:
        lead["strategic_next_moves"] = []
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

    now_dt = utc_now()
    now_iso = iso_utc_now()
    lead_dict.update(
        {
            "id": lead_id,
            "normalized_phone": normalized_phone,
            "intent": determine_lead_intent(lead_dict),
            "vip": is_vip_lead(lead_dict),
            "assigned_to": None,
            "assigned_user_id": None,
            "assigned_to_name": None,
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
    leads = await db.leads.find(query, {"_id": 0}).skip(skip).limit(limit).to_list(limit)

    for lead in leads:
        lead["created_at"] = coerce_datetime(lead.get("created_at")) or utc_now()
        lead["updated_at"] = coerce_datetime(lead.get("updated_at")) or utc_now()
        normalize_lead_for_response(lead)

    return [LeadResponse(**lead) for lead in leads], total


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
        prev_status = (existing.get("lead_status") or "").strip()
        next_status = (patch.get("lead_status") or "").strip()
        was_nurturing = prev_status.lower() == "nurturing".lower()
        is_nurturing = next_status.lower() == "nurturing".lower()
        if not was_nurturing and is_nurturing:
            patch["nurture_task_required_since_dt"] = now_dt
            patch["nurture_task_required_task_id"] = None
        elif was_nurturing and not is_nurturing:
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


async def import_csv(file: UploadFile, current_user: dict, replace_all: bool = False) -> dict:
    contents = await file.read()
    decoded = contents.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))

    if replace_all:
        await db.leads.delete_many({})

    imported = 0
    duplicates = 0
    errors = []

    for row in reader:
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
