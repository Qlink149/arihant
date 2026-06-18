"""Admin app settings (Brevo, routing)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from crm.core.state import db, get_current_user
from crm.services.assignment_router import get_routing_settings, ROUTING_SETTINGS_KEY
from crm.services.brevo_service import get_brevo_settings, save_brevo_settings, send_nurturing_review_email

router = APIRouter()


def _require_admin(user: dict) -> None:
    role = (user.get("role") or "").strip().lower()
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


class BrevoSettingsPatch(BaseModel):
    brevo_enabled: Optional[bool] = None
    brevo_api_key: Optional[str] = None
    alert_email: Optional[str] = None
    sender_email: Optional[str] = None
    sender_name: Optional[str] = None
    dashboard_url: Optional[str] = None


class RoutingSettingsPatch(BaseModel):
    """Reserved for future routing settings."""


@router.get("/settings/brevo")
async def get_brevo(current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    _require_admin(current_user)
    s = await get_brevo_settings()
    masked = {**s, "brevo_api_key": "***" if s.get("brevo_api_key") else ""}
    return masked


@router.put("/settings/brevo")
async def put_brevo(body: BrevoSettingsPatch, current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    _require_admin(current_user)
    patch = body.model_dump(exclude_unset=True)
    if "brevo_api_key" in patch and patch["brevo_api_key"] == "***":
        del patch["brevo_api_key"]
    return await save_brevo_settings(patch)


@router.post("/settings/brevo/test")
async def test_brevo(current_user: dict = Depends(get_current_user)) -> dict:
    _require_admin(current_user)
    ok = await send_nurturing_review_email(
        lead_count=1,
        lead_rows=[{"name": "Test Lead", "status": "Nurturing", "days": 14}],
        admin_user_id=current_user["id"],
    )
    return {"ok": ok}


@router.get("/settings/routing")
async def get_routing(current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    _require_admin(current_user)
    return await get_routing_settings()


@router.put("/settings/routing")
async def put_routing(body: RoutingSettingsPatch, current_user: dict = Depends(get_current_user)) -> dict:
    _require_admin(current_user)
    from crm.core.state import iso_utc_now

    existing = await db.app_settings.find_one({"key": ROUTING_SETTINGS_KEY}, {"_id": 0}) or {}
    value = {**(existing.get("value") or {}), **body.model_dump(exclude_unset=True)}
    await db.app_settings.update_one(
        {"key": ROUTING_SETTINGS_KEY},
        {"$set": {"key": ROUTING_SETTINGS_KEY, "value": value, "updated_at": iso_utc_now()}},
        upsert=True,
    )
    return value
