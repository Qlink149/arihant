"""Background refresh of Grok-derived lead insights (stale-while-revalidate)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from app.core.state import coerce_datetime, db, iso_utc_now, logger, utc_now
from app.services.ai_service import (
    generate_lead_insights,
    grok_keys_configured,
    mask_pii_text,
)

_in_flight: Set[str] = set()
_lock = asyncio.Lock()


def latest_note_call_at(lead: Dict[str, Any]) -> Optional[datetime]:
    best: Optional[datetime] = None
    for u in lead.get("context_updates") or []:
        if u.get("type") not in ("note", "call"):
            continue
        dt = u.get("timestamp_dt")
        if isinstance(dt, datetime):
            t = dt
        else:
            ts = u.get("timestamp")
            t = coerce_datetime(ts) if ts else None
        if t is None:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if best is None or t > best:
            best = t
    return best


def ai_last_generated_at(lead: Dict[str, Any]) -> Optional[datetime]:
    gen = lead.get("ai_last_generated_at_dt")
    if isinstance(gen, datetime):
        t = gen
    else:
        t = coerce_datetime(lead.get("ai_last_generated_at"))
    if isinstance(t, datetime) and t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


def ai_insights_stale(lead: Dict[str, Any]) -> bool:
    latest = latest_note_call_at(lead)
    gen = ai_last_generated_at(lead)
    if gen is None:
        return True
    if latest is None:
        return False
    return latest > gen


def ai_refresh_in_progress(lead_id: str) -> bool:
    return lead_id in _in_flight


def build_masked_transcript(lead: Dict[str, Any]) -> str:
    rows = []
    for u in lead.get("context_updates") or []:
        if u.get("type") not in ("note", "call"):
            continue
        ts = u.get("timestamp") or ""
        desc = mask_pii_text(str(u.get("description") or ""))
        agent = str(u.get("agent") or "")
        rows.append((coerce_datetime(ts) or datetime.min.replace(tzinfo=timezone.utc), f"- [{u.get('type')}] {ts} ({agent}): {desc}"))
    rows.sort(key=lambda x: x[0])
    body = "\n".join(r[1] for r in rows)
    return body if body else "(no notes or calls in timeline)"


def build_crm_hints(lead: Dict[str, Any]) -> str:
    return "\n".join(
        [
            f"project: {lead.get('project') or 'unknown'}",
            f"lead_status: {lead.get('lead_status') or 'unknown'}",
            f"original_fw_status: {lead.get('original_fw_status') or 'n/a'}",
            f"temperature: {lead.get('temperature') or 'n/a'}",
        ]
    )


async def refresh_lead_ai_insights(lead_id: str) -> None:
    async with _lock:
        if lead_id in _in_flight:
            return
        _in_flight.add(lead_id)
    try:
        lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
        if not lead:
            return
        transcript = build_masked_transcript(lead)
        hints = build_crm_hints(lead)
        payload = await generate_lead_insights(transcript=transcript, crm_hints=hints)
        now_dt = utc_now()
        now_iso = iso_utc_now()
        await db.leads.update_one(
            {"id": lead_id},
            {
                "$set": {
                    "ai_persona_summary": payload.persona_summary,
                    "strategic_next_moves": [m.model_dump() for m in payload.strategic_next_moves],
                    "ai_grounded_profile": payload.grounded_profile.model_dump(),
                    "ai_last_generated_at": now_iso,
                    "ai_last_generated_at_dt": now_dt,
                }
            },
        )
    except Exception as e:
        logger.exception("Lead AI refresh failed for %s: %s", lead_id, e)
    finally:
        async with _lock:
            _in_flight.discard(lead_id)


def schedule_lead_ai_refresh(lead_id: str, background_tasks: Any) -> None:
    background_tasks.add_task(refresh_lead_ai_insights, lead_id)
