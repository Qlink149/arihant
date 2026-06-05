import os

import pytest

from crm.core.secrets import validate_production_secrets


def test_validate_skips_in_test_environment(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("CRON_SECRET", raising=False)
    validate_production_secrets()


def test_validate_exits_on_weak_secret(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "short")
    monkeypatch.setenv("CRON_SECRET", "ci-cron-secret-16ch")
    with pytest.raises(SystemExit):
        validate_production_secrets()
