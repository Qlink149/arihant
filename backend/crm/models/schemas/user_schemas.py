from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr


class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    role: Literal["admin", "manager", "rep"] = "rep"


class UserRegister(BaseModel):
    """Public registration — role is always rep; not accepted from clients."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    password: str


class AdminUserCreate(BaseModel):
    """Admin-only user creation with explicit role."""

    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    password: str
    role: Literal["admin", "manager", "rep"] = "rep"


class UserCreate(UserRegister):
    """Backward-compatible alias for public registration."""

    pass


class UserResponse(UserBase):
    model_config = ConfigDict(extra="ignore")
    id: str
    is_active: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class RefreshTokenRequest(BaseModel):
    refresh_token: str
