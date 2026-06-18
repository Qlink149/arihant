"""Brevo transactional email for internal Admin alerts (Q8)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from crm.core.state import db, iso_utc_now, logger, utc_now
from crm.services.notification_service import create_notification

BREVO_SETTINGS_KEY = "brevo"
TEMPLATE_NURTURING_REVIEW = "nurturing_review_alert"
MAX_RETRIES = 3
RETRY_MINUTES = 30


async def get_brevo_settings() -> dict:
    doc = await db.app_settings.find_one({"key": BREVO_SETTINGS_KEY}, {"_id": 0}) or {}
    value = doc.get("value") or {}
    return {
        "brevo_api_key": value.get("brevo_api_key") or os.environ.get("BREVO_API_KEY", ""),
        "brevo_enabled": bool(value.get("brevo_enabled")),
        "alert_email": value.get("alert_email") or os.environ.get("BREVO_ALERT_EMAIL", ""),
        "sender_email": value.get("sender_email") or os.environ.get("BREVO_SENDER_EMAIL", ""),
        "sender_name": value.get("sender_name") or "Arihant CRM",
        "dashboard_url": value.get("dashboard_url") or os.environ.get("DASHBOARD_URL", ""),
    }


async def save_brevo_settings(patch: dict) -> dict:
    existing = await db.app_settings.find_one({"key": BREVO_SETTINGS_KEY}, {"_id": 0}) or {}
    value = {**(existing.get("value") or {}), **patch}
    now_iso = iso_utc_now()
    await db.app_settings.update_one(
        {"key": BREVO_SETTINGS_KEY},
        {"$set": {"key": BREVO_SETTINGS_KEY, "value": value, "updated_at": now_iso}},
        upsert=True,
    )
    return value


async def _queue_failed(payload: dict, error: str) -> None:
    await db.failed_email_queue.insert_one(
        {
            "id": str(uuid.uuid4()),
            "payload": payload,
            "error": error[:500],
            "retry_count": payload.get("retry_count", 0),
            "created_at": iso_utc_now(),
            "created_at_dt": utc_now(),
        }
    )


async def send_nurturing_review_email(
    *,
    lead_count: int,
    lead_rows: List[dict],
    admin_user_id: str,
) -> bool:
    settings = await get_brevo_settings()
    if not settings.get("brevo_enabled") or not settings.get("brevo_api_key"):
        return False
    alert_email = settings.get("alert_email")
    if not alert_email:
        return False

    table_html = "<table><tr><th>Name</th><th>Status</th><th>Days</th></tr>"
    for row in lead_rows[:50]:
        table_html += (
            f"<tr><td>{row.get('name','')}</td>"
            f"<td>{row.get('status','')}</td>"
            f"<td>{row.get('days', '')}</td></tr>"
        )
    table_html += "</table>"

    params = {
        "lead_count": lead_count,
        "lead_table": table_html,
        "dashboard_url": settings.get("dashboard_url") or "",
    }
    return await _send_template_email(
        settings=settings,
        to_email=alert_email,
        template_name=TEMPLATE_NURTURING_REVIEW,
        params=params,
        subject=f"{lead_count} leads stuck in Nurturing — 14+ days",
        admin_user_id=admin_user_id,
        dedupe_key=f"brevo:nurturing:{utc_now().strftime('%Y-%m-%d')}",
    )


async def _send_template_email(
    *,
    settings: dict,
    to_email: str,
    template_name: str,
    params: dict,
    subject: str,
    admin_user_id: str,
    dedupe_key: str,
    retry_count: int = 0,
) -> bool:
    api_key = settings.get("brevo_api_key")
    sender_email = settings.get("sender_email") or to_email
    sender_name = settings.get("sender_name") or "Arihant CRM"

    body = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": params.get("body_html")
        or (
            f"<p>{subject}</p>"
            f"<p>Leads in nurturing review: {params.get('lead_count', 0)}</p>"
            f"{params.get('lead_table', '')}"
            f"<p><a href=\"{params.get('dashboard_url', '')}\">Open dashboard</a></p>"
        ),
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": api_key, "Content-Type": "application/json"},
                json=body,
            )
            resp.raise_for_status()
        return True
    except Exception as e:
        logger.warning("Brevo send failed: %s", e)
        if retry_count < MAX_RETRIES:
            await db.failed_email_queue.insert_one(
                {
                    "id": str(uuid.uuid4()),
                    "template": template_name,
                    "to_email": to_email,
                    "params": params,
                    "subject": subject,
                    "retry_count": retry_count + 1,
                    "next_retry_at_dt": utc_now() + timedelta(minutes=RETRY_MINUTES),
                    "dedupe_key": dedupe_key,
                    "error": str(e)[:500],
                    "created_at": iso_utc_now(),
                }
            )
        else:
            await _queue_failed({"template": template_name, "params": params}, str(e))
            if admin_user_id:
                await create_notification(
                    recipient_user_id=admin_user_id,
                    title="Email delivery failed",
                    message=f"Brevo nurturing review email failed after {MAX_RETRIES} retries",
                    notification_type="system_warning",
                    dedupe_key=f"{dedupe_key}:failed",
                )
        return False


async def process_failed_email_queue() -> int:
    now_dt = utc_now()
    sent = 0
    items = await db.failed_email_queue.find(
        {"next_retry_at_dt": {"$lte": now_dt}, "retry_count": {"$lte": MAX_RETRIES}},
        {"_id": 0},
    ).to_list(20)
    settings = await get_brevo_settings()
    admin = await db.users.find_one(
        {"role": {"$regex": r"^\s*admin\s*$", "$options": "i"}},
        {"_id": 0, "id": 1},
    )
    admin_id = (admin or {}).get("id", "")
    for item in items:
        ok = await _send_template_email(
            settings=settings,
            to_email=item.get("to_email") or settings.get("alert_email"),
            template_name=item.get("template") or TEMPLATE_NURTURING_REVIEW,
            params=item.get("params") or {},
            subject=item.get("subject") or "CRM Alert",
            admin_user_id=admin_id,
            dedupe_key=item.get("dedupe_key") or item["id"],
            retry_count=int(item.get("retry_count") or 0),
        )
        await db.failed_email_queue.delete_one({"id": item["id"]})
        if ok:
            sent += 1
    return sent


async def send_sla_alert_email(
    *,
    subject: str,
    body_html: str,
    admin_user_id: str,
    dedupe_key: str,
) -> bool:
    """Send a one-off SLA escalation email to the configured admin alert address."""
    settings = await get_brevo_settings()
    if not settings.get("brevo_enabled") or not settings.get("brevo_api_key"):
        return False
    alert_email = settings.get("alert_email")
    if not alert_email:
        return False
    dashboard_url = settings.get("dashboard_url") or ""
    html = body_html
    if dashboard_url:
        html += f'<p><a href="{dashboard_url}">Open dashboard</a></p>'
    return await _send_template_email(
        settings=settings,
        to_email=alert_email,
        template_name="sla_alert",
        params={"body_html": html},
        subject=subject,
        admin_user_id=admin_user_id,
        dedupe_key=dedupe_key,
    )
