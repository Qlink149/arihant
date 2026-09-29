"""Map legacy escalation notifications (stage + threshold) to T10 whitelist pairs."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from crm.services.escalation_queue import pair_is_queue_rule

# Legacy notifications stored the SLA stage in `stage`, not `sla_rule`.
LEGACY_PAIR_MAP: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("rnr", "15d"): ("rnr", "15d"),
    ("contacted", "72h"): ("contacted", "72h"),
    ("contacted", "reassign_exhausted"): ("contacted", "reassign_exhausted"),
    ("nurturing", "hot_escalate_14d"): ("nurturing", "hot_escalate_14d"),
    ("interested", "escalate_14d"): ("interested", "escalate_14d"),
    ("visit_completed", "escalate_72h"): ("visit_completed", "escalate_72h"),
    ("new", "pool_exhausted_alert"): ("new", "pool_exhausted_alert"),
    ("reengaged", "48h"): ("reengaged", "48h"),
    # Phase 3 consolidated legacy RNR 24h/48h admin escalations into escalate_d7.
    ("rnr", "24h"): ("rnr", "escalate_d7"),
    ("rnr", "48h"): ("rnr", "escalate_d7"),
}

# Known legacy pairs that are intentionally excluded from the Escalation Queue.
LEGACY_SKIP_REASONS: Dict[Tuple[str, str], str] = {
    ("new", "2h"): "legacy new-lead admin alert (not SOP §7 whitelist)",
}


def _norm(value: Any) -> str:
    return str(value or "").strip()


def resolve_legacy_escalation_pair(notif: dict) -> Optional[Tuple[str, str]]:
    """Return a whitelist (sla_rule, sla_threshold) for a notification, if mappable."""
    sla_rule = _norm(notif.get("sla_rule"))
    sla_threshold = _norm(notif.get("sla_threshold"))
    if sla_rule and sla_threshold and pair_is_queue_rule(sla_rule, sla_threshold):
        return (sla_rule, sla_threshold)

    stage = _norm(notif.get("stage"))
    threshold = sla_threshold
    legacy_key = (stage, threshold)
    if legacy_key in LEGACY_PAIR_MAP:
        return LEGACY_PAIR_MAP[legacy_key]

    if stage == "sla":
        title = _norm(notif.get("title"))
        if "SV Follow-up 1" in title:
            return ("sv_followup_1", "escalate_72h")
        if "SV Follow-up 2" in title:
            return ("sv_followup_2", "escalate_72h")

    return None


def legacy_skip_reason(notif: dict) -> Optional[str]:
    """Human-readable reason when a legacy notification cannot be queued."""
    stage = _norm(notif.get("stage"))
    threshold = _norm(notif.get("sla_threshold"))
    if (stage, threshold) in LEGACY_SKIP_REASONS:
        return LEGACY_SKIP_REASONS[(stage, threshold)]
    if resolve_legacy_escalation_pair(notif):
        return None
    if stage or threshold:
        return f"unmapped legacy pair stage={stage!r} threshold={threshold!r}"
    title = _norm(notif.get("title")) or "(no title)"
    return f"unmapped notification title={title!r}"
