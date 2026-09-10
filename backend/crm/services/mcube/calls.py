"""Upsert MCUBE call CDR documents."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from crm.constants.mcube import normalize_inbound_dialstatus
from crm.core.state import db, iso_utc_now, utc_now
from crm.services.mcube.duration import parse_duration
from crm.utils.helpers import normalize_phone, parse_mcube_dt


def _nonempty(val: Any) -> bool:
    if val is None:
        return False
    if isinstance(val, str) and not val.strip():
        return False
    return True


def map_inbound_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Map lowercase MCUBE payload keys into calls document fields (partial OK)."""
    call_id = str(payload.get("callid") or "").strip() or None
    customer_raw = str(payload.get("callfrom") or "").strip()
    agent_raw = str(payload.get("callto") or payload.get("empnumber") or "").strip()
    empemail = str(payload.get("empemail") or "").strip()
    dial_raw = str(payload.get("dialstatus") or "").strip()
    status, is_answered = normalize_inbound_dialstatus(dial_raw)
    start_dt = parse_mcube_dt(payload.get("starttime"))
    end_dt = parse_mcube_dt(payload.get("endtime"))
    duration_seconds = parse_duration(payload.get("duration"))
    answered_seconds = parse_duration(payload.get("answeredtime"))
    wall_seconds = None
    if start_dt and end_dt and end_dt >= start_dt:
        wall_seconds = int((end_dt - start_dt).total_seconds())

    filename = str(payload.get("filename") or "").strip()
    recording_available = bool(filename)

    call_type = str(payload.get("calltype") or payload.get("callType") or "inbound").strip()
    direction = "inbound"
    if call_type.lower() == "outbound":
        direction = "outbound"

    doc: Dict[str, Any] = {
        "call_id": call_id,
        "direction": direction,
        "agent_number": agent_raw,
        "agent_number_10": normalize_phone(agent_raw) if agent_raw else "",
        "customer_number": customer_raw,
        "customer_number_10": normalize_phone(customer_raw) if customer_raw else "",
        "did_number": str(payload.get("landingnumber") or "").strip(),
        "group_name": str(payload.get("gid") or "").strip(),
        "agent_name": str(
            payload.get("agentname") or payload.get("assignto") or payload.get("eid") or ""
        ).strip(),
        "empemail": empemail,
        "empnumber": str(payload.get("empnumber") or "").strip(),
        "empid": str(payload.get("empid") or "").strip(),
        "status_raw": dial_raw,
        "status": status,
        "is_answered": is_answered,
        "recording_url": filename,
        "recording_available": recording_available,
        "ref_id": str(payload.get("refid") or "").strip() or None,
        "gid": str(payload.get("gid") or "").strip(),
        "businessname": str(payload.get("businessname") or "").strip(),
        "region": str(payload.get("region") or "").strip(),
        "pulse": str(payload.get("pulse") or "").strip(),
        "call_type_raw": call_type,
        "mcube_calid": str(payload.get("calid") or "").strip(),
    }
    if start_dt:
        doc["start_time"] = start_dt.isoformat()
        doc["start_time_dt"] = start_dt
    if end_dt:
        doc["end_time"] = end_dt.isoformat()
        doc["end_time_dt"] = end_dt
    if duration_seconds is not None:
        doc["duration_seconds"] = duration_seconds
    if answered_seconds is not None:
        doc["answered_seconds"] = answered_seconds
    if wall_seconds is not None:
        doc["wall_seconds"] = wall_seconds

    # Finalize when hangup-like: dialstatus present and endtime/duration/recording
    if dial_raw and status != "UNKNOWN":
        if _nonempty(payload.get("endtime")) or duration_seconds is not None or recording_available:
            doc["is_finalized"] = True
        else:
            doc["is_finalized"] = False
    else:
        doc["is_finalized"] = False

    return doc


def _merge_nonempty(existing: dict, incoming: dict) -> dict:
    """Never null out existing non-empty values with empty incoming."""
    out = dict(existing)
    for k, v in incoming.items():
        if k in ("id", "created_at", "created_at_dt", "first_seen_at_dt", "event_count"):
            continue
        if not _nonempty(v) and _nonempty(out.get(k)):
            continue
        if existing.get("is_finalized") and k == "is_finalized" and v is False:
            continue
        if existing.get("is_finalized") and not incoming.get("is_finalized"):
            # Non-terminal late event: only fill empties
            if _nonempty(out.get(k)):
                continue
        out[k] = v
    return out


async def upsert_call_from_inbound(
    payload: Dict[str, Any],
    *,
    lead_id: Optional[str] = None,
    lead_match_method: str = "",
    match_candidates: Optional[list] = None,
    assigned_user_id: str = "",
    assigned_to_name: str = "",
) -> dict:
    now_dt = utc_now()
    now_iso = iso_utc_now()
    mapped = map_inbound_fields(payload)
    call_id = mapped.get("call_id")

    extras = {
        "lead_id": lead_id or None,
        "lead_match_method": lead_match_method or "",
        "match_candidates": match_candidates or [],
        "assigned_user_id": assigned_user_id or "",
        "assigned_to_name": assigned_to_name or "",
        "last_event_at_dt": now_dt,
    }
    mapped.update({k: v for k, v in extras.items() if _nonempty(v) or k in ("match_candidates", "lead_match_method")})

    existing = None
    if call_id:
        existing = await db.calls.find_one({"call_id": call_id}, {"_id": 0})

    if existing:
        if existing.get("is_finalized") and not mapped.get("is_finalized"):
            # Audit-only bump
            await db.calls.update_one(
                {"call_id": call_id},
                {"$set": {"last_event_at_dt": now_dt}, "$inc": {"event_count": 1}},
            )
            existing["event_count"] = int(existing.get("event_count") or 0) + 1
            return existing

        merged = _merge_nonempty(existing, mapped)
        # Prefer incoming lead/agent when previously empty
        if not existing.get("lead_id") and lead_id:
            merged["lead_id"] = lead_id
            merged["lead_match_method"] = lead_match_method
            merged["match_candidates"] = match_candidates or []
        if not existing.get("assigned_user_id") and assigned_user_id:
            merged["assigned_user_id"] = assigned_user_id
            merged["assigned_to_name"] = assigned_to_name
        merged["last_event_at_dt"] = now_dt
        merged["event_count"] = int(existing.get("event_count") or 0) + 1
        await db.calls.update_one({"call_id": call_id}, {"$set": merged})
        return merged

    doc = {
        "id": str(uuid.uuid4()),
        **mapped,
        "event_count": 1,
        "created_at": now_iso,
        "created_at_dt": now_dt,
        "first_seen_at_dt": now_dt,
        "last_event_at_dt": now_dt,
    }
    if not doc.get("call_id"):
        # Cannot unique-index null clusters meaningfully; still store with uuid-only id
        pass
    await db.calls.insert_one(doc)
    return doc
