"""Display-only call attempt counts derived from context_updates."""

from __future__ import annotations

from typing import Any, Dict, List


def compute_call_attempt_counts(context_updates: List[dict]) -> Dict[str, int]:
    """Count call timeline entries. Manual summaries count as outbound."""
    total = 0
    outbound = 0
    for entry in context_updates or []:
        if not isinstance(entry, dict):
            continue
        if (entry.get("type") or "").strip().lower() != "call":
            continue
        total += 1
        direction = (entry.get("direction") or "").strip().lower()
        if direction == "outbound" or not direction:
            outbound += 1
    return {
        "call_attempt_count_total": total,
        "call_attempt_count_outbound": outbound,
    }


def apply_call_attempt_counts_to_lead(lead: Dict[str, Any]) -> None:
    counts = compute_call_attempt_counts(lead.get("context_updates") or [])
    lead.update(counts)
