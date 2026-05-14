"""
Regression tests for critical contract correctness:
- /api/auth/refresh must accept JSON body {refresh_token}
- /api/campaigns must honor lead_ids passed by frontend preview

These tests follow the existing pattern: they hit a running backend at REACT_APP_BACKEND_URL.
"""

import os
import uuid

import pytest
import requests


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://crm-sales-next.preview.emergentagent.com").rstrip("/")


@pytest.fixture(scope="module")
def tokens():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        data={"username": "roshini@arihant.com", "password": "arihant123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data and "refresh_token" in data
    return {"access_token": data["access_token"], "refresh_token": data["refresh_token"]}


@pytest.fixture(scope="module")
def authed_session(tokens):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tokens['access_token']}", "Content-Type": "application/json"})
    return s


def test_refresh_accepts_json_body(tokens):
    r = requests.post(
        f"{BASE_URL}/api/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    assert r.status_code == 200, f"Refresh failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data
    assert data.get("token_type") == "bearer"


def test_campaign_create_honors_lead_ids(authed_session):
    # Create two leads so we control lead_ids.
    lead_ids = []
    for i in range(2):
        phone = f"+9199{uuid.uuid4().int % 10_000_000_00:09d}"
        payload = {
            "first_name": f"Test{i}",
            "last_name": "CampaignAudience",
            "phone": phone,
            "email": f"test{i}.{uuid.uuid4().hex[:6]}@example.com",
            "project": "Reserve 16",
            "lead_status": "Open",
            "lead_source": "test",
        }
        r = authed_session.post(f"{BASE_URL}/api/leads", json=payload, timeout=30)
        assert r.status_code == 200, f"Lead create failed: {r.status_code} {r.text}"
        lead_ids.append(r.json()["id"])

    camp_payload = {
        "name": f"TEST_Campaign_{uuid.uuid4().hex[:8]}",
        "agent_type": "lead_nurturer",
        "agent_prompt": "test prompt",
        "filters": {"project": "Reserve 16"},
        "lead_ids": lead_ids,
    }
    r = authed_session.post(f"{BASE_URL}/api/campaigns", json=camp_payload, timeout=30)
    assert r.status_code == 200, f"Campaign create failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("lead_count") == 2
    assert isinstance(data.get("leads"), list) and len(data["leads"]) == 2
    returned_ids = sorted([l["id"] for l in data["leads"]])
    assert returned_ids == sorted(lead_ids)

