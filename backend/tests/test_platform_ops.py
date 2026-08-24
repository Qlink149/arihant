"""
Tests for platform operator ops endpoints (/api/ops/*).
"""
import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
TEST_EMAIL = "roshini@arihant.com"
TEST_PASSWORD = "arihant123"
OPS_EMAIL = os.environ.get("PLATFORM_OPERATOR_EMAIL", "yogansh@claraai.tech").split(",")[0].strip().lower()
OPS_PASSWORD = os.environ.get("SEED_DEFAULT_PASSWORD", "Arihant@2026")


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
    pytest.skip(f"Authentication failed: {response.status_code}")


@pytest.fixture(scope="module")
def authenticated_client(api_client, auth_token):
    api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
    return api_client


@pytest.fixture(scope="module")
def ops_token(api_client):
    response = api_client.post(
        f"{BASE_URL}/api/auth/login",
        data={"username": OPS_EMAIL, "password": OPS_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if response.status_code != 200:
        pytest.skip(f"Platform operator login failed ({OPS_EMAIL}): {response.status_code}")
    return response.json().get("access_token")


@pytest.fixture(scope="module")
def ops_client(api_client, ops_token):
    client = requests.Session()
    client.headers.update(
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ops_token}",
        }
    )
    return client


class TestPlatformOpsAccess:
    def test_ops_users_forbidden_for_regular_admin(self, authenticated_client):
        response = authenticated_client.get(f"{BASE_URL}/api/ops/users")
        assert response.status_code == 403, response.text

    def test_ops_impersonate_forbidden_for_regular_admin(self, authenticated_client):
        response = authenticated_client.post(
            f"{BASE_URL}/api/ops/impersonate",
            json={"user_id": "non-existent-id"},
        )
        assert response.status_code == 403, response.text

    def test_ops_users_requires_auth(self, api_client):
        session = requests.Session()
        response = session.get(f"{BASE_URL}/api/ops/users")
        assert response.status_code == 401


class TestPlatformOpsOperator:
    def test_auth_me_flags_platform_operator(self, ops_client):
        response = ops_client.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data.get("is_platform_operator") is True
        assert data.get("role") == "admin"

    def test_list_ops_users(self, ops_client):
        response = ops_client.get(f"{BASE_URL}/api/ops/users")
        assert response.status_code == 200, response.text
        users = response.json()
        assert isinstance(users, list)
        if users:
            u = users[0]
            assert "id" in u
            assert "email" in u
            assert "full_name" in u
            assert "role" in u
            assert "is_active" in u
            assert "hashed_password" not in u
        emails = [(u.get("email") or "").lower() for u in users]
        assert OPS_EMAIL not in emails

    def test_impersonate_returns_tokens(self, ops_client, authenticated_client):
        list_res = ops_client.get(f"{BASE_URL}/api/ops/users")
        if list_res.status_code != 200 or not list_res.json():
            pytest.skip("No users to impersonate")

        target = list_res.json()[0]
        response = ops_client.post(
            f"{BASE_URL}/api/ops/impersonate",
            json={"user_id": target["id"]},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data.get("user", {}).get("id") == target["id"]


class TestBlockedAssignee:
    def test_transfer_to_platform_operator_blocked(self, authenticated_client, ops_client):
        me = ops_client.get(f"{BASE_URL}/api/auth/me")
        assert me.status_code == 200
        operator_name = me.json().get("full_name")
        assert operator_name

        leads_res = authenticated_client.get(
            f"{BASE_URL}/api/my-dashboard/leads",
            params={"skip": 0, "limit": 1},
        )
        if leads_res.status_code != 200 or not leads_res.json().get("leads"):
            pytest.skip("No leads available for transfer test")

        lead_id = leads_res.json()["leads"][0]["id"]
        response = authenticated_client.post(
            f"{BASE_URL}/api/leads/transfer",
            json={
                "lead_id": lead_id,
                "to_rep": operator_name,
                "notes": "TEST_blocked_assignee",
            },
        )
        assert response.status_code == 400, response.text

    def test_transfer_to_platform_operator_email_blocked(self, authenticated_client, ops_client):
        leads_res = authenticated_client.get(
            f"{BASE_URL}/api/my-dashboard/leads",
            params={"skip": 0, "limit": 1},
        )
        if leads_res.status_code != 200 or not leads_res.json().get("leads"):
            pytest.skip("No leads available for transfer test")

        lead_id = leads_res.json()["leads"][0]["id"]
        response = authenticated_client.post(
            f"{BASE_URL}/api/leads/transfer",
            json={
                "lead_id": lead_id,
                "to_rep": OPS_EMAIL,
                "notes": "TEST_blocked_assignee_email",
            },
        )
        assert response.status_code == 400, response.text
