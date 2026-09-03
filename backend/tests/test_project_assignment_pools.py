"""Project-pool routing, hop order, agent-activity gate, and New 1h SLA."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from crm.services.lead_sla_utils import has_agent_activity_since
from crm.services.project_assignment_pools import (
    ANANTHRAMAN_EMAIL,
    ANUSHA_EMAIL,
    DEFAULT_POOL_KEY,
    GOWTHAM_EMAIL,
    HARISH_EMAIL,
    JIGAR_EMAIL,
    MALATHY_EMAIL,
    NARENDRAN_EMAIL,
    ROSHNI_EMAIL,
    SHARIFF_EMAIL,
    get_pool,
    next_hop_emails,
    pool_escalates,
    pool_key_for_lead,
)
from crm.services.sla_engine import SLAEngineService


SINCE = datetime(2026, 8, 25, 5, 0, tzinfo=timezone.utc)
LATER = SINCE + timedelta(minutes=10)


def test_pool_key_known_projects():
    assert pool_key_for_lead({"project_id": "reserve-16"}) == "reserve-16"
    assert pool_key_for_lead({"project_id": "krsna"}) == "krsna"
    assert pool_key_for_lead({"project": "Abhiramapuram - Krishna"}) == "krsna"
    assert pool_key_for_lead({"project_id": "mira"}) == "mira"
    assert pool_key_for_lead({"project_id": "vivriti"}) == "vivriti"
    assert pool_key_for_lead({"project_id": "melange"}) == "melange"
    assert pool_key_for_lead({"project_id": "vipassana"}) == "vipassana"
    assert pool_key_for_lead({"project": "Srinagar Colony - Vipassana"}) == "vipassana"


def test_pool_key_empty_and_unknown_use_default():
    assert pool_key_for_lead({}) == DEFAULT_POOL_KEY
    assert pool_key_for_lead({"project": ""}) == DEFAULT_POOL_KEY
    assert pool_key_for_lead({"project_id": "guindy"}) == DEFAULT_POOL_KEY
    assert pool_key_for_lead({"project_id": "chamiers-road"}) == DEFAULT_POOL_KEY


def test_melange_and_vipassana_do_not_escalate():
    assert pool_escalates("melange") is False
    assert pool_escalates("vipassana") is False
    assert pool_escalates("reserve-16") is True
    assert pool_escalates(DEFAULT_POOL_KEY) is True


def test_reserve_16_fallback_order_excludes_current_owner():
    pool = get_pool("reserve-16")
    remaining = next_hop_emails(pool, [ANUSHA_EMAIL], initial=False)
    assert remaining[0] == GOWTHAM_EMAIL
    assert remaining[1:] == [NARENDRAN_EMAIL, MALATHY_EMAIL, JIGAR_EMAIL, ANANTHRAMAN_EMAIL]


def test_reserve_16_chain_after_both_primaries():
    pool = get_pool("reserve-16")
    remaining = next_hop_emails(pool, [ANUSHA_EMAIL, GOWTHAM_EMAIL], initial=False)
    assert remaining == [NARENDRAN_EMAIL, MALATHY_EMAIL, JIGAR_EMAIL, ANANTHRAMAN_EMAIL]


def test_krsna_mira_other_primary_then_stop():
    krsna = get_pool("krsna")
    assert next_hop_emails(krsna, [HARISH_EMAIL], initial=False) == [MALATHY_EMAIL]
    assert next_hop_emails(krsna, [HARISH_EMAIL, MALATHY_EMAIL], initial=False) == []

    mira = get_pool("mira")
    assert next_hop_emails(mira, [SHARIFF_EMAIL], initial=False) == [HARISH_EMAIL]
    assert next_hop_emails(mira, [SHARIFF_EMAIL, HARISH_EMAIL], initial=False) == []


def test_vivriti_fallback_is_narendran_malathy():
    pool = get_pool("vivriti")
    assert next_hop_emails(pool, [], initial=True) == [ANUSHA_EMAIL]
    assert next_hop_emails(pool, [ANUSHA_EMAIL], initial=False) == [NARENDRAN_EMAIL, MALATHY_EMAIL]


def test_default_pool_other_primary_only():
    pool = get_pool(DEFAULT_POOL_KEY)
    assert next_hop_emails(pool, [ANUSHA_EMAIL], initial=False) == [GOWTHAM_EMAIL]
    assert next_hop_emails(pool, [ANUSHA_EMAIL, GOWTHAM_EMAIL], initial=False) == []


def _lead_with_updates(*entries, assigned_user_id="u-anusha", assigned_to="Anusha Omprakash"):
    return {
        "assigned_user_id": assigned_user_id,
        "assigned_to": assigned_to,
        "context_updates": list(entries),
    }


def test_activity_counts_note_call_status_outcome():
    note = {
        "type": "note",
        "update_type": "general_note",
        "timestamp_dt": LATER,
        "actor_user_id": "u-anusha",
        "agent": "Anusha Omprakash",
    }
    call = {
        "type": "call",
        "timestamp_dt": LATER,
        "actor_user_id": "u-anusha",
        "agent": "Anusha Omprakash",
    }
    status = {
        "type": "updated",
        "timestamp_dt": LATER,
        "actor_user_id": "u-anusha",
        "agent": "Anusha Omprakash",
        "changes": [{"field": "lead_status", "from": "New", "to": "Contacted"}],
    }
    outcome = {
        "type": "updated",
        "timestamp_dt": LATER,
        "actor_user_id": "u-anusha",
        "agent": "Anusha Omprakash",
        "changes": [{"field": "logged_outcome", "from": None, "to": "Interested"}],
    }
    assert has_agent_activity_since(_lead_with_updates(note), SINCE)
    assert has_agent_activity_since(_lead_with_updates(call), SINCE)
    assert has_agent_activity_since(_lead_with_updates(status), SINCE)
    assert has_agent_activity_since(_lead_with_updates(outcome), SINCE)


def test_activity_ignores_system_whatsapp_assign_and_other_agent():
    ack = {
        "type": "whatsapp",
        "timestamp_dt": LATER,
        "actor_user_id": "system",
        "agent": "System Auto-Ack",
    }
    assigned = {
        "type": "assigned",
        "timestamp_dt": LATER,
        "agent": "System",
    }
    other = {
        "type": "note",
        "timestamp_dt": LATER,
        "actor_user_id": "u-harish",
        "agent": "Harish Marlecha",
    }
    lead = _lead_with_updates(ack, assigned, other)
    assert has_agent_activity_since(lead, SINCE) is False


# ── Router (mocked Mongo) ───────────────────────────────────────────────────

ANUSHA = {
    "id": "u-anusha",
    "email": ANUSHA_EMAIL,
    "full_name": "Anusha Omprakash",
    "role": "rep",
    "is_active": True,
}
GOWTHAM = {
    "id": "u-gowtham",
    "email": GOWTHAM_EMAIL,
    "full_name": "Gowtham j",
    "role": "rep",
    "is_active": True,
}
ROSHNI = {
    "id": "u-roshni",
    "email": ROSHNI_EMAIL,
    "full_name": "Roshini",
    "role": "admin",
    "is_active": True,
}
HARISH = {
    "id": "u-harish",
    "email": HARISH_EMAIL,
    "full_name": "Harish Marlecha",
    "role": "admin",
    "is_active": True,
}
MALATHY = {
    "id": "u-malathy",
    "email": MALATHY_EMAIL,
    "full_name": "Malathy",
    "role": "rep",
    "is_active": True,
}
JIGAR = {
    "id": "u-jigar",
    "email": JIGAR_EMAIL,
    "full_name": "jigar",
    "role": "rep",
    "is_active": True,
}
NARENDRAN = {
    "id": "u-narendran",
    "email": NARENDRAN_EMAIL,
    "full_name": "Narendran S",
    "role": "rep",
    "is_active": True,
}
ANANTHARAMAN = {
    "id": "u-anantharaman",
    "email": ANANTHRAMAN_EMAIL,
    "full_name": "Anantharaman",
    "role": "rep",
    "is_active": True,
}


def _users_by_email(*users):
    return {u["email"]: u for u in users}


def _mock_router_db(lead):
    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value=dict(lead))
    mock_db.leads.update_one = AsyncMock()
    mock_db.tasks.update_many = AsyncMock()
    return mock_db


def test_route_melange_assigns_roshni_only():
    asyncio.run(_route_melange_assigns_roshni_only())


async def _route_melange_assigns_roshni_only():
    from crm.services import assignment_router as router

    lead = {"id": "L1", "project_id": "melange", "lead_status": "New"}
    mock_db = _mock_router_db(lead)
    with patch.object(router, "db", mock_db):
        with patch.object(
            router, "resolve_users_by_emails", AsyncMock(return_value=_users_by_email(ROSHNI, ANUSHA))
        ):
            with patch.object(router, "is_pool_member_eligible", AsyncMock(return_value=True)):
                with patch.object(router, "create_notification", new_callable=AsyncMock):
                    result = await router.route_new_lead("L1")
    assert result["assigned_user_id"] == "u-roshni"
    assert result["pool_key"] == "melange"
    set_fields = mock_db.leads.update_one.call_args[0][1]["$set"]
    assert set_fields["pool_routing"] is True
    assert set_fields["assigned_user_id"] == "u-roshni"
    assert "assigned_at_dt" in set_fields


def test_route_empty_project_rr_picks_fewer_new():
    asyncio.run(_route_empty_project_rr_picks_fewer_new())


async def _route_empty_project_rr_picks_fewer_new():
    from crm.services import assignment_router as router

    lead = {"id": "L2", "lead_status": "New"}
    mock_db = _mock_router_db(lead)

    async def _counts(user_id, full_name):
        return {"u-anusha": 3, "u-gowtham": 1}[user_id]

    with patch.object(router, "db", mock_db):
        with patch.object(
            router,
            "resolve_users_by_emails",
            AsyncMock(return_value=_users_by_email(ANUSHA, GOWTHAM)),
        ):
            with patch.object(router, "is_pool_member_eligible", AsyncMock(return_value=True)):
                with patch.object(router, "count_open_new_leads", side_effect=_counts):
                    with patch.object(router, "create_notification", new_callable=AsyncMock):
                        result = await router.route_new_lead("L2")
    assert result["assigned_user_id"] == "u-gowtham"
    assert result["pool_key"] == DEFAULT_POOL_KEY


def test_harish_admin_eligible_without_rep_duty():
    asyncio.run(_harish_admin_eligible_without_rep_duty())


async def _harish_admin_eligible_without_rep_duty():
    from crm.services import assignment_router as router

    with patch.object(router, "is_active_for_routing", AsyncMock(return_value=False)):
        with patch("crm.core.platform_ops.is_blocked_assignee", AsyncMock(return_value=False)):
            assert await router.is_pool_member_eligible(HARISH) is True
            assert await router.is_pool_member_eligible(MALATHY) is False


def test_reassign_reserve16_hops_to_other_primary():
    asyncio.run(_reassign_reserve16_hops_to_other_primary())


async def _reassign_reserve16_hops_to_other_primary():
    from crm.services import assignment_router as router

    lead = {
        "id": "L3",
        "project_id": "reserve-16",
        "pool_key": "reserve-16",
        "pool_routing": True,
        "assigned_user_id": "u-anusha",
        "pool_assignment_history": ["u-anusha"],
        "lead_status": "New",
    }
    mock_db = _mock_router_db(lead)
    with patch.object(router, "db", mock_db):
        with patch.object(
            router,
            "resolve_users_by_emails",
            AsyncMock(return_value=_users_by_email(ANUSHA, GOWTHAM, NARENDRAN, MALATHY, JIGAR)),
        ):
            with patch.object(router, "is_pool_member_eligible", AsyncMock(return_value=True)):
                with patch.object(router, "count_open_new_leads", AsyncMock(return_value=0)):
                    with patch.object(router, "create_notification", new_callable=AsyncMock):
                        with patch.object(router, "log_lead_event", new_callable=AsyncMock):
                            result = await router.reassign_new_lead_in_pool("L3")
    assert result["ok"] is True
    assert result["assigned_user_id"] == "u-gowtham"


def test_reassign_reserve16_last_hop_is_anantharaman():
    asyncio.run(_reassign_reserve16_last_hop_is_anantharaman())


async def _reassign_reserve16_last_hop_is_anantharaman():
    from crm.services import assignment_router as router

    lead = {
        "id": "L4",
        "pool_key": "reserve-16",
        "pool_routing": True,
        "assigned_user_id": "u-jigar",
        "pool_assignment_history": [
            "u-anusha",
            "u-gowtham",
            "u-narendran",
            "u-malathy",
            "u-jigar",
        ],
        "lead_status": "New",
    }
    mock_db = _mock_router_db(lead)
    users = _users_by_email(ANUSHA, GOWTHAM, NARENDRAN, MALATHY, JIGAR, ANANTHARAMAN)
    with patch.object(router, "db", mock_db):
        with patch.object(router, "resolve_users_by_emails", AsyncMock(return_value=users)):
            with patch.object(router, "is_pool_member_eligible", AsyncMock(return_value=True)):
                with patch.object(router, "count_open_new_leads", AsyncMock(return_value=0)):
                    with patch.object(router, "create_notification", new_callable=AsyncMock):
                        with patch.object(router, "log_lead_event", new_callable=AsyncMock):
                            result = await router.reassign_new_lead_in_pool("L4")
    assert result["ok"] is True
    assert result["assigned_user_id"] == "u-anantharaman"


def test_reassign_reserve16_exhausts_after_anantharaman():
    asyncio.run(_reassign_reserve16_exhausts_after_anantharaman())


async def _reassign_reserve16_exhausts_after_anantharaman():
    from crm.services import assignment_router as router

    lead = {
        "id": "L4b",
        "pool_key": "reserve-16",
        "pool_routing": True,
        "assigned_user_id": "u-anantharaman",
        "pool_assignment_history": [
            "u-anusha",
            "u-gowtham",
            "u-narendran",
            "u-malathy",
            "u-jigar",
            "u-anantharaman",
        ],
        "lead_status": "New",
    }
    mock_db = _mock_router_db(lead)
    users = _users_by_email(ANUSHA, GOWTHAM, NARENDRAN, MALATHY, JIGAR, ANANTHARAMAN)
    with patch.object(router, "db", mock_db):
        with patch.object(router, "resolve_users_by_emails", AsyncMock(return_value=users)):
            with patch.object(router, "is_pool_member_eligible", AsyncMock(return_value=True)):
                result = await router.reassign_new_lead_in_pool("L4b")
    assert result["exhausted"] is True
    assert result["ok"] is False
    mock_db.leads.update_one.assert_not_called()


def test_reassign_melange_does_not_move():
    asyncio.run(_reassign_melange_does_not_move())


async def _reassign_melange_does_not_move():
    from crm.services import assignment_router as router

    lead = {
        "id": "L5",
        "pool_key": "melange",
        "pool_routing": True,
        "assigned_user_id": "u-roshni",
        "lead_status": "New",
    }
    mock_db = _mock_router_db(lead)
    with patch.object(router, "db", mock_db):
        result = await router.reassign_new_lead_in_pool("L5")
    assert result["exhausted"] is True
    assert result["reason"] == "no_escalate"
    mock_db.leads.update_one.assert_not_called()


def test_sla_new_skips_manual_and_activity_and_reassigns_pool():
    asyncio.run(_sla_new_skips_manual_and_activity_and_reassigns_pool())


async def _sla_new_skips_manual_and_activity_and_reassigns_pool():
    engine = SLAEngineService()
    assigned_at = datetime(2026, 8, 25, 4, 30, tzinfo=timezone.utc)
    now_dt = datetime(2026, 8, 25, 6, 0, tzinfo=timezone.utc)
    pool_lead = {
        "id": "pool-1",
        "pool_routing": True,
        "pool_key": "reserve-16",
        "assigned_at_dt": assigned_at,
        "lead_status": "New",
        "context_updates": [],
    }
    activity_lead = {
        "id": "pool-2",
        "pool_routing": True,
        "pool_key": "reserve-16",
        "assigned_at_dt": assigned_at,
        "assigned_user_id": "u-anusha",
        "assigned_to": "Anusha Omprakash",
        "lead_status": "New",
        "context_updates": [
            {
                "type": "note",
                "timestamp_dt": assigned_at + timedelta(minutes=5),
                "actor_user_id": "u-anusha",
                "agent": "Anusha Omprakash",
            }
        ],
    }
    melange_lead = {
        "id": "mel-1",
        "pool_routing": True,
        "pool_key": "melange",
        "assigned_at_dt": assigned_at,
        "lead_status": "New",
        "context_updates": [],
    }

    async def fake_paginate(coll, query, **kwargs):
        if "pool_routing" in str(query):
            yield [pool_lead, activity_lead, melange_lead]
        else:
            yield []

    reassign = AsyncMock(return_value={"ok": True, "assigned_user_id": "u-gowtham"})

    with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
        with patch("crm.services.sla_engine.business_seconds_elapsed", return_value=3600):
            with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
                with patch("crm.services.sla_engine.reassign_new_lead_in_pool", reassign):
                    await engine._process_rule_new(now_dt, now_dt.isoformat(), {})

    assert reassign.call_count == 1
    reassign.assert_awaited_once_with("pool-1")
    flag_paths = [op._doc["$set"] for op in engine._lead_ops]
    assert any("sla_flags.new.last_pool_reassign_at_dt" in doc for doc in flag_paths)


def test_sla_new_marks_exhausted_chain():
    asyncio.run(_sla_new_marks_exhausted_chain())


async def _sla_new_marks_exhausted_chain():
    engine = SLAEngineService()
    now_dt = datetime(2026, 8, 25, 6, 0, tzinfo=timezone.utc)
    lead = {
        "id": "pool-x",
        "pool_routing": True,
        "pool_key": "mira",
        "assigned_at_dt": now_dt - timedelta(hours=2),
        "lead_status": "New",
        "context_updates": [],
    }

    async def fake_paginate(coll, query, **kwargs):
        if "pool_routing" in str(query):
            yield [lead]
        else:
            yield []

    with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
        with patch("crm.services.sla_engine.business_seconds_elapsed", return_value=3600):
            with patch("crm.services.sla_engine._paginate_leads", fake_paginate):
                with patch(
                    "crm.services.sla_engine.reassign_new_lead_in_pool",
                    AsyncMock(return_value={"ok": False, "exhausted": True}),
                ):
                    await engine._process_rule_new(now_dt, now_dt.isoformat(), {})

    assert any(
        "sla_flags.new.pool_chain_exhausted_at_dt" in op._doc["$set"] for op in engine._lead_ops
    )
