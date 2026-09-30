"""Lead location (Location Interested) helpers. Mirrors lead_project_fields.py.

batch3(item4): the field was a single free-text string; the client wants
multi-select. Storage becomes a list, but every reader here must also
accept a legacy scalar string until the migration script
(backend/scripts/migrate_location_to_list.py) has run — coalesce_locations()
is the single place that reads both shapes.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence

LOCATION_JOIN = "; "


def _clean_names(values: Iterable[Any]) -> List[str]:
    seen = set()
    out: List[str] = []
    for raw in values:
        name = str(raw or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def coalesce_locations(lead: Optional[dict]) -> List[str]:
    """locations as a list, whether stored as a legacy scalar string or a list."""
    if not lead:
        return []
    raw = lead.get("location")
    if isinstance(raw, list):
        return _clean_names(raw)
    if raw:
        return _clean_names([raw])
    return []


def format_locations_display(locations: Sequence[str]) -> str:
    return LOCATION_JOIN.join(_clean_names(locations))


def first_location(lead: Optional[dict]) -> Optional[str]:
    """A single representative location for consumers that need exactly one
    value (Meta CAPI city match, the AI persona sentence, suggestions
    matching). Never invents a value."""
    locations = coalesce_locations(lead)
    return locations[0] if locations else None
