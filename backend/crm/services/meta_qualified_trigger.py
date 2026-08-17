"""When a Meta lead becomes qualified, set the CRM flag and send CAPI once.

Auto-set ``meta_qualified=True`` when status enters Contacted or Interested
(from any prior stage, including RNR). Agents can also set the flag by hand.
CAPI ``QualifiedLead`` fires only for Facebook sources, and only when the flag
becomes Yes. Successful sends are not repeated.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

from crm.core.state import logger

META_SOURCE_ALIASES = frozenset(
    {
        "facebook lead form",
        "facebook_ad",
        "facebook lead ads",
    }
)
_QUALIFY_STATUSES = frozenset({"contacted", "interested"})
_WS_RE = re.compile(r"\s+")


def _norm_source(value: Any) -> str:
    return _WS_RE.sub(" ", str(value or "").strip().lower())


def _source_is_meta(value: Any) -> bool:
    return _norm_source(value) in META_SOURCE_ALIASES


def is_meta_lead(lead: Optional[dict]) -> bool:
    """True when lead_source or original_source is a Facebook Instant Form / ad source."""
    if not isinstance(lead, dict):
        return False
    return _source_is_meta(lead.get("lead_source")) or _source_is_meta(lead.get("original_source"))


def is_qualify_status(status: Any) -> bool:
    return str(status or "").strip().lower() in _QUALIFY_STATUSES


def should_auto_set_meta_qualified(
    lead: Optional[dict],
    *,
    status_changed: bool,
    next_status: Any,
) -> bool:
    """Auto-tick Meta Qualified when a Meta lead enters Contacted or Interested."""
    if not status_changed:
        return False
    if not is_meta_lead(lead):
        return False
    return is_qualify_status(next_status)


def _is_meta_qualified_yes(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    return str(value).strip().lower() in {"yes", "y", "true", "1"}


def meta_qualified_became_yes(previous: Any, next_value: Any) -> bool:
    """True only on the unset/false → Yes transition."""
    return (not _is_meta_qualified_yes(previous)) and _is_meta_qualified_yes(next_value)


def should_send_qualified_lead_capi(
    lead: Optional[dict],
    *,
    previous_meta_qualified: Any,
    next_meta_qualified: Any,
) -> bool:
    if not is_meta_lead(lead):
        return False
    return meta_qualified_became_yes(previous_meta_qualified, next_meta_qualified)


async def _send_qualified_lead_capi(lead: dict) -> None:
    try:
        from crm.services.meta_capi_service import send_qualified_lead_event

        await send_qualified_lead_event(lead)
    except Exception as e:
        logger.error(
            "Meta CAPI trigger failed lead=%s: %s",
            (lead or {}).get("id"),
            e,
            exc_info=True,
        )


def schedule_qualified_lead_capi(lead: Optional[dict]) -> None:
    """Fire-and-forget CAPI send so a Meta outage does not block the CRM save."""
    if not isinstance(lead, dict):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "Meta CAPI skipped: no running event loop lead=%s",
            lead.get("id"),
        )
        return
    loop.create_task(_send_qualified_lead_capi(dict(lead)))
