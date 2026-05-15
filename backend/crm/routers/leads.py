import csv
import io
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File

from crm.core.state import (
    db,
    LeadCreate,
    LeadResponse,
    LeadUpdatePatch,
    get_current_user,
    normalize_phone,
    resolve_project_id,
    determine_lead_temperature,
    determine_lead_intent,
    is_vip_lead,
    utc_now,
    iso_utc_now,
    coerce_datetime,
    resolve_user_id_by_full_name,
)
from crm.services.ai_lead_regen import (
    ai_insights_stale,
    ai_refresh_in_progress,
    grok_keys_configured,
    schedule_lead_ai_refresh,
)


router = APIRouter()


def _normalize_lead_for_response(lead: dict) -> dict:
    if lead.get("strategic_next_moves") is None:
        lead["strategic_next_moves"] = []
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


@router.post("/leads", response_model=LeadResponse)
async def create_lead(lead: LeadCreate, current_user: dict = Depends(get_current_user)):
    lead_id = str(uuid.uuid4())
    normalized_phone = normalize_phone(lead.phone) if lead.phone else None

    if normalized_phone:
        existing = await db.leads.find_one({"normalized_phone": normalized_phone}, {"_id": 0})
        if existing:
            raise HTTPException(status_code=400, detail=f"Duplicate lead found with same phone number (ID: {existing['id']})")

    lead_dict = lead.model_dump()
    if not lead_dict.get("project_id"):
        lead_dict["project_id"] = resolve_project_id(lead_dict.get("project"))
    now_dt = utc_now()
    now_iso = iso_utc_now()
    lead_dict.update(
        {
            "id": lead_id,
            "normalized_phone": normalized_phone,
            "temperature": determine_lead_temperature(lead_dict),
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
    _normalize_lead_for_response(lead_dict)
    return LeadResponse(**lead_dict)


@router.get("/leads", response_model=List[LeadResponse])
async def get_leads(
    current_user: dict = Depends(get_current_user),
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
    skip: int = 0,
    limit: int = 100,
):
    query = {}

    if project_id:
        query["project_id"] = project_id
    if project:
        query["project"] = {"$regex": project, "$options": "i"}
    if temperature:
        query["temperature"] = temperature
    if budget:
        query["budget"] = {"$regex": budget, "$options": "i"}
    if location:
        query["location"] = {"$regex": location, "$options": "i"}
    if intent:
        query["intent"] = intent
    if vip is not None:
        query["vip"] = vip
    if status:
        query["lead_status"] = status
    if search:
        query["$or"] = [
            {"first_name": {"$regex": search, "$options": "i"}},
            {"last_name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"phone": {"$regex": search, "$options": "i"}},
        ]
    if days:
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        query["created_at"] = {"$gte": cutoff_iso}

    leads = await db.leads.find(query, {"_id": 0}).skip(skip).limit(limit).to_list(limit)

    for lead in leads:
        lead["created_at"] = coerce_datetime(lead.get("created_at")) or utc_now()
        lead["updated_at"] = coerce_datetime(lead.get("updated_at")) or utc_now()
        _normalize_lead_for_response(lead)

    return [LeadResponse(**lead) for lead in leads]


@router.get("/leads/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if isinstance(lead.get("created_at"), str):
        lead["created_at"] = coerce_datetime(lead.get("created_at")) or utc_now()
    if isinstance(lead.get("updated_at"), str):
        lead["updated_at"] = coerce_datetime(lead.get("updated_at")) or utc_now()

    lead = _normalize_lead_for_response(lead)
    cfg = grok_keys_configured()
    stale = ai_insights_stale(lead)
    lead["ai_configured"] = cfg
    lead["ai_stale"] = stale
    lead["ai_generation_pending"] = bool(cfg and (stale or ai_refresh_in_progress(lead_id)))
    if cfg and stale:
        schedule_lead_ai_refresh(lead_id, background_tasks)

    return LeadResponse(**lead)


@router.put("/leads/{lead_id}", response_model=LeadResponse)
async def update_lead(lead_id: str, lead_update: LeadUpdatePatch, current_user: dict = Depends(get_current_user)):
    existing = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Lead not found")

    patch = lead_update.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "assigned_to" in patch and "assigned_to_name" not in patch:
        patch["assigned_to_name"] = patch["assigned_to"]

    now_dt = utc_now()
    now_iso = iso_utc_now()

    extra_ctx = []
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

    context_update = {
        "type": "updated",
        "timestamp": now_iso,
        "timestamp_dt": now_dt,
        "description": f"Lead updated: {', '.join(patch.keys())}",
        "agent": current_user["full_name"],
        "actor_user_id": current_user.get("id"),
        "actor_name": current_user.get("full_name"),
    }

    patch["updated_at"] = now_iso
    patch["updated_at_dt"] = now_dt
    patch["context_updates"] = existing.get("context_updates", []) + extra_ctx + [context_update]

    merged = {**existing, **patch}
    patch["temperature"] = determine_lead_temperature(merged)
    patch["intent"] = determine_lead_intent(merged)
    patch["vip"] = is_vip_lead(merged)

    await db.leads.update_one({"id": lead_id}, {"$set": patch})

    updated = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    updated["created_at"] = coerce_datetime(updated.get("created_at")) or utc_now()
    updated["updated_at"] = coerce_datetime(updated.get("updated_at")) or utc_now()
    _normalize_lead_for_response(updated)

    return LeadResponse(**updated)


def determine_temperature_from_status(status_val: str) -> str:
    s = status_val.lower().strip()
    if s in ["interested", "site visit completed", "advance paid", "negotiation"]:
        return "Hot"
    if s in ["follow up 1", "follow up 2", "site visit scheduled", "contacted", "new", "open"]:
        return "Warm"
    return "Cold"


def parse_csv_date(date_str: str) -> str:
    for fmt in ["%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"]:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except (ValueError, AttributeError):
            continue
    return datetime.now(timezone.utc).isoformat()


@router.post("/leads/upload-csv")
async def upload_leads_csv(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    replace_all: bool = False,
):
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

            lead_dict["temperature"] = determine_temperature_from_status(status_val)
            lead_dict["intent"] = determine_lead_intent(lead_dict)
            lead_dict["vip"] = is_vip_lead(lead_dict)
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


@router.post("/leads/{lead_id}/merge/{duplicate_id}")
async def merge_leads(lead_id: str, duplicate_id: str, current_user: dict = Depends(get_current_user)):
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

    await db.leads.update_one(
        {"id": lead_id},
        {"$set": {"context_updates": merged_context, "updated_at": now_iso, "updated_at_dt": now_dt}},
    )

    await db.leads.delete_one({"id": duplicate_id})
    return {"message": "Leads merged successfully"}

