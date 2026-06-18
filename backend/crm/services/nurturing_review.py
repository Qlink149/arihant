"""Daily 14-day Nurturing admin review batch (Q7)."""

from __future__ import annotations

from datetime import timedelta

from crm.constants.lead_status import sla_paused_exclusion_clause
from crm.core.state import db, iso_utc_now, utc_now
from crm.services.brevo_service import send_nurturing_review_email
from crm.services.notification_service import create_notification
from crm.services.lead_sla_utils import is_booking_progress_status
from crm.utils.helpers import coerce_datetime

_RE_NURTURING = {"$regex": r"nurtur", "$options": "i"}


async def process_nurturing_review() -> dict:
    now_dt = utc_now()
    now_iso = iso_utc_now()
    cutoff = now_dt - timedelta(days=14)
    today = now_dt.strftime("%Y-%m-%d")

    leads = await db.leads.find(
        {
            "lead_status": _RE_NURTURING,
            "nurture_entered_at_dt": {"$lte": cutoff},
            "sla_flags.nurturing.admin_review_14d_at_dt": {"$exists": False},
            "sla_paused": sla_paused_exclusion_clause(),
        },
        {"_id": 0},
    ).to_list(500)

    eligible = []
    for lead in leads:
        if is_booking_progress_status(lead.get("lead_status")):
            continue
        entered = coerce_datetime(lead.get("nurture_entered_at_dt"))
        if not entered:
            continue
        days = int((now_dt - entered).total_seconds() / 86400)
        eligible.append(
            {
                "lead": lead,
                "days": days,
                "name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
            }
        )

    if not eligible:
        return {"ok": True, "count": 0}

    admin = await db.users.find_one(
        {"role": {"$regex": r"^\s*admin\s*$", "$options": "i"}},
        {"_id": 0, "id": 1, "full_name": 1},
    )
    if not admin:
        return {"ok": False, "error": "no_admin"}

    count = len(eligible)
    names_preview = ", ".join(e["name"] for e in eligible[:5])
    if count > 5:
        names_preview += f" (+{count - 5} more)"

    await create_notification(
        recipient_user_id=admin["id"],
        recipient_name=admin.get("full_name") or "",
        title=f"{count} leads stuck in Nurturing — 14+ days",
        message=f"Review required: {names_preview}",
        notification_type="action_required",
        stage="nurturing",
        sla_threshold="14d",
        dedupe_key=f"nurturing_review:{today}",
    )

    lead_rows = [
        {"name": e["name"], "status": e["lead"].get("lead_status", ""), "days": e["days"]}
        for e in eligible
    ]
    await send_nurturing_review_email(
        lead_count=count,
        lead_rows=lead_rows,
        admin_user_id=admin["id"],
    )

    from pymongo import UpdateOne

    ops = [
        UpdateOne(
            {"id": e["lead"]["id"]},
            {
                "$set": {
                    "sla_flags.nurturing.admin_review_14d_at_dt": now_dt,
                    "updated_at": now_iso,
                    "updated_at_dt": now_dt,
                }
            },
        )
        for e in eligible
    ]
    if ops:
        await db.leads.bulk_write(ops)

    return {"ok": True, "count": count, "admin_id": admin["id"]}
