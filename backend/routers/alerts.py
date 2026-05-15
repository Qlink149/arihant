from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends

from app_state import AlertConfig, db, get_current_user, iso_utc_now, utc_now


router = APIRouter()


def _stale_lead_filter(cutoff_dt: datetime, cutoff_iso: str) -> dict:
    """Match leads not touched since cutoff using BSON or legacy ISO string / date."""
    no_dt = {"$or": [{"updated_at_dt": {"$exists": False}}, {"updated_at_dt": None}]}
    legacy = {
        "$or": [
            {"updated_at": {"$lt": cutoff_iso}},
            {"updated_at": {"$type": "date", "$lt": cutoff_dt}},
        ],
    }
    return {"$or": [{"updated_at_dt": {"$lt": cutoff_dt}}, {"$and": [no_dt, legacy]}]}


@router.get("/alerts/config")
async def get_alert_configs(current_user: dict = Depends(get_current_user)):
    configs = await db.alert_configs.find({}, {"_id": 0}).to_list(100)
    return configs


@router.post("/alerts/config")
async def create_alert_config(config: AlertConfig, current_user: dict = Depends(get_current_user)):
    now_dt = utc_now()
    now_iso = iso_utc_now()
    config_dict = config.model_dump()
    config_dict.setdefault("created_at", now_iso)
    config_dict["created_at_dt"] = now_dt
    await db.alert_configs.insert_one(config_dict)
    return config_dict


@router.get("/alerts/pending")
async def get_pending_alerts(current_user: dict = Depends(get_current_user)):
    alerts = []

    cutoff_dt = utc_now() - timedelta(hours=24)
    cutoff_iso = cutoff_dt.isoformat()
    stale = _stale_lead_filter(cutoff_dt, cutoff_iso)

    rnr_leads = await db.leads.find(
        {"$and": [{"lead_status": {"$regex": "rnr", "$options": "i"}}, stale]},
        {"_id": 0},
    ).to_list(100)

    alert_ids = set()
    for lead in rnr_leads:
        lid = lead["id"]
        alert_ids.add(lid)
        alerts.append(
            {
                "type": "rnr_followup",
                "lead_id": lid,
                "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}",
                "message": "RNR lead needs follow-up (>24 hours)",
                "severity": "high",
            }
        )

    stale_leads = await db.leads.find(stale, {"_id": 0}).limit(50).to_list(50)

    for lead in stale_leads:
        lid = lead["id"]
        if lid not in alert_ids:
            alert_ids.add(lid)
            alerts.append(
                {
                    "type": "stale_lead",
                    "lead_id": lid,
                    "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}",
                    "message": "Lead not updated in 24+ hours",
                    "severity": "medium",
                }
            )

    return alerts

