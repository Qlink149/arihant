"""Unit tests for E2E safety rails (no Mongo required)."""
import os

import pytest

from scripts import e2e_cleanup as ec


def test_assert_safe_rejects_production(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("DB_NAME", "arihant_crm_e2e")
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(SystemExit, match="ENVIRONMENT"):
        ec.assert_safe_e2e_target()


def test_assert_safe_rejects_prod_db_name(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("DB_NAME", "arihant_crm")
    monkeypatch.setenv("ENVIRONMENT", "e2e")
    with pytest.raises(SystemExit, match="DB_NAME"):
        ec.assert_safe_e2e_target()


def test_assert_safe_rejects_live_api_host(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("DB_NAME", "arihant_crm_e2e")
    monkeypatch.setenv("ENVIRONMENT", "e2e")
    with pytest.raises(SystemExit, match="live host"):
        ec.assert_safe_e2e_target(api_base="https://arihant-api.claraai.tech")


def test_assert_safe_allows_e2e(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("DB_NAME", "arihant_crm_e2e")
    monkeypatch.setenv("ENVIRONMENT", "e2e")
    meta = ec.assert_safe_e2e_target(api_base="http://127.0.0.1:8000")
    assert meta["DB_NAME"] == "arihant_crm_e2e"
