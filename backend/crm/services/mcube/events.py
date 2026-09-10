"""Durable mcube_events ingest (apikey redacted)."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from crm.core.state import db, iso_utc_now, utc_now
from crm.services.mcube.payload import redact_payload


async def insert_mcube_event(
    *,
    raw_payload: Dict[str, Any],
    source_ip: Optional[str] = None,
    http_method: str = "POST",
    content_type: str = "",
    direction: str = "inbound",
) -> dict:
    now_dt = utc_now()
    now_iso = iso_utc_now()
    redacted = redact_payload(raw_payload)
    call_id = str(redacted.get("callid") or "").strip() or None
    doc = {
        "id": str(uuid.uuid4()),
        "direction": direction,
        "received_at": now_iso,
        "received_at_dt": now_dt,
        "http_method": http_method,
        "content_type": content_type or "",
        "source_ip": source_ip or "",
        "raw_payload": redacted,
        "call_id": call_id,
        "processed": False,
        "processed_at_dt": None,
        "error": None,
        "attempts": 0,
    }
    await db.mcube_events.insert_one(doc)
    return doc


async def mark_event_processed(event_id: str, *, error: Optional[str] = None) -> None:
    now_dt = utc_now()
    await db.mcube_events.update_one(
        {"id": event_id},
        {
            "$set": {
                "processed": True,
                "processed_at_dt": now_dt,
                "error": error,
            },
            "$inc": {"attempts": 1},
        },
    )


async def mark_event_attempt_failed(event_id: str, error: str) -> None:
    await db.mcube_events.update_one(
        {"id": event_id},
        {
            "$set": {"error": error},
            "$inc": {"attempts": 1},
        },
    )
