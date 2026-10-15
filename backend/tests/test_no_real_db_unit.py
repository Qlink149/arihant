"""Regression: unit tests must never reach a real database (see tests/conftest.py)."""

from __future__ import annotations

import os

import pytest


def test_the_database_url_is_the_unreachable_test_one():
    assert os.environ["MONGO_URL"].startswith("mongodb://127.0.0.1:1")
    assert os.environ["DB_NAME"] == "arihant_crm_unit_tests_no_db"


def test_the_state_client_is_not_pointed_at_a_real_cluster():
    from crm.core.state import db

    assert db.name == "arihant_crm_unit_tests_no_db"
    assert "mongodb.net" not in os.environ["MONGO_URL"]


@pytest.mark.asyncio
async def test_a_stray_alert_cannot_write_to_a_real_database():
    """The leak: an alert helper used its own `db` while the test only mocked another module's."""
    from crm.services.intake_alerts import alert_admins_unrecognised_form

    await alert_admins_unrecognised_form("Website", "Unknown Enquiry Form")  # must not raise or hang


@pytest.mark.asyncio
async def test_a_stray_visit_log_write_cannot_reach_a_real_database():
    from datetime import datetime, timezone

    from crm.services.site_visit_events import record_site_visit_event

    # never raises (best-effort logging) and, with no reachable DB, writes nothing anywhere
    await record_site_visit_event(
        "lead-x", {"first_name": "Walk", "project": "ECR - Reserve 16"}, actor={"id": "u", "full_name": "Tester"},
        completed_at_dt=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
