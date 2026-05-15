from datetime import datetime

import jwt
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from app_state import (
    db,
    SECRET_KEY,
    ALGORITHM,
    UserCreate,
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


@router.post("/auth/register", response_model=UserResponse)
async def register(user_data: UserCreate):
    existing = await db.users.find_one({"email": user_data.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user_id = str(uuid.uuid4())
    now_dt = utc_now()
    now_iso = iso_utc_now()
    user_doc = {
        "id": user_id,
        "email": user_data.email,
        "full_name": user_data.full_name,
        "phone": user_data.phone,
        "role": user_data.role,
        "hashed_password": hash_password(user_data.password),
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
        email=user_data.email,
        full_name=user_data.full_name,
        phone=user_data.phone,
        role=user_data.role,
        is_active=True,
        created_at=datetime.fromisoformat(user_doc["created_at"]),
        updated_at=now_dt,
    )


@router.post("/auth/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
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
        "greeting": f"{get_time_greeting()}, {current_user['full_name'].split()[0]}",
    }

