"""Helpers for note @mentions and assignee notifications."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from crm.core.state import db
from crm.services.notification_service import create_notification

_MENTION_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_.-]*(?:\s+[A-Z][A-Za-z0-9_.-]*){0,3})")


def _lead_display_name(lead: dict) -> str:
    return f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip() or "Lead"


async def resolve_mentioned_users(
    *,
    mentioned_user_ids: Optional[Sequence[str]] = None,
    note_text: str = "",
) -> List[dict]:
    """Resolve mention targets from explicit ids and/or @Name tokens in note text."""
    ids: Set[str] = {str(x).strip() for x in (mentioned_user_ids or []) if str(x).strip()}
    names: Set[str] = set()
    for m in _MENTION_RE.finditer(note_text or ""):
        token = (m.group(1) or "").strip()
        if token:
            names.add(token.lower())

    users_by_id: Dict[str, dict] = {}
    if ids:
        async for u in db.users.find(
            {"id": {"$in": list(ids)}, "is_active": {"$ne": False}},
            {"_id": 0, "id": 1, "full_name": 1, "email": 1},
        ):
            if u.get("id"):
                users_by_id[u["id"]] = u

    if names:
        async for u in db.users.find(
            {"is_active": {"$ne": False}},
            {"_id": 0, "id": 1, "full_name": 1, "email": 1},
        ):
            fn = (u.get("full_name") or "").strip()
            if not fn or not u.get("id"):
                continue
            fl = fn.lower()
            if fl in names or any(fl.startswith(n) or n.startswith(fl) for n in names):
                users_by_id[u["id"]] = u

    return list(users_by_id.values())


async def notify_note_recipients(
    *,
    lead: dict,
    author: dict,
    note_text: str,
    mentioned_users: Iterable[dict],
) -> None:
    lead_id = lead.get("id") or ""
    lead_name = _lead_display_name(lead)
    author_id = author.get("id") or ""
    author_name = author.get("full_name") or "Someone"
    snippet = (note_text or "").strip()
    if len(snippet) > 160:
        snippet = snippet[:157] + "…"

    notified: Set[str] = set()
    if author_id:
        notified.add(author_id)

    assignee_id = (lead.get("assigned_user_id") or "").strip()
    assignee_name = (
        lead.get("assigned_to_name") or lead.get("assigned_to") or lead.get("presales_agent") or ""
    ).strip()

    if assignee_id and assignee_id not in notified:
        await create_notification(
            recipient_user_id=assignee_id,
            recipient_name=assignee_name,
            title="New note on your lead",
            message=f"{author_name} added a note on {lead_name}: {snippet}",
            notification_type="lead_note",
            lead_id=lead_id,
            lead_name=lead_name,
            severity="medium",
            urgency="action_needed",
        )
        notified.add(assignee_id)

    for u in mentioned_users:
        uid = (u.get("id") or "").strip()
        if not uid or uid in notified:
            continue
        await create_notification(
            recipient_user_id=uid,
            recipient_name=u.get("full_name") or "",
            title="You were mentioned in a note",
            message=f"{author_name} mentioned you on {lead_name}: {snippet}",
            notification_type="lead_note_mention",
            lead_id=lead_id,
            lead_name=lead_name,
            severity="medium",
            urgency="action_needed",
        )
        notified.add(uid)
