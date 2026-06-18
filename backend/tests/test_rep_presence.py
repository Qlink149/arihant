"""Unit tests for rep presence helpers and ops rep-activity endpoint."""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import requests

from crm.services.rep_presence import (
    compute_presence_status,
    routing_ineligible_reason,
)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
TEST_EMAIL = "roshini@arihant.com"
TEST_PASSWORD = "arihant123"


def _utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


class TestComputePresenceStatus:
    def test_manual_away_is_offline(self):
        now = _utc(2026, 6, 17, 10)
        assert compute_presence_status({"manual_status": "away"}, now) == "offline"
        assert compute_presence_status({"manual_status": "on_break"}, now) == "offline"

    def test_manual_available_is_online(self):
        now = _utc(2026, 6, 17, 10)
        assert compute_presence_status({"manual_status": "available"}, now) == "online"

    def test_recent_heartbeat_online(self):
        now = _utc(2026, 6, 17, 10, 0)
        last = now - timedelta(minutes=10)
        assert compute_presence_status({"last_active_dt": last}, now) == "online"

    def test_stale_heartbeat_idle(self):
        now = _utc(2026, 6, 17, 10, 0)
        last = now - timedelta(minutes=45)
        assert compute_presence_status({"last_active_dt": last}, now) == "idle"

    def test_old_heartbeat_offline(self):
        now = _utc(2026, 6, 17, 10, 0)
        last = now - timedelta(minutes=90)
        assert compute_presence_status({"last_active_dt": last}, now) == "offline"

    def test_no_activity_offline(self):
        now = _utc(2026, 6, 17, 10)
        assert compute_presence_status({}, now) == "offline"


class TestRoutingIneligibleReason:
    def test_account_inactive(self):
        now = _utc(2026, 6, 17, 10)
        reason = routing_ineligible_reason(
            {"is_active": False},
            {"manual_status": "available", "last_active_dt": now},
            now_dt=now,
        )
        assert reason == "account_inactive"

    def test_manual_on_break(self):
        now = _utc(2026, 6, 17, 10, 30)
        reason = routing_ineligible_reason(
            {"is_active": True},
            {"manual_status": "on_break", "last_active_dt": now},
            now_dt=now,
        )
        assert reason == "manual_on_break"

    def test_no_recent_heartbeat(self):
        now = _utc(2026, 6, 17, 10)
        old = now - timedelta(hours=2)
        reason = routing_ineligible_reason(
            {"is_active": True},
            {"manual_status": "available", "last_active_dt": old},
            now_dt=now,
        )
        assert reason == "no_recent_heartbeat"

    def test_outside_business_hours(self):
        now = _utc(2026, 6, 17, 2, 0)
        with patch("crm.services.rep_presence.is_business_hours_ist", return_value=False):
            reason = routing_ineligible_reason(
                {"is_active": True},
                {"manual_status": "available", "last_active_dt": now},
                now_dt=now,
            )
        assert reason == "outside_business_hours"

    def test_eligible_returns_none(self):
        now = _utc(2026, 6, 17, 10, 30)
        with patch("crm.services.rep_presence.is_business_hours_ist", return_value=True):
            reason = routing_ineligible_reason(
                {"is_active": True},
                {"manual_status": "available", "last_active_dt": now},
                now_dt=now,
            )
        assert reason is None


@pytest.fixture(scope="module")
def api_client():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def auth_token(api_client):
    if not BASE_URL:
        pytest.skip("REACT_APP_BACKEND_URL not set")
    try:
        response = api_client.post(
            f"{BASE_URL}/api/auth/login",
            data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except requests.RequestException as exc:
        pytest.skip(f"Backend unavailable: {exc}")
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Authentication failed: {response.status_code}")


@pytest.fixture(scope="module")
def authenticated_client(api_client, auth_token):
    api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
    return api_client


class TestRepActivityEndpoint:
    def test_rep_activity_forbidden_for_regular_admin(self, authenticated_client):
        if not BASE_URL:
            pytest.skip("REACT_APP_BACKEND_URL not set")
        response = authenticated_client.get(f"{BASE_URL}/api/ops/rep-activity")
        assert response.status_code == 403, response.text
