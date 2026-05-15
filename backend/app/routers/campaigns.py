import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.core.state import CampaignCreate, CampaignResponse, coerce_datetime, db, get_current_user, iso_utc_now, utc_now


router = APIRouter()


@router.post("/campaigns", response_model=CampaignResponse)
async def create_campaign(campaign: CampaignCreate, current_user: dict = Depends(get_current_user)):
    campaign_id = str(uuid.uuid4())
    now_dt = utc_now()
    now_iso = iso_utc_now()

    lead_ids = [lid for lid in (campaign.lead_ids or []) if lid]
    if not lead_ids:
        raise HTTPException(status_code=400, detail="lead_ids is required to create a campaign")

    leads = await db.leads.find({"id": {"$in": lead_ids}}, {"_id": 0}).to_list(len(lead_ids))

    found_ids = {l.get("id") for l in leads if l.get("id")}
    missing = [lid for lid in lead_ids if lid not in found_ids]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown lead_ids: {missing[:10]}")

    lead_by_id = {l["id"]: l for l in leads if l.get("id")}
    ordered_leads = [lead_by_id[lid] for lid in lead_ids if lid in lead_by_id]

    campaign_dict = campaign.model_dump()
    campaign_dict.update(
        {
            "id": campaign_id,
            "status": "active",
            "lead_count": len(ordered_leads),
            "audience": {
                "lead_ids": lead_ids,
                "filters_snapshot": campaign.filters or {},
                "audience_resolved_at": now_iso,
                "audience_resolved_at_dt": now_dt,
            },
            "leads": [
                {"id": l["id"], "name": f"{l.get('first_name', '')} {l.get('last_name', '')}", "status": "pending"}
                for l in ordered_leads
            ],
            "stats": {"total": len(ordered_leads), "interested": 0, "callback": 0, "not_interested": 0, "no_answer": 0},
            "created_at": now_iso,
            "created_at_dt": now_dt,
            "created_by": current_user["id"],
            "created_by_user_id": current_user["id"],
        }
    )

    await db.campaigns.insert_one(campaign_dict)
    campaign_dict["created_at"] = coerce_datetime(campaign_dict["created_at"]) or now_dt
    return CampaignResponse(**campaign_dict)


@router.get("/campaigns", response_model=List[CampaignResponse])
async def get_campaigns(current_user: dict = Depends(get_current_user)):
    campaigns = await db.campaigns.find({}, {"_id": 0}).sort("created_at", -1).to_list(100)

    for campaign in campaigns:
        ca = campaign.get("created_at")
        if isinstance(ca, str):
            campaign["created_at"] = datetime.fromisoformat(ca)

    return [CampaignResponse(**c) for c in campaigns]


@router.get("/campaigns/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: str, current_user: dict = Depends(get_current_user)):
    campaign = await db.campaigns.find_one({"id": campaign_id}, {"_id": 0})
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    ca = campaign.get("created_at")
    if isinstance(ca, str):
        campaign["created_at"] = datetime.fromisoformat(ca)

    return CampaignResponse(**campaign)


@router.put("/campaigns/{campaign_id}/lead/{lead_id}/status")
async def update_campaign_lead_status(
    campaign_id: str,
    lead_id: str,
    status: str,
    current_user: dict = Depends(get_current_user),
):
    campaign = await db.campaigns.find_one({"id": campaign_id}, {"_id": 0})
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    leads = campaign.get("leads", [])
    old_status = "pending"
    for lead in leads:
        if lead["id"] == lead_id:
            old_status = lead.get("status", "pending")
            lead["status"] = status
            break

    stats = campaign.get("stats", {})
    if old_status != "pending":
        stats[old_status] = stats.get(old_status, 1) - 1
    stats[status] = stats.get(status, 0) + 1

    await db.campaigns.update_one({"id": campaign_id}, {"$set": {"leads": leads, "stats": stats}})

    now_dt = utc_now()
    now_iso = iso_utc_now()
    await db.leads.update_one(
        {"id": lead_id},
        {
            "$push": {
                "context_updates": {
                    "type": "campaign",
                    "timestamp": now_iso,
                    "timestamp_dt": now_dt,
                    "description": f"Campaign '{campaign['name']}' - Status: {status}",
                    "agent": "AI Agent",
                }
            },
            "$set": {"updated_at": now_iso, "updated_at_dt": now_dt},
        },
    )

    return {"message": "Status updated"}

