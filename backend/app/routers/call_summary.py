from fastapi import APIRouter, Depends, HTTPException

from app.core.state import CallSummary, db, get_current_user, iso_utc_now, utc_now


router = APIRouter()


@router.post("/leads/{lead_id}/call-summary")
async def add_call_summary(lead_id: str, summary: CallSummary, current_user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    now_dt = utc_now()
    now_iso = iso_utc_now()
    context_update = {
        "type": "call",
        "timestamp": now_iso,
        "timestamp_dt": now_dt,
        "description": summary.summary or "Call recorded",
        "agent": current_user["full_name"],
        "actor_user_id": current_user["id"],
        "intent_level": summary.intent_level,
        "key_points": summary.key_points,
        "next_steps": summary.next_steps,
        "transcript": summary.transcript,
    }

    new_temp = lead.get("temperature", "Warm")
    if summary.intent_level == "high":
        new_temp = "Hot"
    elif summary.intent_level == "low":
        new_temp = "Cold"

    await db.leads.update_one(
        {"id": lead_id},
        {"$push": {"context_updates": context_update}, "$set": {"temperature": new_temp, "updated_at": now_iso, "updated_at_dt": now_dt}},
    )

    return {"message": "Call summary added", "intent_level": summary.intent_level}

