"""Nurture label (temperature) rules — only valid when lead_status is Nurturing."""

from typing import Any, Dict, Optional

from fastapi import HTTPException

from crm.constants.lead_status import NURTURE_LABELS, NURTURING_STATUS


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
