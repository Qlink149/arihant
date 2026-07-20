"""Background refresh of Grok-derived lead insights (stale-while-revalidate)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from crm.core.state import coerce_datetime, db, iso_utc_now, logger, utc_now
from crm.services.ai_service import (
    generate_lead_insights,
    grok_keys_configured,
    mask_pii_text,
)

_in_flight: Set[str] = set()
_lock = asyncio.Lock()

# Timeline types that should refresh persona / strategic moves (not only notes/calls).
_AI_TIMELINE_TYPES = frozenset(
    {
        "note",
        "call",
        "whatsapp",
        "updated",
        "site_visit",
        "meeting",
        "email",
        "assigned",
        "task_completed",
    }
)

# Overview / DNA fields — editing these should refresh AI even if timestamp races.
_AI_OVERVIEW_FIELDS = frozenset(
    {
        "project",
        "budget",
        "configuration",
        "location",
        "possession_requirement",
        "reason_for_purchase",
        "lead_status",
        "temperature",
        "source",
        "preferred_floor",
        "family_size",
        "occupation",
        "purpose",
        "city",
        "area",
        "original_fw_status",
    }
)


def latest_ai_signal_at(lead: Dict[str, Any]) -> Optional[datetime]:
    """Newest timeline signal that should invalidate AI insights."""
    best: Optional[datetime] = None
    for u in lead.get("context_updates") or []:
        if u.get("type") not in _AI_TIMELINE_TYPES:
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


# Back-compat alias used by older imports/tests
def latest_note_call_at(lead: Dict[str, Any]) -> Optional[datetime]:
    return latest_ai_signal_at(lead)


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
    gen = ai_last_generated_at(lead)
    if gen is None:
        return True
    latest = latest_ai_signal_at(lead)
    if latest is not None and latest > gen:
        return True
    return False


def ai_refresh_in_progress(lead_id: str) -> bool:
    return lead_id in _in_flight


def patch_touches_ai_overview(patch: Dict[str, Any]) -> bool:
    """True when a lead update patch should trigger AI refresh."""
    if not patch:
        return False
    return any(k in _AI_OVERVIEW_FIELDS for k in patch.keys())


def build_masked_transcript(lead: Dict[str, Any]) -> str:
    rows = []
    for u in lead.get("context_updates") or []:
        utype = u.get("type")
        if utype not in _AI_TIMELINE_TYPES:
            continue
        ts = u.get("timestamp") or ""
        desc = mask_pii_text(str(u.get("description") or ""))
        if not desc.strip():
            continue
        agent = str(u.get("agent") or "")
        rows.append(
            (
                coerce_datetime(ts) or datetime.min.replace(tzinfo=timezone.utc),
                f"- [{utype}] {ts} ({agent}): {desc}",
            )
        )
    rows.sort(key=lambda x: x[0])
    # Keep transcript bounded for model context
    trimmed = rows[-80:]
    body = "\n".join(r[1] for r in trimmed)
    return body if body else "(no interaction timeline yet)"


def build_crm_hints(lead: Dict[str, Any]) -> str:
    return "\n".join(
        [
            f"project: {lead.get('project') or 'unknown'}",
            f"lead_status: {lead.get('lead_status') or 'unknown'}",
            f"original_fw_status: {lead.get('original_fw_status') or 'n/a'}",
            f"temperature: {lead.get('temperature') or 'n/a'}",
            f"budget: {lead.get('budget') or 'n/a'}",
            f"configuration: {lead.get('configuration') or 'n/a'}",
            f"location: {lead.get('location') or lead.get('city') or lead.get('area') or 'n/a'}",
            f"possession_requirement: {lead.get('possession_requirement') or 'n/a'}",
            f"reason_for_purchase: {lead.get('reason_for_purchase') or lead.get('purpose') or 'n/a'}",
            f"source: {lead.get('source') or 'n/a'}",
            f"assigned_to: {lead.get('assigned_to') or lead.get('assigned_to_name') or 'n/a'}",
        ]
    )


async def refresh_lead_ai_insights(lead_id: str) -> None:
    if not grok_keys_configured():
        return
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


def schedule_lead_ai_refresh(lead_id: str, background_tasks: Any = None) -> None:
    """Schedule AI refresh via FastAPI BackgroundTasks when available."""
    if not lead_id or not grok_keys_configured():
        return
    if background_tasks is not None:
        background_tasks.add_task(refresh_lead_ai_insights, lead_id)
        return
    enqueue_lead_ai_refresh(lead_id)


def enqueue_lead_ai_refresh(lead_id: str) -> None:
    """
    Fire-and-forget schedule for paths without BackgroundTasks
    (WhatsApp webhook, service-layer updates).
    """
    if not lead_id or not grok_keys_configured():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No running loop to enqueue AI refresh for %s", lead_id)
        return
    loop.create_task(refresh_lead_ai_insights(lead_id))
