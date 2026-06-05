"""Centralized in-app notifications with fired_at and overdue helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from crm.core.state import db, iso_utc_now, utc_now
from crm.services.notifications_stream import notifications_stream
from crm.utils.helpers import coerce_datetime

# SLA window in seconds for overdue badge (calendar unless noted)
SLA_OVERDUE_WINDOWS = {
    "new": {"30m": 30 * 60, "2h": 2 * 3600},
    "rnr": {"24h": 24 * 3600, "48h": 48 * 3600},
    "contacted": {"48h": 48 * 3600, "72h": 72 * 3600},
    "visit_completed": {"48h": 48 * 3600, "72h": 72 * 3600, "7d": 7 * 24 * 3600},
    "sv_followup": {"72h": 72 * 3600, "7d": 7 * 24 * 3600},
    "negotiation": {"48h": 48 * 3600, "stalled_7d": 7 * 24 * 3600, "admin_15d": 15 * 24 * 3600},
    "reengaged": {"12h": 12 * 3600, "24h": 24 * 3600, "48h": 48 * 3600},
    "nurturing": {"14d": 14 * 24 * 3600},
}


def compute_is_overdue(
    notification: dict,
    now_dt: Optional[datetime] = None,
) -> bool:
    now_dt = now_dt or utc_now()
    fired = coerce_datetime(notification.get("fired_at_dt")) or coerce_datetime(
        notification.get("created_at_dt")
    ) or coerce_datetime(notification.get("created_at"))
    if not fired:
        return False
    if fired.tzinfo is None:
        fired = fired.replace(tzinfo=timezone.utc)

    stage = (notification.get("stage") or "").strip().lower()
    threshold = (notification.get("sla_threshold") or "").strip().lower()
    windows = SLA_OVERDUE_WINDOWS.get(stage, {})
    window_sec = windows.get(threshold)
    if not window_sec and threshold.endswith("h"):
        try:
            window_sec = int(threshold.replace("h", "")) * 3600
        except ValueError:
            window_sec = None
    if not window_sec:
        return False
    return (now_dt - fired).total_seconds() > window_sec


async def create_notification(
    *,
    recipient_user_id: str,
    recipient_name: str = "",
    title: str,
    message: str,
    notification_type: str = "action_required",
    lead_id: str = "",
    lead_name: str = "",
    task_id: Optional[str] = None,
    stage: str = "",
    sla_threshold: str = "",
    severity: str = "medium",
    urgency: str = "action_needed",
    dedupe_key: Optional[str] = None,
    publish_sse: bool = True,
) -> dict:
    now_dt = utc_now()
    now_iso = iso_utc_now()
    doc = {
        "id": str(uuid.uuid4()),
        "type": notification_type,
        "notification_type": notification_type,
        "title": title,
        "message": message,
        "lead_id": lead_id or "",
        "lead_name": lead_name or "",
        "task_id": task_id or "",
        "stage": stage,
        "sla_threshold": sla_threshold,
        "severity": severity,
        "urgency": urgency,
        "assigned_to": recipient_name,
        "recipient_name": recipient_name,
        "recipient_user_id": recipient_user_id,
        "is_read": False,
        "fired_at_dt": now_dt,
        "created_at": now_iso,
        "created_at_dt": now_dt,
    }
    if dedupe_key:
        doc["dedupe_key"] = dedupe_key
        existing = await db.notifications.find_one({"dedupe_key": dedupe_key}, {"_id": 0})
        if existing:
            return existing

    await db.notifications.insert_one(doc)
    if publish_sse and recipient_user_id:
        try:
            await notifications_stream.publish(recipient_user_id, doc)
        except Exception:
            pass
    return doc


def enrich_notification(doc: dict, now_dt: Optional[datetime] = None) -> dict:
    out = dict(doc)
    out["is_overdue"] = compute_is_overdue(out, now_dt)
    return out
