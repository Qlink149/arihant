"""Unit tests for the new Meta Ads dashboard endpoints (admin-only,
same convention as marketing.py)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from crm.api.v1.endpoints import meta_ads

ADMIN = {"id": "u1", "full_name": "Admin Ana", "role": "admin"}
REP = {"id": "u2", "full_name": "Rep Rita", "role": "rep"}


def _mock_db(metrics_rows=None, last_sync=None):
    mock_db = MagicMock()
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=metrics_rows or [])
    cursor.sort = MagicMock(return_value=cursor)
    mock_db.meta_ads_daily_metrics.find = MagicMock(return_value=cursor)
    mock_db.meta_ads_sync_logs.find_one = AsyncMock(return_value=last_sync)
    mock_db.cron_locks.find_one = AsyncMock(return_value=None)
    return mock_db


@pytest.mark.parametrize("handler_name,kwargs", [
    ("get_meta_ads_dashboard", {}),
    ("get_meta_ads_campaigns", {}),
    ("get_meta_ads_last_sync", {}),
])
def test_endpoints_reject_non_admin(monkeypatch, handler_name, kwargs):
    monkeypatch.setattr(meta_ads, "db", _mock_db())
    handler = getattr(meta_ads, handler_name)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(current_user=REP, **kwargs))
    assert exc.value.status_code == 403


def test_dashboard_groups_by_resolved_project(monkeypatch):
    rows = [
        {"resolved_project": "Anna Nagar - Mira", "spend": 100.0, "leads": 2, "impressions": 500, "clicks": 5, "level": "campaign"},
        {"resolved_project": "Anna Nagar - Mira", "spend": 50.0, "leads": 1, "impressions": 200, "clicks": 2, "level": "campaign"},
        {"resolved_project": None, "spend": 10.0, "leads": 0, "impressions": 100, "clicks": 0, "level": "campaign"},
    ]
    monkeypatch.setattr(meta_ads, "db", _mock_db(metrics_rows=rows))
    result = asyncio.run(meta_ads.get_meta_ads_dashboard(current_user=ADMIN))
    by_project = {p["project"]: p for p in result["by_project"]}
    assert by_project["Anna Nagar - Mira"]["total_spend"] == 150.0
    assert by_project["Anna Nagar - Mira"]["total_leads"] == 3
    assert by_project["Anna Nagar - Mira"]["cpl"] == 50.0
    assert "Unresolved" in by_project
    assert result["total_spend"] == 160.0


def test_last_sync_returns_latest_doc(monkeypatch):
    log = {"status": "ok", "started_at": "2026-10-06T00:00:00+00:00", "token_expiring_soon": False}
    monkeypatch.setattr(meta_ads, "db", _mock_db(last_sync=log))
    result = asyncio.run(meta_ads.get_meta_ads_last_sync(current_user=ADMIN))
    assert result == {**log, "running": False}


def test_last_sync_empty_when_never_run(monkeypatch):
    monkeypatch.setattr(meta_ads, "db", _mock_db(last_sync=None))
    result = asyncio.run(meta_ads.get_meta_ads_last_sync(current_user=ADMIN))
    assert result == {"running": False}
