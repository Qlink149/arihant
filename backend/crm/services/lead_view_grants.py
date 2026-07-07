"""Temporary view-only access grants for leads (exact lookup)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Optional

from crm.core.state import db
from crm.utils.helpers import iso_utc_now, utc_now


DEFAULT_GRANT_MINUTES = 10


async def upsert_view_grant(
    *,
    lead_id: str,
    user_id: str,
    minutes: int = DEFAULT_GRANT_MINUTES,
    reason: str = "exact_lookup",
    lookup_type: Optional[str] = None,
    lookup_value: Optional[str] = None,
) -> dict:
    """
    Create or extend a temporary view grant.

    Returns the stored/updated document (sans _id).
    """
    if not lead_id or not user_id:
        raise ValueError("lead_id and user_id are required")

    now_dt = utc_now()
    now_iso = iso_utc_now()
    expires_dt = now_dt + timedelta(minutes=max(int(minutes), 1))
    expires_iso = expires_dt.isoformat()

    filt = {"lead_id": lead_id, "user_id": user_id}
    update = {
        "$set": {
            "expires_at": expires_iso,
            "expires_at_dt": expires_dt,
            "reason": reason,
            "lookup_type": lookup_type or "",
            "lookup_value": lookup_value or "",
            "updated_at": now_iso,
            "updated_at_dt": now_dt,
        },
        "$setOnInsert": {
            "id": str(uuid.uuid4()),
            "lead_id": lead_id,
            "user_id": user_id,
            "created_at": now_iso,
            "created_at_dt": now_dt,
        },
    }

    await db.lead_view_grants.update_one(filt, update, upsert=True)
    doc = await db.lead_view_grants.find_one(filt, {"_id": 0})
    return doc or {"lead_id": lead_id, "user_id": user_id, "expires_at_dt": expires_dt}


async def has_active_view_grant(*, lead_id: str, user_id: str) -> bool:
    """True if a non-expired grant exists."""
    if not lead_id or not user_id:
        return False
    now_dt = utc_now()
    doc = await db.lead_view_grants.find_one(
        {"lead_id": lead_id, "user_id": user_id, "expires_at_dt": {"$gt": now_dt}},
        {"_id": 1},
    )
    return doc is not None

