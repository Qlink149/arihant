"""batch: Marketing dashboard RBAC. SOP v3.1 §3 says Admin-only; the audit
found these endpoints had no server-side check at all (AdminRoute is
frontend-only). Proves the fix: a non-admin gets 403 from every endpoint,
an admin passes through to the normal handler logic."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from crm.api.v1.endpoints import marketing


def _mock_db():
    mock_db = MagicMock()
    mock_db.marketing_spends.insert_one = AsyncMock()
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=[])
    cursor.sort = MagicMock(return_value=cursor)
    mock_db.marketing_spends.find = MagicMock(return_value=cursor)
    mock_db.marketing_spends.delete_one = AsyncMock()
    return mock_db


MANAGER = {"id": "u1", "full_name": "Manager Mike", "role": "manager"}
REP = {"id": "u2", "full_name": "Rep Rita", "role": "rep"}
ADMIN = {"id": "u3", "full_name": "Admin Ana", "role": "admin"}


def test_require_admin_rejects_non_admin():
    for user in (MANAGER, REP, {"role": None}, {}):
        with pytest.raises(HTTPException) as exc:
            marketing._require_admin(user)
        assert exc.value.status_code == 403


def test_require_admin_allows_admin():
    marketing._require_admin(ADMIN)  # must not raise


@pytest.mark.parametrize("handler_name,kwargs", [
    ("add_marketing_spend", {"entry": marketing.MarketingSpendEntry(project="X", channel="Y", amount=1, period="2026-Q1")}),
    ("get_marketing_spends", {}),
    ("get_marketing_dashboard", {}),
    ("delete_marketing_spend", {"spend_id": "s1"}),
])
def test_endpoint_rejects_non_admin(monkeypatch, handler_name, kwargs):
    monkeypatch.setattr(marketing, "db", _mock_db())
    handler = getattr(marketing, handler_name)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(current_user=REP, **kwargs))
    assert exc.value.status_code == 403


def test_get_marketing_dashboard_allows_admin(monkeypatch):
    monkeypatch.setattr(marketing, "db", _mock_db())
    result = asyncio.run(marketing.get_marketing_dashboard(current_user=ADMIN))
    assert result["total_spend"] == 0


def test_delete_marketing_spend_allows_admin(monkeypatch):
    mock_db = _mock_db()
    monkeypatch.setattr(marketing, "db", mock_db)
    result = asyncio.run(marketing.delete_marketing_spend(spend_id="s1", current_user=ADMIN))
    assert result == {"message": "Spend entry deleted"}
    mock_db.marketing_spends.delete_one.assert_awaited_once_with({"id": "s1"})
