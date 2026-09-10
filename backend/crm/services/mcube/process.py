"""Process ingested MCUBE events into calls + lead timeline + notifications."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional

from crm.constants.lead_status import is_terminal_lead_status
from crm.constants.mcube import is_missed_status
from crm.core.state import MCUBE_ENABLED, db, logger, utc_now
from crm.services.mcube.calls import upsert_call_from_inbound
from crm.services.mcube.events import mark_event_attempt_failed, mark_event_processed
from crm.services.mcube.match import list_admin_users, match_lead_by_customer_phone, match_user_by_agent
from crm.services.mcube.timeline import record_call_on_lead
from crm.services.notification_service import create_notification


async def process_mcube_event_doc(event: Dict[str, Any]) -> Dict[str, Any]:
    """Process one mcube_events document. Safe to call from BackgroundTasks or cron."""
    event_id = event.get("id") or ""
    payload = event.get("raw_payload") or {}
    if not isinstance(payload, dict):
        await mark_event_processed(event_id, error="invalid_payload")
        return {"ok": False, "error": "invalid_payload"}

    if not MCUBE_ENABLED:
        await mark_event_processed(event_id, error="mcube_disabled_ignored")
        return {"ok": True, "ignored": True, "reason": "disabled"}

    try:
        result = await _process_inbound_payload(payload, event_id=event_id)
        await mark_event_processed(event_id, error=None)
        return result
    except Exception as e:
        logger.exception("MCUBE event processing failed event_id=%s: %s", event_id, e)
        await mark_event_attempt_failed(event_id, str(e)[:500])
        return {"ok": False, "error": str(e)[:200]}


async def _process_inbound_payload(payload: Dict[str, Any], *, event_id: str = "") -> Dict[str, Any]:
    customer = str(payload.get("callfrom") or "").strip()
    empemail = str(payload.get("empemail") or "").strip()
    agent_phone = str(payload.get("callto") or payload.get("empnumber") or "").strip()
    agent_name = str(
        payload.get("agentname") or payload.get("assignto") or payload.get("eid") or ""
    ).strip()

    lead, method, candidates = await match_lead_by_customer_phone(customer)
    user = await match_user_by_agent(
        empemail=empemail,
        agent_phone=agent_phone,
        agent_name=agent_name,
    )

    assigned_user_id = (user or {}).get("id") or ""
    assigned_to_name = (user or {}).get("full_name") or agent_name or ""

    call = await upsert_call_from_inbound(
        payload,
        lead_id=(lead or {}).get("id"),
        lead_match_method=method,
        match_candidates=candidates,
        assigned_user_id=assigned_user_id,
        assigned_to_name=assigned_to_name,
    )

    # Fill empty lead owner only (never steal)
    if lead and assigned_user_id and not (lead.get("assigned_user_id") or "").strip():
        await db.leads.update_one(
            {"id": lead["id"], "$or": [{"assigned_user_id": {"$exists": False}}, {"assigned_user_id": ""}, {"assigned_user_id": None}]},
            {
                "$set": {
                    "assigned_user_id": assigned_user_id,
                    "assigned_to": assigned_to_name,
                    "assigned_to_name": assigned_to_name,
                }
            },
        )
        # Intentionally does NOT set updated_at / updated_at_dt

    timeline_written = False
    if lead and lead.get("id") and call.get("is_finalized"):
        # Avoid duplicate timeline rows for same call_id on re-process
        already = False
        existing_lead = await db.leads.find_one(
            {"id": lead["id"]},
            {"_id": 0, "context_updates": 1},
        )
        for upd in (existing_lead or {}).get("context_updates") or []:
            if isinstance(upd, dict) and upd.get("mcube_call_id") and upd.get("mcube_call_id") == call.get("call_id"):
                already = True
                break
        if not already:
            await record_call_on_lead(
                lead_id=lead["id"],
                call=call,
                agent_name=assigned_to_name,
                actor_user_id=assigned_user_id,
            )
            timeline_written = True

        await _maybe_notify_missed(lead=lead, call=call, assigned_user_id=assigned_user_id, assigned_to_name=assigned_to_name)

    if method in ("unmatched", "ambiguous") and call.get("is_finalized"):
        await _notify_unmatched(call=call, method=method, candidates=candidates)

    return {
        "ok": True,
        "call_id": call.get("call_id"),
        "lead_id": (lead or {}).get("id"),
        "lead_match_method": method,
        "assigned_user_id": assigned_user_id,
        "timeline_written": timeline_written,
        "event_id": event_id,
    }


async def _maybe_notify_missed(
    *,
    lead: dict,
    call: dict,
    assigned_user_id: str,
    assigned_to_name: str,
) -> None:
    status = call.get("status") or ""
    if not is_missed_status(status):
        return
    if is_terminal_lead_status(lead.get("lead_status")):
        return

    # Skip if an answered call on this lead in last 15 minutes
    since = utc_now() - timedelta(minutes=15)
    answered = await db.calls.find_one(
        {
            "lead_id": lead["id"],
            "is_answered": True,
            "start_time_dt": {"$gte": since},
        },
        {"_id": 0, "id": 1},
    )
    if answered:
        return

    recipient_id = (lead.get("assigned_user_id") or "").strip() or assigned_user_id
    recipient_name = (lead.get("assigned_to") or lead.get("assigned_to_name") or assigned_to_name or "").strip()
    if not recipient_id:
        return

    lead_name = f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip() or "Lead"
    call_id = call.get("call_id") or call.get("id") or ""
    await create_notification(
        recipient_user_id=recipient_id,
        recipient_name=recipient_name,
        title="Missed inbound call",
        message=f"Missed call from {call.get('customer_number') or 'unknown'} on {lead_name}",
        notification_type="mcube_missed_call",
        lead_id=lead["id"],
        lead_name=lead_name,
        stage="mcube",
        severity="high",
        dedupe_key=f"mcube:missed:{call_id}",
    )


async def _notify_unmatched(*, call: dict, method: str, candidates: list) -> None:
    call_id = call.get("call_id") or call.get("id") or ""
    admins = await list_admin_users()
    customer = call.get("customer_number") or ""
    title = "Unmatched inbound call" if method == "unmatched" else "Ambiguous inbound call"
    msg = (
        f"Inbound call from {customer} could not be matched to a single lead ({method})."
        if method == "unmatched"
        else f"Inbound call from {customer} matched multiple leads: {', '.join(candidates[:5])}"
    )
    for admin in admins:
        if not admin.get("id"):
            continue
        await create_notification(
            recipient_user_id=admin["id"],
            recipient_name=admin.get("full_name") or "",
            title=title,
            message=msg,
            notification_type="mcube_unmatched_call",
            lead_id="",
            severity="medium",
            dedupe_key=f"mcube:unmatched:{call_id}:{admin['id']}",
        )


_MCUBE_CRON_LOCK_JOB = "process_mcube_events"
_MCUBE_CRON_BATCH = 50


async def process_pending_mcube_events(*, limit: int = _MCUBE_CRON_BATCH) -> dict:
    """Cron mop-up: process unprocessed events with attempts < 5."""
    from datetime import timedelta
    import uuid

    from pymongo import ReturnDocument
    from pymongo.errors import DuplicateKeyError

    now_dt = utc_now()
    owner = str(uuid.uuid4())
    expires = now_dt + timedelta(minutes=4)
    try:
        lock = await db.cron_locks.find_one_and_update(
            {
                "job": _MCUBE_CRON_LOCK_JOB,
                "$or": [
                    {"expires_at": {"$lt": now_dt}},
                    {"expires_at": {"$exists": False}},
                ],
            },
            {"$set": {"job": _MCUBE_CRON_LOCK_JOB, "locked_at": now_dt, "expires_at": expires, "owner": owner}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return {"ok": False, "skipped": True, "reason": "lock_held"}
    except Exception as e:
        logger.warning("MCUBE cron lock failed: %s", e)
        return {"ok": False, "error": str(e)}

    if not lock or (lock.get("owner") or "") != owner:
        return {"ok": False, "skipped": True, "reason": "lock_held"}

    cursor = (
        db.mcube_events.find(
            {"processed": False, "attempts": {"$lt": 5}},
            {"_id": 0},
        )
        .sort([("received_at_dt", 1)])
        .limit(limit)
    )
    events = await cursor.to_list(limit)
    processed = 0
    errors = 0
    for ev in events:
        result = await process_mcube_event_doc(ev)
        if result.get("ok"):
            processed += 1
        else:
            errors += 1
    return {"ok": True, "processed": processed, "errors": errors, "batch": len(events)}
