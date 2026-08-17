"""Unit tests for RNR Admin reassign revert owner inference (no Mongo)."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from revert_rnr_admin_reassign import (  # noqa: E402
    infer_previous_owner_name,
    later_human_reassignment,
    owner_from_assigned_description,
)


def test_owner_from_assigned_description_variants():
    assert owner_from_assigned_description("Assigned to Anusha Omprakash (creator)") == "Anusha Omprakash"
    assert owner_from_assigned_description("Assignee changed: Raj → Priya") == "Priya"
    assert owner_from_assigned_description("Routed to Gowtham j (sla_1h_reroute)") == "Gowtham j"


def test_infer_previous_owner_uses_creator_when_no_assigned_event():
    stolen = datetime(2026, 8, 8, 11, 12, 17, tzinfo=timezone.utc)
    lead = {
        "context_updates": [
            {
                "type": "created",
                "timestamp_dt": stolen - timedelta(days=3),
                "actor_name": "Anusha Omprakash",
                "agent": "Anusha Omprakash",
            },
            {
                "type": "updated",
                "timestamp_dt": stolen - timedelta(days=2),
                "actor_name": "Anusha Omprakash",
            },
        ]
    }
    assert infer_previous_owner_name(lead, stolen) == "Anusha Omprakash"


def test_infer_previous_owner_prefers_last_assigned_before_steal():
    stolen = datetime(2026, 8, 8, 11, 12, 17, tzinfo=timezone.utc)
    lead = {
        "context_updates": [
            {
                "type": "created",
                "timestamp_dt": stolen - timedelta(days=5),
                "actor_name": "Admin",
            },
            {
                "type": "assigned",
                "timestamp_dt": stolen - timedelta(days=1),
                "description": "Assignee changed: Admin → Anusha Omprakash",
                "agent": "Admin",
            },
        ]
    }
    assert infer_previous_owner_name(lead, stolen) == "Anusha Omprakash"


def test_later_human_reassignment_detects_assignee_changed_after_steal():
    stolen = datetime(2026, 8, 8, 11, 12, 17, tzinfo=timezone.utc)
    events = [
        {
            "event_type": "assignee_changed",
            "created_at_dt": stolen + timedelta(hours=2),
        }
    ]
    assert later_human_reassignment(events, stolen) is True
    assert later_human_reassignment(
        [{"event_type": "assignee_changed", "created_at_dt": stolen - timedelta(hours=1)}],
        stolen,
    ) is False
