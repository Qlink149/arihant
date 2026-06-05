"""Shared user upsert logic for CLI provisioning scripts."""

from __future__ import annotations

import uuid
from typing import Literal

from crm.core.platform_ops import get_platform_operator_email
from crm.core.state import hash_password, iso_utc_now, utc_now

ALLOWED_ROLES = frozenset({"admin", "manager", "rep"})


def normalize_role(role: str) -> str:
    r = (role or "rep").strip().lower()
    if r not in ALLOWED_ROLES:
        raise ValueError(f"Invalid role {role!r}; must be one of: admin, manager, rep")
    return r


def assert_email_allowed(email: str) -> None:
    reserved = get_platform_operator_email()
    if reserved and email.strip().lower() == reserved:
        raise ValueError(f"Cannot provision platform operator email: {email}")


async def upsert_user(
    db,
    *,
    email: str,
    password: str,
    full_name: str,
    role: str,
    phone: str | None = None,
) -> tuple[str, bool]:
    """
    Insert or update a user by email (case-insensitive).
    Returns (user_id, created) where created is True on insert.
    """
    email = email.strip().lower()
    role = normalize_role(role)
    assert_email_allowed(email)

    existing = await db.users.find_one(
        {"email": {"$regex": f"^{email}$", "$options": "i"}},
        {"_id": 0},
    )
    now_dt = utc_now()
    now_iso = iso_utc_now()

    if existing:
        user_id = existing["id"]
        await db.users.update_one(
            {"id": user_id},
            {
                "$set": {
                    "email": email,
                    "full_name": full_name,
                    "role": role,
                    "hashed_password": hash_password(password),
                    "is_active": True,
                    "updated_at": now_iso,
                    "updated_at_dt": now_dt,
                    **({"phone": phone} if phone is not None else {}),
                }
            },
        )
        return user_id, False

    user_id = str(uuid.uuid4())
    await db.users.insert_one(
        {
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "phone": phone,
            "role": role,
            "hashed_password": hash_password(password),
            "is_active": True,
            "current_session_id": None,
            "notification_dismissals": [],
            "created_at": now_iso,
            "created_at_dt": now_dt,
            "updated_at": now_iso,
            "updated_at_dt": now_dt,
        }
    )
    return user_id, True
