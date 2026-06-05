"""Public registration gate — disabled unless ALLOW_PUBLIC_REGISTRATION is set."""

import pytest
from fastapi.testclient import TestClient

from crm.api.v1.endpoints.auth import public_registration_allowed
from crm.main import app


def test_public_registration_allowed_default_off(monkeypatch):
    monkeypatch.delenv("ALLOW_PUBLIC_REGISTRATION", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert public_registration_allowed() is False


def test_public_registration_allowed_when_flag_true(monkeypatch):
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "true")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert public_registration_allowed() is True


def test_public_registration_blocked_in_production_even_with_flag(monkeypatch):
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert public_registration_allowed() is False


def test_register_endpoint_returns_403_when_disabled(monkeypatch):
    monkeypatch.delenv("ALLOW_PUBLIC_REGISTRATION", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "test")

    client = TestClient(app)
    response = client.post(
        "/api/auth/register",
        json={
            "email": "newrep@example.com",
            "password": "password123",
            "full_name": "New Rep",
        },
    )
    assert response.status_code == 403
    assert "disabled" in response.json().get("detail", "").lower()
