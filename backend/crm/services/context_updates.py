"""Deduplicate lead context_updates timeline entries."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from crm.utils.helpers import coerce_datetime


def normalize_description(text: str) -> str:
    """Normalize note text for duplicate comparison."""
    text = (text or "").lower()
    text = re.sub(r"\[\d{4}-\d{2}-\d{2}\]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _entry_timestamp(entry: Dict[str, Any]) -> datetime:
    dt = entry.get("timestamp_dt")
    if isinstance(dt, datetime):
        t = dt
    else:
        t = coerce_datetime(entry.get("timestamp")) if entry.get("timestamp") else None
    if t is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


def _dedupe_key(entry: Dict[str, Any]) -> Tuple:
    note_id = (entry.get("note_id") or entry.get("external_id") or "").strip()
    if note_id:
        return ("id", note_id)
    desc = normalize_description(entry.get("description") or "")
    etype = (entry.get("type") or "").strip().lower()
    agent = (entry.get("agent") or entry.get("actor_name") or "").strip().lower()
    return ("content", etype, agent, desc)


def dedupe_context_updates(updates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Collapse duplicate timeline rows; keep the entry with the newest timestamp.

    Duplicates match on note_id when present, otherwise (type, agent, normalized description).
    """
    if not updates:
        return []

    sorted_newest_first = sorted(updates, key=_entry_timestamp, reverse=True)
    seen: set[Tuple] = set()
    kept: List[Dict[str, Any]] = []

    for entry in sorted_newest_first:
        key = _dedupe_key(entry)
        if key in seen:
            continue
        seen.add(key)
        kept.append(entry)

    kept.sort(key=_entry_timestamp, reverse=True)
    return kept
