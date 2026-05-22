"""
Tests for lead text search on list endpoints.
"""
import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

TEST_EMAIL = "roshini@arihant.com"
TEST_PASSWORD = "arihant123"


@pytest.fixture(scope="module")
def api_client():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def auth_token(api_client):
    response = api_client.post(
        f"{BASE_URL}/api/auth/login",
        data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def authenticated_client(api_client, auth_token):
    api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
    return api_client


def _first_lead_name(client, url: str, params: dict | None = None) -> str | None:
    response = client.get(url, params=params or {"skip": 0, "limit": 1})
    if response.status_code != 200:
        return None
    data = response.json()
    if isinstance(data, list):
        leads = data
    else:
        leads = data.get("leads", [])
    if not leads:
        return None
    lead = leads[0]
    return lead.get("first_name") or lead.get("last_name")


class TestMyDashboardLeadSearch:
    def test_search_by_first_name(self, authenticated_client):
        name = _first_lead_name(
            authenticated_client, f"{BASE_URL}/api/my-dashboard/leads"
        )
        if not name or len(name) < 2:
            pytest.skip("No leads with searchable name on my dashboard")

        response = authenticated_client.get(
            f"{BASE_URL}/api/my-dashboard/leads",
            params={"skip": 0, "limit": 150, "search": name[:3]},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data.get("total", 0) >= 1, "Search should return at least one lead"
        assert len(data.get("leads", [])) >= 1

    def test_search_regex_metacharacters_safe(self, authenticated_client):
        response = authenticated_client.get(
            f"{BASE_URL}/api/my-dashboard/leads",
            params={"skip": 0, "limit": 10, "search": "(test"},
        )
        assert response.status_code == 200, response.text

    def test_search_with_temperature_filter(self, authenticated_client):
        response = authenticated_client.get(
            f"{BASE_URL}/api/my-dashboard/leads",
            params={"skip": 0, "limit": 10, "search": "a", "temperature": "Hot"},
        )
        assert response.status_code == 200, response.text
        for lead in response.json().get("leads", []):
            assert lead.get("temperature") == "Hot"


class TestLeadsEndpointSearch:
    def test_search_by_first_name(self, authenticated_client):
        name = _first_lead_name(authenticated_client, f"{BASE_URL}/api/leads")
        if not name or len(name) < 2:
            pytest.skip("No leads with searchable name")

        response = authenticated_client.get(
            f"{BASE_URL}/api/leads",
            params={"skip": 0, "limit": 50, "search": name[:3]},
        )
        assert response.status_code == 200, response.text
        assert len(response.json()) >= 1
        assert response.headers.get("X-Total-Count", "0") != "0"

    def test_search_regex_metacharacters_safe(self, authenticated_client):
        response = authenticated_client.get(
            f"{BASE_URL}/api/leads",
            params={"skip": 0, "limit": 10, "search": "(test"},
        )
        assert response.status_code == 200, response.text

    def test_search_with_budget_filter(self, authenticated_client):
        response = authenticated_client.get(
            f"{BASE_URL}/api/leads",
            params={
                "skip": 0,
                "limit": 10,
                "budget": "1-2 Cr",
                "search": "a",
            },
        )
        assert response.status_code == 200, response.text
