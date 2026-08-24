import os
import re
from typing import List, Optional, Set

from fastapi import Depends, HTTPException, status

from crm.core.state import db, get_current_user, logger

DEFAULT_PLATFORM_OPERATOR_EMAIL = "yogansh@claraai.tech"
_startup_warned_missing_env = False


def get_platform_operator_emails() -> Set[str]:
    """All configured platform operator emails (comma-separated in env), lowercased."""
    explicit = os.environ.get("PLATFORM_OPERATOR_EMAIL") or ""
    emails = {e.strip().lower() for e in explicit.split(",") if e.strip()}
    if emails:
        return emails
    return {DEFAULT_PLATFORM_OPERATOR_EMAIL.strip().lower()}


def get_platform_operator_email() -> str:
    """Back-compat single-value accessor: one representative platform operator email."""
    return sorted(get_platform_operator_emails())[0]


def warn_if_platform_operator_env_missing() -> None:
    global _startup_warned_missing_env
    if _startup_warned_missing_env:
        return
    if not (os.environ.get("PLATFORM_OPERATOR_EMAIL") or "").strip():
        logger.warning(
            "PLATFORM_OPERATOR_EMAIL is not set; using default %s for platform operator features",
            DEFAULT_PLATFORM_OPERATOR_EMAIL,
        )
    _startup_warned_missing_env = True


def is_platform_operator(user: dict) -> bool:
    allowed = get_platform_operator_emails()
    if not allowed:
        return False
    email = (user.get("email") or "").strip().lower()
    return email in allowed


async def get_platform_operator_identities() -> List[dict]:
    emails = get_platform_operator_emails()
    if not emails:
        return []
    patterns = [re.compile(f"^{re.escape(e)}$", re.IGNORECASE) for e in emails]
    return await db.users.find(
        {"email": {"$in": patterns}},
        {"_id": 0, "id": 1, "email": 1, "full_name": 1},
    ).to_list(len(emails))


async def get_blocked_assignee_values() -> Set[str]:
    """Lowercase names/emails that must not receive leads, tasks, or transfers."""
    blocked: Set[str] = set(get_platform_operator_emails())
    for identity in await get_platform_operator_identities():
        if identity.get("email"):
            blocked.add(identity["email"].strip().lower())
        if identity.get("full_name"):
            blocked.add(identity["full_name"].strip().lower())
    return blocked


def _normalize_assignee(value: Optional[str]) -> str:
    return (value or "").strip().lower()


async def is_blocked_assignee(value: Optional[str]) -> bool:
    normalized = _normalize_assignee(value)
    if not normalized:
        return False
    blocked = await get_blocked_assignee_values()
    return normalized in blocked


async def assert_assignee_allowed(value: Optional[str]) -> None:
    if await is_blocked_assignee(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This user cannot be assigned work",
        )


def is_blocked_assignee_name(agent: str, blocked: Set[str]) -> bool:
    return _normalize_assignee(agent) in blocked


async def require_platform_operator(current_user: dict = Depends(get_current_user)) -> dict:
    if not is_platform_operator(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized",
        )
    return current_user
