"""Nurture label (temperature) rules — only valid when lead_status is Nurturing."""

from typing import Any, Dict, Optional, List

from fastapi import HTTPException

from crm.constants.lead_status import NURTURE_LABELS, NURTURING_STATUS
from crm.core.state import db, iso_utc_now, utc_now


def _is_nurturing_status(status: Optional[str]) -> bool:
    return (status or "").strip().lower() == NURTURING_STATUS.lower()


def _normalize_nurture_label(value: Optional[str]) -> Optional[str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    raw = str(value).strip()
    for label in NURTURE_LABELS:
        if raw.lower() == label.lower():
            return label
    return None


def _existing_valid_label(existing: dict) -> Optional[str]:
    return _normalize_nurture_label(existing.get("temperature"))


def apply_nurture_temperature_rules(
    existing: Optional[dict],
    patch: Dict[str, Any],
    *,
    is_create: bool = False,
) -> Dict[str, Any]:
    """
    Enforce nurture-label rules on a write patch.

    - Non-Nurturing statuses always clear temperature.
    - Nurturing requires Hot or Warm when status is newly set or on create.
    - temperature cannot be set on non-Nurturing leads.
    """
    existing = existing or {}
    effective_status = patch.get("lead_status", existing.get("lead_status", "New"))

    status_in_patch = "lead_status" in patch
    temp_in_patch = "temperature" in patch
    entering_nurturing = status_in_patch and _is_nurturing_status(patch.get("lead_status"))

    if not _is_nurturing_status(effective_status):
        leaving_nurturing = status_in_patch and not _is_nurturing_status(patch.get("lead_status"))
        if (
            temp_in_patch
            and _normalize_nurture_label(patch.get("temperature")) is not None
            and not leaving_nurturing
        ):
            raise HTTPException(
                status_code=400,
                detail="Nurture label (temperature) is only allowed when lead_status is Nurturing",
            )
        patch["temperature"] = None
        return patch

    # Nurturing status
    if temp_in_patch:
        normalized = _normalize_nurture_label(patch.get("temperature"))
        if normalized is None and patch.get("temperature") not in (None, ""):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid nurture label. Allowed values: {', '.join(NURTURE_LABELS)}",
            )
        patch["temperature"] = normalized
    elif entering_nurturing or is_create:
        label = _existing_valid_label(existing) if not is_create else None
        if is_create:
            label = _normalize_nurture_label(patch.get("temperature")) or _existing_valid_label(patch)
        if label is None:
            raise HTTPException(
                status_code=400,
                detail="Nurture label (Hot or Warm) is required when lead_status is Nurturing",
            )
        patch["temperature"] = label
    else:
        label = _existing_valid_label({**existing, **patch})
        if label is None:
            raise HTTPException(
                status_code=400,
                detail="Nurture label (Hot or Warm) is required when lead_status is Nurturing",
            )
        patch["temperature"] = label

    return patch


def nurture_warm_to_hot_context_entry(
    source: str,
    *,
    actor_name: str = "System",
    actor_user_id: str = "",
) -> dict:
    now_dt = utc_now()
    return {
        "type": "updated",
        "timestamp": iso_utc_now(),
        "timestamp_dt": now_dt,
        "description": f"Nurture label upgraded: Warm → Hot ({source})",
        "changes": [{"field": "temperature", "from": "Warm", "to": "Hot"}],
        "agent": actor_name,
        "actor_user_id": actor_user_id,
        "actor_name": actor_name,
    }


def nurture_hot_to_warm_context_entry(
    source: str,
    *,
    actor_name: str = "System",
    actor_user_id: str = "",
) -> dict:
    now_dt = utc_now()
    return {
        "type": "updated",
        "timestamp": iso_utc_now(),
        "timestamp_dt": now_dt,
        "description": f"Nurture label changed: Hot → Warm ({source})",
        "changes": [{"field": "temperature", "from": "Hot", "to": "Warm"}],
        "agent": actor_name,
        "actor_user_id": actor_user_id,
        "actor_name": actor_name,
    }


def apply_outcome_temperature(
    existing: dict,
    patch: Dict[str, Any],
    extra_ctx: list,
    *,
    outcome: str,
    current_user: Optional[dict] = None,
) -> None:
    """Event-driven Hot/Warm from a logged outcome (SOP 5.4). Never downgrades except T6."""
    from crm.constants.call_outcomes import (
        OUTCOME_INTERESTED,
        last_nurture_outcomes,
        last_three_are_neutral,
    )

    effective_status = patch.get("lead_status", existing.get("lead_status"))
    if not _is_nurturing_status(effective_status):
        return
    actor_name = (current_user or {}).get("full_name") or "User"
    actor_user_id = (current_user or {}).get("id") or ""
    current_temp = _normalize_nurture_label(patch.get("temperature", existing.get("temperature")))
    if outcome == OUTCOME_INTERESTED and current_temp == "Warm":
        patch["temperature"] = "Hot"
        extra_ctx.append(
            nurture_warm_to_hot_context_entry(
                "interested_outcome",
                actor_name=actor_name,
                actor_user_id=actor_user_id,
            )
        )
        return
    if current_temp != "Hot":
        return
    since = patch.get("nurture_entered_at_dt") or existing.get("nurture_entered_at_dt")
    history = last_nurture_outcomes(
        existing.get("context_updates") or [],
        since=since,
        extra_outcome=outcome,
    )
    if last_three_are_neutral(history):
        patch["temperature"] = "Warm"
        extra_ctx.append(
            nurture_hot_to_warm_context_entry(
                "three_neutral_outcomes",
                actor_name=actor_name,
                actor_user_id=actor_user_id,
            )
        )


async def upgrade_nurturing_warm_to_hot_on_lead(
    lead_id: str,
    lead: dict,
    *,
    source: str,
    actor_name: str = "System",
    actor_user_id: str = "",
) -> bool:
    """Upgrade only: Nurturing + Warm → Hot. Never downgrades."""
    if not _is_nurturing_status(lead.get("lead_status")):
        return False
    if _existing_valid_label(lead) != "Warm":
        return False
    entry = nurture_warm_to_hot_context_entry(
        source, actor_name=actor_name, actor_user_id=actor_user_id
    )
    await db.leads.update_one(
        {"id": lead_id},
        {"$set": {"temperature": "Hot"}, "$push": {"context_updates": entry}},
    )
    return True
