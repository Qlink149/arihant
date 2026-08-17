"""Lead project array helpers. Additive arrays + coalesced reads. Never invent names."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

PROJECT_JOIN = "; "
MAX_PROJECTS = 10
REENGAGE_FROM_STATUSES = frozenset({"closed lost", "unqualified", "gone cold"})
RE_ENGAGED_STATUS = "Re-engaged"


class EmptyProjectsError(ValueError):
    """Raised when an update explicitly sends an empty projects list."""


class TooManyProjectsError(ValueError):
    """Raised when more than MAX_PROJECTS unique names are provided."""


def split_project_string(value: Optional[str]) -> List[str]:
    """Split a legacy scalar on ';' only. Never on commas."""
    if not value:
        return []
    return _clean_names(str(value).split(";"))


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


def _clean_ids(values: Iterable[Any]) -> List[str]:
    seen = set()
    out: List[str] = []
    for raw in values:
        slug = str(raw or "").strip()
        if not slug:
            continue
        key = slug.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(slug)
    return out


def format_projects_display(projects: Sequence[str]) -> str:
    names = _clean_names(projects)
    return PROJECT_JOIN.join(names)


def coalesce_projects(lead: Optional[dict]) -> List[str]:
    """projects[] if non-empty, else split project on ';', else []. Never invent names."""
    if not lead:
        return []
    raw = lead.get("projects")
    if isinstance(raw, list) and any(str(x).strip() for x in raw):
        return _clean_names(raw)
    return split_project_string(lead.get("project"))


def coalesce_project_ids(lead: Optional[dict]) -> List[str]:
    if not lead:
        return []
    raw = lead.get("project_ids")
    if isinstance(raw, list) and any(str(x).strip() for x in raw):
        ids = _clean_ids(raw)
        existing = str(lead.get("project_id") or "").strip()
        if existing and existing.casefold() not in {i.casefold() for i in ids}:
            ids = [existing, *ids]
        return ids
    existing = str(lead.get("project_id") or "").strip()
    return [existing] if existing else []


def resolve_slug_for_name(name: Optional[str]) -> Optional[str]:
    """Token-scan display names. Exact PROJECT_REGISTRY equality is a known miss for CRM labels."""
    from crm.core.state import resolve_lead_project_key, resolve_project_id

    text = (name or "").strip()
    if not text:
        return None
    exact = resolve_project_id(text)
    if exact:
        return exact
    key = resolve_lead_project_key({"project": text, "project_id": None})
    return key or None


def incoming_slug_on_lead(lead: Optional[dict], incoming_id: Optional[str]) -> bool:
    slug = str(incoming_id or "").strip()
    if not slug or not lead:
        return False
    needle = slug.casefold()
    if str(lead.get("project_id") or "").strip().casefold() == needle:
        return True
    for existing in coalesce_project_ids(lead):
        if existing.casefold() == needle:
            return True
    return False


def should_reengage_status(status: Optional[str]) -> bool:
    return (status or "").strip().casefold() in REENGAGE_FROM_STATUSES


def primary_project_label(lead: Optional[dict]) -> str:
    """First project name for WhatsApp template variables."""
    names = coalesce_projects(lead)
    if names:
        return names[0]
    return str((lead or {}).get("project") or "").strip()


def apply_coalesce_for_response(lead: dict) -> dict:
    """Populate projects/project_ids on a read path. Do not persist."""
    names = coalesce_projects(lead)
    if names:
        lead["projects"] = names
    ids = coalesce_project_ids(lead)
    if ids:
        lead["project_ids"] = ids
    return lead


def normalize_lead_projects(
    *,
    projects: Optional[Sequence[Any]] = None,
    project: Optional[str] = None,
    existing: Optional[dict] = None,
    reject_empty: bool = False,
    caller_project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write-path normalization. projects wins over project. Preserve existing project_id if still valid."""
    projects_provided = projects is not None
    if projects_provided:
        names = _clean_names(projects)
        if reject_empty and not names:
            raise EmptyProjectsError("projects must contain at least one name")
    elif project is not None and str(project).strip():
        names = split_project_string(project)
    else:
        names = []

    if len(names) > MAX_PROJECTS:
        raise TooManyProjectsError(f"At most {MAX_PROJECTS} projects are allowed")

    if not names:
        return {}

    preserved_id = str(
        caller_project_id
        or ((existing or {}).get("project_id") if existing else None)
        or ""
    ).strip() or None

    resolved: List[str] = []
    seen_ids = set()
    for name in names:
        slug = resolve_slug_for_name(name)
        if not slug:
            continue
        key = slug.casefold()
        if key in seen_ids:
            continue
        seen_ids.add(key)
        resolved.append(slug)

    existing_ids = coalesce_project_ids(existing) if existing else []
    for slug in existing_ids:
        key = slug.casefold()
        if key not in seen_ids:
            # Keep slugs that still belong to a selected name via token match,
            # or the preserved scalar if it still matches any selected name.
            still = False
            for name in names:
                mapped = resolve_slug_for_name(name)
                if mapped and mapped.casefold() == key:
                    still = True
                    break
            if still:
                seen_ids.add(key)
                resolved.append(slug)

    if preserved_id and preserved_id.casefold() not in seen_ids:
        # Keep the stored slug if any selected name resolves to it, or if it was
        # already on the lead and at least one name is still present.
        mapped_any = any(
            (resolve_slug_for_name(n) or "").casefold() == preserved_id.casefold()
            for n in names
        )
        if mapped_any or incoming_slug_on_lead(existing, preserved_id):
            resolved = [preserved_id, *[s for s in resolved if s.casefold() != preserved_id.casefold()]]
            seen_ids.add(preserved_id.casefold())

    scalar_id = None
    if preserved_id and preserved_id.casefold() in seen_ids:
        scalar_id = preserved_id
    elif resolved:
        scalar_id = resolved[0]

    out: Dict[str, Any] = {
        "projects": names,
        "project": format_projects_display(names),
        "project_ids": resolved,
        "project_id": scalar_id,
    }
    return out


def append_incoming_project(
    existing: dict,
    *,
    incoming_name: Optional[str],
    incoming_id: Optional[str],
) -> Dict[str, Any]:
    """Append-only merge for intake. Never drops existing names or rotates project_id."""
    name = str(incoming_name or "").strip()
    slug = str(incoming_id or "").strip() or None
    names = coalesce_projects(existing)
    ids = coalesce_project_ids(existing)
    already_slug = incoming_slug_on_lead(existing, slug)
    already_name = bool(name) and name.casefold() in {n.casefold() for n in names}
    already = already_slug or already_name
    appended = False
    if name and not already_slug and not already_name:
        names.append(name)
        appended = True
    if slug and not already_slug:
        ids.append(slug)
        appended = True
    out: Dict[str, Any] = {
        "projects": names,
        "project_ids": ids,
        "appended": appended,
        "already": already,
    }
    if names:
        out["project"] = format_projects_display(names)
    return out
