"""SLA-safe lead timeline writes for MCUBE calls."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from crm.core.state import db, iso_utc_now, utc_now
from crm.services.lead_events import log_lead_event


async def append_call_timeline_entry(
    lead_id: str,
    entry: dict,
    call_dt: datetime,
) -> None:
    """
    The ONLY permitted lead write from MCUBE.
    $push context_updates + $set last_call_at_dt — never updated_at / updated_at_dt.
    """
    if not lead_id:
        return
    await db.leads.update_one(
        {"id": lead_id},
        {
            "$push": {"context_updates": entry},
            "$set": {"last_call_at_dt": call_dt},
        },
    )


def build_call_timeline_entry(
    *,
    call: Dict[str, Any],
    agent_name: str = "",
    actor_user_id: str = "",
    call_dt: Optional[datetime] = None,
) -> dict:
    """Shape mirrors call_summary.py keys so DigitalTwin renders type=call."""
    now_dt = call_dt or utc_now()
    now_iso = now_dt.isoformat() if call_dt else iso_utc_now()
    direction = (call.get("direction") or "inbound").title()
    status = call.get("status") or "UNKNOWN"
    duration = call.get("duration_seconds")
    recording = call.get("recording_url") or ""
    customer = call.get("customer_number") or ""
    desc_parts = [f"{direction} call — {status}"]
    if duration is not None:
        desc_parts.append(f"{duration}s")
    if customer:
        desc_parts.append(f"from {customer}")
    description = " · ".join(desc_parts)

    key_points = [
        f"Status: {status}",
        f"Direction: {direction}",
    ]
    if duration is not None:
        key_points.append(f"Duration: {duration}s")
    if call.get("agent_name") or agent_name:
        key_points.append(f"Agent: {agent_name or call.get('agent_name')}")
    if recording:
        key_points.append(f"Recording: {recording}")

    return {
        "type": "call",
        "timestamp": now_iso,
        "timestamp_dt": now_dt,
        "description": description,
        "agent": agent_name or call.get("agent_name") or "MCUBE",
        "actor_user_id": actor_user_id or call.get("assigned_user_id") or "",
        "intent_level": "neutral",
        "key_points": key_points,
        "next_steps": None,
        "transcript": "",
        "mcube_call_id": call.get("call_id") or "",
        "recording_url": recording,
        "call_status": status,
        "direction": call.get("direction") or "inbound",
    }


async def record_call_on_lead(
    *,
    lead_id: str,
    call: Dict[str, Any],
    agent_name: str = "",
    actor_user_id: str = "",
) -> None:
    call_dt = call.get("end_time_dt") or call.get("start_time_dt") or utc_now()
    entry = build_call_timeline_entry(
        call=call,
        agent_name=agent_name,
        actor_user_id=actor_user_id,
        call_dt=call_dt,
    )
    await append_call_timeline_entry(lead_id, entry, call_dt)
    await log_lead_event(
        "mcube_call",
        lead_id=lead_id,
        actor_user_id=actor_user_id or "",
        actor_name=agent_name or "MCUBE",
        payload={
            "call_id": call.get("call_id"),
            "status": call.get("status"),
            "direction": call.get("direction"),
            "recording_url": call.get("recording_url") or "",
            "duration_seconds": call.get("duration_seconds"),
        },
    )
