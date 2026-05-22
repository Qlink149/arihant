"""Offline unit test for auth refresh token handler."""
import asyncio
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import HTTPException

from crm.core.state import (
    ALGORITHM,
    SECRET_KEY,
    RefreshTokenRequest,
    create_refresh_token,
)
from crm.routers import auth as auth_router
from crm.routers.auth import refresh_token


def test_refresh_token_extracts_user_id_from_sub(monkeypatch):
    user_id = "test-user-uuid-123"
    token = create_refresh_token(data={"sub": user_id, "sid": "session-1"})

    users = AsyncMock()
    users.find_one = AsyncMock(
        return_value={
            "id": user_id,
            "email": "test@example.com",
            "current_session_id": "session-1",
        }
    )
    monkeypatch.setattr(auth_router.db, "users", users)

    result = asyncio.run(refresh_token(RefreshTokenRequest(refresh_token=token)))
    users.find_one.assert_awaited_once_with({"id": user_id}, {"_id": 0})
    assert "access_token" in result
    payload = jwt.decode(result["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
    assert payload.get("sub") == user_id


def test_refresh_token_rejects_missing_sub():
    token = jwt.encode(
        {"type": "refresh", "exp": 9999999999},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(refresh_token(RefreshTokenRequest(refresh_token=token)))
    assert exc.value.status_code == 401
