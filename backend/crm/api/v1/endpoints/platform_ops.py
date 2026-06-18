import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from crm.core.platform_ops import get_platform_operator_email, require_platform_operator
from crm.core.state import (
    db,
    create_access_token,
    create_refresh_token,
    iso_utc_now,
    utc_now,
)
from crm.services.rep_presence import list_rep_presence_for_ops


router = APIRouter()


class ImpersonateRequest(BaseModel):
    user_id: str = Field(..., min_length=1)


@router.get("/ops/users")
async def list_ops_users(operator: dict = Depends(require_platform_operator)):
    operator_email = get_platform_operator_email()
    projection = {
        "_id": 0,
        "id": 1,
        "full_name": 1,
        "email": 1,
        "role": 1,
        "is_active": 1,
    }
    users = await db.users.find({}, projection).sort("full_name", 1).to_list(500)
    result = []
    for u in users:
        email = (u.get("email") or "").strip().lower()
        if email == operator_email:
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


@router.get("/ops/rep-activity")
async def list_rep_activity(operator: dict = Depends(require_platform_operator)):
    return await list_rep_presence_for_ops()


@router.post("/ops/impersonate")
async def impersonate_user(
    body: ImpersonateRequest,
    operator: dict = Depends(require_platform_operator),
):
    target = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if not target.get("is_active", True):
        raise HTTPException(status_code=400, detail="User is inactive")

    now_dt = utc_now()
    now_iso = iso_utc_now()
    audit_id = str(uuid.uuid4())

    await db.platform_impersonation_audit.insert_one(
        {
            "id": audit_id,
            "operator_email": operator.get("email"),
            "operator_id": operator.get("id"),
            "target_user_id": target.get("id"),
            "target_email": target.get("email"),
            "created_at": now_iso,
            "created_at_dt": now_dt,
        }
    )

    sid = str(uuid.uuid4())
    await db.users.update_one(
        {"id": target["id"]},
        {"$set": {"current_session_id": sid, "updated_at": now_iso, "updated_at_dt": now_dt}},
    )

    access_token = create_access_token(data={"sub": target["id"], "sid": sid})
    refresh_token = create_refresh_token(data={"sub": target["id"], "sid": sid})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": target["id"],
            "email": target["email"],
            "full_name": target.get("full_name"),
        },
    }
