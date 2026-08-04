"""Multi-tenant API keys for public lead intake (hashed at rest)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any, Dict, Optional

from crm.core.state import PROJECT_REGISTRY, db, iso_utc_now, resolve_project_id, utc_now

DEFAULT_RATE_LIMIT_PER_MIN = 60
KEY_PREFIX_LEN = 8


def hash_api_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_plaintext_api_key() -> str:
    return f"arihant_{secrets.token_urlsafe(32)}"


def resolve_project_for_key(project_name: str) -> Dict[str, str]:
    """Return {id, name} from PROJECT_REGISTRY or raise ValueError."""
    name = (project_name or "").strip()
    if not name:
        raise ValueError("project_name is required")

    project_id = resolve_project_id(name)
    if project_id:
        for p in PROJECT_REGISTRY:
            if p["id"] == project_id:
                return {"id": p["id"], "name": p["name"]}

    # Also allow passing canonical id (e.g. "melange")
    lowered = name.lower()
    for p in PROJECT_REGISTRY:
        if p["id"] == lowered:
            return {"id": p["id"], "name": p["name"]}

    known = ", ".join(p["name"] for p in PROJECT_REGISTRY)
    raise ValueError(f"Unknown project_name {project_name!r}. Known: {known}")


async def create_api_key(
    *,
    project_name: str,
    client_name: str,
    rate_limit_per_min: int = DEFAULT_RATE_LIMIT_PER_MIN,
) -> Dict[str, Any]:
    """Create an API key. Returns plaintext once; only hash is stored."""
    project = resolve_project_for_key(project_name)
    plaintext = generate_plaintext_api_key()
    key_hash = hash_api_key(plaintext)
    now_dt = utc_now()
    now_iso = iso_utc_now()
    doc = {
        "id": str(uuid.uuid4()),
        "key_hash": key_hash,
        "key_prefix": plaintext[:KEY_PREFIX_LEN],
        "project_name": project["name"],
        "project_id": project["id"],
        "client_name": (client_name or "").strip() or project["name"],
        "is_active": True,
        "rate_limit_per_min": int(rate_limit_per_min) if rate_limit_per_min else DEFAULT_RATE_LIMIT_PER_MIN,
        "created_at": now_iso,
        "created_at_dt": now_dt,
        "last_used_at": None,
        "last_used_at_dt": None,
    }
    await db.api_keys.insert_one(doc)
    return {
        "id": doc["id"],
        "plaintext_key": plaintext,
        "key_prefix": doc["key_prefix"],
        "project_name": doc["project_name"],
        "project_id": doc["project_id"],
        "client_name": doc["client_name"],
        "rate_limit_per_min": doc["rate_limit_per_min"],
    }


async def resolve_api_key(plaintext: Optional[str]) -> Optional[dict]:
    """Lookup active API key by plaintext. Returns Mongo doc or None."""
    if not plaintext or not str(plaintext).strip():
        return None
    key_hash = hash_api_key(str(plaintext).strip())
    doc = await db.api_keys.find_one(
        {"key_hash": key_hash, "is_active": True},
        {"_id": 0},
    )
    return doc


async def touch_api_key_last_used(api_key_id: str) -> None:
    try:
        await db.api_keys.update_one(
            {"id": api_key_id},
            {
                "$set": {
                    "last_used_at": iso_utc_now(),
                    "last_used_at_dt": utc_now(),
                }
            },
        )
    except Exception:
        pass
