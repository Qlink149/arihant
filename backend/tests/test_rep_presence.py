"""Unit tests for rep presence helpers and ops rep-activity endpoint."""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
import requests

from crm.services.rep_presence import (
    compute_presence_status,
    routing_ineligible_reason,
    sla_pause_summary,
)
from crm.utils.business_time import is_on_duty_today, is_same_ist_day

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
TEST_EMAIL = "roshini@arihant.com"
TEST_PASSWORD = "arihant123"
IST = ZoneInfo("Asia/Kolkata")


def _utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def _ist(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=IST)


class TestDutyDayHelpers:
    def test_same_ist_day(self):
        # 2026-06-17 20:00 UTC = 2026-06-18 01:30 IST → different IST day from morning UTC
        morning_utc = _utc(2026, 6, 17, 4, 0)  # 09:30 IST same day
        assert is_same_ist_day(morning_utc, _utc(2026, 6, 17, 6, 0))

    def test_on_duty_today_from_last_login(self):
        now = _utc(2026, 6, 17, 10, 0)
        assert is_on_duty_today({"last_login_dt": now - timedelta(hours=2)}, now)
        assert not is_on_duty_today({"last_login_dt": now - timedelta(days=1)}, now)

    def test_on_duty_today_from_last_active(self):
        now = _utc(2026, 6, 17, 10, 0)
        assert is_on_duty_today({"last_active_dt": now}, now)
        assert not is_on_duty_today({}, now)


class TestComputePresenceStatus:
    def test_on_duty_today_is_online(self):
        now = _utc(2026, 6, 17, 10)
        assert compute_presence_status({"last_login_dt": now}, now) == "online"
        assert compute_presence_status({"last_active_dt": now - timedelta(hours=3)}, now) == "online"

    def test_manual_break_still_online_if_on_duty(self):
        """Manual break must NOT force offline for per-day presence."""
        now = _utc(2026, 6, 17, 10)
        assert (
            compute_presence_status(
                {"manual_status": "on_break", "last_login_dt": now},
                now,
            )
            == "online"
        )

    def test_yesterday_is_offline(self):
        now = _utc(2026, 6, 17, 10)
        yesterday = now - timedelta(days=1)
        assert compute_presence_status({"last_active_dt": yesterday}, now) == "offline"

    def test_no_activity_offline(self):
        now = _utc(2026, 6, 17, 10)
        assert compute_presence_status({}, now) == "offline"


class TestRoutingIneligibleReason:
    def test_account_inactive(self):
        now = _utc(2026, 6, 17, 10)
        reason = routing_ineligible_reason(
            {"is_active": False},
            {"last_login_dt": now},
            now_dt=now,
        )
        assert reason == "account_inactive"

    def test_manual_on_break_does_not_block(self):
        now = _utc(2026, 6, 17, 10, 30)
        with patch("crm.services.rep_presence.is_business_hours_ist", return_value=True):
            reason = routing_ineligible_reason(
                {"is_active": True},
                {"manual_status": "on_break", "last_login_dt": now},
                now_dt=now,
            )
        assert reason is None

    def test_not_on_duty_today(self):
        now = _utc(2026, 6, 17, 10)
        old = now - timedelta(days=1)
        with patch("crm.services.rep_presence.is_business_hours_ist", return_value=True):
            reason = routing_ineligible_reason(
                {"is_active": True},
                {"manual_status": "available", "last_active_dt": old},
                now_dt=now,
            )
        assert reason == "not_on_duty_today"

    def test_stale_heartbeat_same_day_still_eligible(self):
        """Closing laptop for hours must NOT pause SLA if they logged in today."""
        now = _utc(2026, 6, 17, 10)
        login = now - timedelta(hours=5)
        with patch("crm.services.rep_presence.is_business_hours_ist", return_value=True):
            reason = routing_ineligible_reason(
                {"is_active": True},
                {"last_login_dt": login, "last_active_dt": login},
                now_dt=now,
            )
        assert reason is None

    def test_outside_business_hours(self):
        now = _utc(2026, 6, 17, 2, 0)
        with patch("crm.services.rep_presence.is_business_hours_ist", return_value=False):
            reason = routing_ineligible_reason(
                {"is_active": True},
                {"last_login_dt": now},
                now_dt=now,
            )
        assert reason == "outside_business_hours"

    def test_eligible_returns_none(self):
        now = _utc(2026, 6, 17, 10, 30)
        with patch("crm.services.rep_presence.is_business_hours_ist", return_value=True):
            reason = routing_ineligible_reason(
                {"is_active": True},
                {"manual_status": "available", "last_login_dt": now},
                now_dt=now,
            )
        assert reason is None


class TestSlaPauseSummary:
    def test_not_on_duty_label(self):
        now = _utc(2026, 6, 17, 10, 30)
        with patch("crm.services.rep_presence.is_business_hours_ist", return_value=True):
            summary = sla_pause_summary(
                routing_eligible=False,
                reason="not_on_duty_today",
                now_dt=now,
            )
        assert summary["sla_paused"] is True
        assert summary["sla_pause_when"] == "not_on_duty_today"
        assert "duty" in summary["sla_pause_label"].lower()

    def test_active_shows_closes_hint(self):
        now = _utc(2026, 6, 17, 10, 30)
        with patch("crm.services.rep_presence.is_business_hours_ist", return_value=True), patch(
            "crm.services.rep_presence.business_closes_ist",
            return_value=_utc(2026, 6, 17, 12, 0),
        ):
            summary = sla_pause_summary(
                routing_eligible=True,
                reason=None,
                now_dt=now,
            )
        assert summary["sla_paused"] is False
        assert summary["sla_pause_when"] == "active"


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
