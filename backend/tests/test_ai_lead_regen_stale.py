"""AI lead regen: WhatsApp/overview timeline types mark insights stale."""

from datetime import datetime, timedelta, timezone

from crm.services.ai_lead_regen import (
    ai_insights_stale,
    build_crm_hints,
    build_masked_transcript,
    latest_ai_signal_at,
    patch_touches_ai_overview,
)


def test_whatsapp_timeline_makes_ai_stale():
    now = datetime.now(timezone.utc)
    lead = {
        "ai_last_generated_at_dt": now - timedelta(hours=2),
        "context_updates": [
            {
                "type": "whatsapp",
                "timestamp": (now - timedelta(minutes=5)).isoformat(),
                "timestamp_dt": now - timedelta(minutes=5),
                "description": "Incoming WhatsApp: Get Brochure",
            }
        ],
    }
    assert latest_ai_signal_at(lead) is not None
    assert ai_insights_stale(lead) is True


def test_updated_overview_timeline_makes_ai_stale():
    now = datetime.now(timezone.utc)
    lead = {
        "ai_last_generated_at_dt": now - timedelta(hours=1),
        "context_updates": [
            {
                "type": "updated",
                "timestamp": now.isoformat(),
                "timestamp_dt": now,
                "description": "Updated budget",
            }
        ],
    }
    assert ai_insights_stale(lead) is True


def test_transcript_includes_whatsapp():
    lead = {
        "context_updates": [
            {
                "type": "whatsapp",
                "timestamp": "2026-07-20T12:00:00Z",
                "description": "Incoming WhatsApp: Thanks boss",
                "agent": "Customer",
            },
            {
                "type": "note",
                "timestamp": "2026-07-20T11:00:00Z",
                "description": "Called customer",
                "agent": "Rep",
            },
        ]
    }
    body = build_masked_transcript(lead)
    assert "whatsapp" in body
    assert "Thanks boss" in body
    assert "Called customer" in body


def test_crm_hints_include_overview_dna():
    hints = build_crm_hints(
        {
            "project": "OMR - Vivriti",
            "budget": "2-5 Cr",
            "location": "Abiramapuram",
            "lead_status": "New",
            "configuration": "3 BHK",
        }
    )
    assert "OMR - Vivriti" in hints
    assert "2-5 Cr" in hints
    assert "Abiramapuram" in hints
    assert "3 BHK" in hints


def test_patch_touches_ai_overview():
    assert patch_touches_ai_overview({"budget": "3 Cr"}) is True
    assert patch_touches_ai_overview({"next_action_date": "2026-07-21"}) is False
