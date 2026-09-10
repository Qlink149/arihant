"""Lead / agent matching for MCUBE inbound."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from crm.core.state import db
from crm.utils.helpers import normalize_phone


async def match_lead_by_customer_phone(customer_phone: str) -> Tuple[Optional[dict], str, List[str]]:
    """
    Returns (lead_or_None, lead_match_method, match_candidate_ids).
    Methods: phone_primary | phone_work | ambiguous | unmatched
    """
    norm = normalize_phone(customer_phone or "")
    if not norm:
        return None, "unmatched", []

    primary = await db.leads.find(
        {"normalized_phone": norm},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "assigned_user_id": 1, "assigned_to": 1, "lead_status": 1},
    ).to_list(20)
    if len(primary) == 1:
        return primary[0], "phone_primary", [primary[0]["id"]]
    if len(primary) > 1:
        return None, "ambiguous", [p["id"] for p in primary if p.get("id")]

    work = await db.leads.find(
        {"normalized_work_phone": norm},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "assigned_user_id": 1, "assigned_to": 1, "lead_status": 1},
    ).to_list(20)
    if len(work) == 1:
        return work[0], "phone_work", [work[0]["id"]]
    if len(work) > 1:
        return None, "ambiguous", [p["id"] for p in work if p.get("id")]

    return None, "unmatched", []


async def match_user_by_agent(
    *,
    empemail: str = "",
    agent_phone: str = "",
    agent_name: str = "",
) -> Optional[dict]:
    """Primary: empemail → users.email. Fallback: mcube phone, then soft full_name."""
    email = (empemail or "").strip().lower()
    if email:
        user = await db.users.find_one(
            {"$expr": {"$eq": [{"$toLower": "$email"}, email]}},
            {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1, "mcube_number": 1},
        )
        if user:
            return user

    phone10 = normalize_phone(agent_phone or "")
    if phone10:
        user = await db.users.find_one(
            {"normalized_mcube_number": phone10},
            {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1, "mcube_number": 1},
        )
        if user:
            return user

    name = (agent_name or "").strip()
    if name:
        user = await db.users.find_one(
            {"full_name": {"$regex": f"^{_re_escape(name)}$", "$options": "i"}},
            {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1, "mcube_number": 1},
        )
        if user:
            return user
    return None


def _re_escape(s: str) -> str:
    import re

    return re.escape(s)


async def list_admin_users() -> List[dict]:
    return await db.users.find(
        {"role": {"$regex": r"^\s*admin\s*$", "$options": "i"}, "is_active": {"$ne": False}},
        {"_id": 0, "id": 1, "full_name": 1, "email": 1},
    ).to_list(50)
