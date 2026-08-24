import os
from datetime import datetime

import jwt
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm

from crm.core.rate_limit import limiter
from pydantic import BaseModel, Field

from crm.core.platform_ops import get_platform_operator_emails, is_platform_operator
from crm.models.schemas.user_schemas import AdminUserCreate, UserRegister
from crm.core.state import (
    db,
    SECRET_KEY,
    ALGORITHM,
    UserResponse,
    Token,
    RefreshTokenRequest,
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_time_greeting,
    utc_now,
    iso_utc_now,
)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


router = APIRouter()

_TRUTHY = frozenset({"1", "true", "yes"})


def public_registration_allowed() -> bool:
    """Public POST /auth/register is off unless explicitly enabled (not in production)."""
    if os.getenv("ENVIRONMENT", "").strip().lower() == "production":
        return False
    return os.getenv("ALLOW_PUBLIC_REGISTRATION", "").strip().lower() in _TRUTHY


async def _create_user_doc(
    *,
    email: str,
    full_name: str,
    phone: str | None,
    password: str,
    role: str,
) -> UserResponse:
    reserved = get_platform_operator_emails()
    if reserved and email.strip().lower() in reserved:
        raise HTTPException(status_code=403, detail="Registration not allowed for this email")

    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user_id = str(uuid.uuid4())
    now_dt = utc_now()
    now_iso = iso_utc_now()
    user_doc = {
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
    await db.users.insert_one(user_doc)
    return UserResponse(
        id=user_id,
        email=email,
        full_name=full_name,
        phone=phone,
        role=role,
        is_active=True,
        created_at=datetime.fromisoformat(user_doc["created_at"]),
        updated_at=now_dt,
    )


@router.post("/auth/register", response_model=UserResponse)
@limiter.limit("3/minute")
async def register(request: Request, user_data: UserRegister):
    if not public_registration_allowed():
        raise HTTPException(
            status_code=403,
            detail="Public registration is disabled. Contact an administrator.",
        )
    return await _create_user_doc(
        email=user_data.email,
        full_name=user_data.full_name,
        phone=user_data.phone,
        password=user_data.password,
        role="rep",
    )


@router.post("/auth/admin/create-user", response_model=UserResponse)
@limiter.limit("20/minute")
async def admin_create_user(
    request: Request,
    user_data: AdminUserCreate,
    current_user: dict = Depends(get_current_user),
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return await _create_user_doc(
        email=user_data.email,
        full_name=user_data.full_name,
        phone=user_data.phone,
        password=user_data.password,
        role=user_data.role,
    )


@router.post("/auth/login", response_model=Token)
@limiter.limit("10/minute")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    user = await db.users.find_one({"email": form_data.username}, {"_id": 0})
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    sid = str(uuid.uuid4())
    now_dt = utc_now()
    now_iso = iso_utc_now()
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"current_session_id": sid, "updated_at": now_iso, "updated_at_dt": now_dt}},
    )

    # Stamp duty-day presence so SLA routing treats them as on duty today (IST)
    await db.user_activity.update_one(
        {"user_id": user["id"]},
        {
            "$set": {
                "user_id": user["id"],
                "full_name": user.get("full_name") or "",
                "last_login": now_iso,
                "last_login_dt": now_dt,
                "last_active": now_iso,
                "last_active_dt": now_dt,
            }
        },
        upsert=True,
    )

    access_token = create_access_token(data={"sub": user["id"], "sid": sid})
    refresh_token = create_refresh_token(data={"sub": user["id"], "sid": sid})

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user={"id": user["id"], "email": user["email"], "full_name": user["full_name"]},
    )


@router.post("/auth/refresh")
async def refresh_token(req: RefreshTokenRequest):
    try:
        payload = jwt.decode(req.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        token_sid = payload.get("sid")
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        db_sid = user.get("current_session_id")
        if db_sid and token_sid != db_sid:
            raise HTTPException(status_code=401, detail="Session invalidated. Please log in again.")

        new_access_token = create_access_token(data={"sub": user_id, "sid": token_sid or db_sid})
        return {"access_token": new_access_token, "token_type": "bearer"}
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@router.put("/auth/password")
async def change_password(body: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    user = await db.users.find_one({"id": current_user["id"]}, {"_id": 0})
    if not user or not verify_password(body.current_password, user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    sid = str(uuid.uuid4())
    now_dt = utc_now()
    now_iso = iso_utc_now()
    await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {
                "hashed_password": hash_password(body.new_password),
                "current_session_id": sid,
                "updated_at": now_iso,
                "updated_at_dt": now_dt,
            }
        },
    )
    access_token = create_access_token(data={"sub": user["id"], "sid": sid})
    refresh_token = create_refresh_token(data={"sub": user["id"], "sid": sid})
    return {
        "message": "Password updated",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "full_name": current_user["full_name"],
        "role": current_user.get("role") or "rep",
        "is_platform_operator": is_platform_operator(current_user),
        "greeting": f"{get_time_greeting()}, {current_user['full_name'].split()[0]}",
    }

