from typing import List

from fastapi import APIRouter, Depends

from crm.core.platform_ops import get_blocked_assignee_values
from crm.core.state import db, get_current_user


router = APIRouter()


@router.get("/users/assignees")
async def list_assignees(current_user: dict = Depends(get_current_user)) -> List[dict]:
    """
    List active users that can be assigned leads.

    This is safe for all authenticated users (used to populate 'Assign To' dropdowns).
    """
    _ = current_user
    blocked = await get_blocked_assignee_values()

    projection = {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1, "is_active": 1}
    users = await db.users.find({"is_active": {"$ne": False}}, projection).sort("full_name", 1).to_list(1000)

    result: List[dict] = []
    for u in users:
        email = (u.get("email") or "").strip().lower()
        name = (u.get("full_name") or "").strip().lower()
        if email in blocked or name in blocked:
            continue
        result.append(
            {
                "id": u.get("id"),
                "full_name": u.get("full_name"),
                "email": u.get("email"),
                "role": u.get("role") or "rep",
                "is_active": u.get("is_active", True),
            }
        )
    return result

