"""Tests for task list enrichment with lead context."""
from datetime import datetime, timezone

import pytest

from crm.services.task_enrichment import enrich_task_dict, sla_task_reason


def test_sla_task_reason_new_30m():
    reason = sla_task_reason({"sla_rule": "new", "sla_threshold": "30m", "source": "sla"})
    assert "30 minutes" in reason


def test_enrich_task_dict_from_lead():
    task = {
        "id": "t1",
        "lead_id": "l1",
        "description": "Reassign Lead",
        "source": "sla",
        "sla_rule": "new",
        "sla_threshold": "30m",
    }
    lead = {
        "id": "l1",
        "first_name": "Rajesh",
        "last_name": "Kumar",
        "project": "ECR Reserve 16",
        "context_updates": [
            {
                "type": "note",
                "description": "Customer asked for brochure.",
                "timestamp_dt": datetime(2026, 5, 28, 10, 0, tzinfo=timezone.utc),
            }
        ],
    }
    out = enrich_task_dict(task, lead)
    assert out["lead_name"] == "Rajesh Kumar"
    assert out["project"] == "ECR Reserve 16"
    assert out["task_reason"]
    assert "30 minutes" in out["task_reason"] or "brochure" in (out.get("latest_note") or "")
