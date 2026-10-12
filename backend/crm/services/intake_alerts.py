"""In-app alert for a form submission that could not become a lead (never drop silently)."""

from __future__ import annotations

from typing import Optional

from crm.core.state import db, logger, utc_now


async def alert_admins_unrecognised_form(channel: str, form_label: Optional[str], *, detail: str = "") -> None:
    """One alert per form per day to every active Admin. Never raises."""
    try:
        from crm.services.notification_service import create_notification

        day = utc_now().strftime("%Y-%m-%d")
        admins = await db.users.find(
            {"role": {"$regex": r"^\s*admin\s*$", "$options": "i"}, "is_active": {"$ne": False}},
            {"_id": 0, "id": 1, "full_name": 1},
        ).to_list(20)
        label = form_label or "unknown"
        for a in admins:
            await create_notification(
                recipient_user_id=a["id"],
                recipient_name=a.get("full_name") or "",
                title=f"{channel} form not recognised - lead not created",
                message=(
                    f"A {channel} submission from the form '{label}' could not be turned into a lead. "
                    f"The details are saved so they can be recovered. {detail}".strip()
                ),
                notification_type="system_warning",
                severity="high",
                urgency="action_needed",
                dedupe_key=f"unrecognised_form:{channel}:{label}:{day}:{a['id']}",
            )
    except Exception as e:  # noqa: BLE001 - alerting must never break intake
        logger.error("unrecognised-form alert failed: %s", e)
