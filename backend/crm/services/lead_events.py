"""Append-only lead audit events for transfers, tasks, notes, and assignments."""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from crm.core.state import db, iso_utc_now, utc_now


async def log_lead_event(
    event_type: str,
    *,
    lead_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    actor_name: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> str:
    """Persist one audit row; returns event id."""
    event_id = str(uuid.uuid4())
    now_dt = utc_now()
    doc = {
        "id": event_id,
        "event_type": event_type,
        "lead_id": lead_id or "",
        "actor_user_id": actor_user_id or "",
        "actor_name": actor_name or "",
        "payload": payload or {},
        "created_at": iso_utc_now(),
        "created_at_dt": now_dt,
    }
    await db.lead_events.insert_one(doc)
    return event_id
