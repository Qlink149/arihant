import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.state import db, get_current_user, iso_utc_now, utc_now


router = APIRouter()


class MarketingSpendEntry(BaseModel):
    project: str
    channel: str
    amount: float
    leads_generated: int = 0
    conversions: int = 0
    period: str
    campaign_name: Optional[str] = None
    impressions: Optional[int] = None
    clicks: Optional[int] = None
    notes: Optional[str] = None


@router.post("/marketing/spends")
async def add_marketing_spend(entry: MarketingSpendEntry, current_user: dict = Depends(get_current_user)):
    doc = entry.dict()
    doc["id"] = str(uuid.uuid4())
    now_dt = utc_now()
    now_iso = iso_utc_now()
    doc["created_by"] = current_user["full_name"]
    doc["created_by_user_id"] = current_user["id"]
    doc["created_by_name"] = current_user["full_name"]
    doc["created_at"] = now_iso
    doc["created_at_dt"] = now_dt
    doc["source"] = "manual"
    doc["cost_per_lead"] = round(doc["amount"] / doc["leads_generated"], 2) if doc["leads_generated"] > 0 else 0
    doc["cost_per_conversion"] = round(doc["amount"] / doc["conversions"], 2) if doc["conversions"] > 0 else 0
    await db.marketing_spends.insert_one(doc)
    return {"message": "Spend entry added", "id": doc["id"]}


@router.get("/marketing/spends")
async def get_marketing_spends(project: Optional[str] = None, period: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    query = {}
    if project:
        query["project"] = project
    if period:
        query["period"] = period
    entries = await db.marketing_spends.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return entries


@router.get("/marketing/dashboard")
async def get_marketing_dashboard(current_user: dict = Depends(get_current_user)):
    spends = await db.marketing_spends.find({}, {"_id": 0}).to_list(1000)

    by_project = {}
    by_channel = {}
    for s in spends:
        proj = s.get("project", "Unknown")
        chan = s.get("channel", "Unknown")

        if proj not in by_project:
            by_project[proj] = {"project": proj, "total_spend": 0, "total_leads": 0, "total_conversions": 0, "channels": {}}
        by_project[proj]["total_spend"] += s.get("amount", 0)
        by_project[proj]["total_leads"] += s.get("leads_generated", 0)
        by_project[proj]["total_conversions"] += s.get("conversions", 0)

        if chan not in by_project[proj]["channels"]:
            by_project[proj]["channels"][chan] = {"spend": 0, "leads": 0, "conversions": 0}
        by_project[proj]["channels"][chan]["spend"] += s.get("amount", 0)
        by_project[proj]["channels"][chan]["leads"] += s.get("leads_generated", 0)
        by_project[proj]["channels"][chan]["conversions"] += s.get("conversions", 0)

        if chan not in by_channel:
            by_channel[chan] = {"channel": chan, "total_spend": 0, "total_leads": 0, "total_conversions": 0}
        by_channel[chan]["total_spend"] += s.get("amount", 0)
        by_channel[chan]["total_leads"] += s.get("leads_generated", 0)
        by_channel[chan]["total_conversions"] += s.get("conversions", 0)

    for proj_data in by_project.values():
        proj_data["cpl"] = round(proj_data["total_spend"] / proj_data["total_leads"], 2) if proj_data["total_leads"] > 0 else 0
        proj_data["cpc"] = (
            round(proj_data["total_spend"] / proj_data["total_conversions"], 2) if proj_data["total_conversions"] > 0 else 0
        )
    for chan_data in by_channel.values():
        chan_data["cpl"] = round(chan_data["total_spend"] / chan_data["total_leads"], 2) if chan_data["total_leads"] > 0 else 0
        chan_data["cpc"] = (
            round(chan_data["total_spend"] / chan_data["total_conversions"], 2) if chan_data["total_conversions"] > 0 else 0
        )

    return {
        "by_project": list(by_project.values()),
        "by_channel": list(by_channel.values()),
        "total_spend": sum(s.get("amount", 0) for s in spends),
        "total_leads": sum(s.get("leads_generated", 0) for s in spends),
        "total_conversions": sum(s.get("conversions", 0) for s in spends),
        "entries": spends,
    }


@router.delete("/marketing/spends/{spend_id}")
async def delete_marketing_spend(spend_id: str, current_user: dict = Depends(get_current_user)):
    await db.marketing_spends.delete_one({"id": spend_id})
    return {"message": "Spend entry deleted"}

