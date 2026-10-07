"""Client tracker #21 / row 20: the WhatsApp "new lead acknowledgement" goes out
ONLY when a lead is created with status New - however it was created. Manual
leads created straight into another status (walk-in as Site Visit Scheduled /
Visit Completed, already-Contacted, ...) must not get it, and neither must an
existing lead that is merely moved back to New.

The only two code paths that send it are lead_service.create_lead and
lead_intake_service._create_new_lead (Webflow, Zapier/Meta, API-key website
intake, Channel Partner). These tests pin that, path by path.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crm.models.schemas.lead_schemas import LeadCreate, LeadUpdatePatch

TESTS = Path(__file__).parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TESTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mq = _load("test_meta_qualified_update_unit")  # create_lead / update_lead fixtures
_csv = _load("test_import_csv_unit")  # import_csv fixtures

USER = {"id": "u1", "full_name": "Tester"}


async def _create_lead_and_get_ack_mock(status):
    from crm.services.lead_service import create_lead

    db, _ = _mq._make_db({"id": "unused"})
    patches = _mq._patch_lead_service(db)
    mocks = _mq._enter_all(patches)
    ack = mocks[-1]  # patch("crm.services.whatsapp_service.send_lead_ack")
    try:
        payload = {"first_name": "Walk", "last_name": "In", "phone": "919999900123", "lead_source": "Direct Walk-in"}
        if status is not None:
            payload["lead_status"] = status
        await create_lead(LeadCreate(**payload), USER)
        await asyncio.sleep(0)  # the ack is fire-and-forget (asyncio.create_task)
        await asyncio.sleep(0)
    finally:
        _mq._stop_all(patches)
    return ack


# ---------------------------------------------------------------- UI create form
@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["New", "new", " New ", None])
async def test_create_form_new_status_sends_ack(status):
    ack = await _create_lead_and_get_ack_mock(status)
    ack.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    ["Site Visit Scheduled", "Visit Completed", "Contacted", "Interested", "Nurturing", "RNR", "Negotiation"],
)
async def test_create_form_any_other_status_does_not_send_ack(status):
    ack = await _create_lead_and_get_ack_mock(status)
    ack.assert_not_awaited()


# --------------------------------------- intake: website / Meta-Zapier / CP / API key
INTAKE_KEYS = {
    "website (API key)": {"id": "some-real-key", "project_name": "Mira", "project_id": "mira"},
    "Meta / Zapier": {"id": "zapier-meta:mira", "project_name": "Mira", "project_id": "mira"},
    "Webflow": {"id": "webflow:melange", "project_name": "Melange", "project_id": "melange"},
    "Channel Partner": {
        "id": "channel-partner:mira",
        "project_name": "Mira",
        "project_id": "mira",
        "channel_partner": "Propmart",
    },
}


async def _intake_create(api_key, *, spam=False):
    import crm.services.lead_intake_service as intake

    mock_db = MagicMock()
    mock_db.leads.insert_one = AsyncMock()
    ack = AsyncMock(return_value={"success": True})
    with patch.object(intake, "db", mock_db), patch(
        "crm.services.assignment_router.route_new_lead", new_callable=AsyncMock
    ), patch("crm.services.whatsapp_service.send_lead_ack", ack):
        await intake._create_new_lead(
            {
                "first_name": "Priya",
                "last_name": "S",
                "email": "p@example.com",
                "phone": "9876543210",
                "budget": None,
                "schedule_visit": None,
                "consent": True,
                "meta": {"via": "test"},
                "intake_spam": spam,
            },
            api_key=api_key,
            source="Website",
        )
    inserted = mock_db.leads.insert_one.await_args.args[0]
    return ack, inserted


@pytest.mark.asyncio
@pytest.mark.parametrize("path", list(INTAKE_KEYS))
async def test_every_intake_path_creates_new_and_sends_ack(path):
    ack, inserted = await _intake_create(INTAKE_KEYS[path])
    assert inserted["lead_status"] == "New"  # intake always creates as New
    ack.assert_awaited_once()


@pytest.mark.asyncio
async def test_intake_spam_honeypot_does_not_send_ack():
    ack, _ = await _intake_create(INTAKE_KEYS["website (API key)"], spam=True)
    ack.assert_not_awaited()


# ------------------------------------ paths that create leads but never send an ack
@pytest.mark.asyncio
async def test_csv_import_never_sends_ack_even_for_new_status():
    import crm.services.lead_service as lead_service

    db = _csv._DummyDB()
    ack = AsyncMock()
    from contextlib import ExitStack

    with ExitStack() as stack, patch("crm.services.whatsapp_service.send_lead_ack", ack):
        _csv._apply_patches(stack, db)
        result = await lead_service.import_csv(
            _csv._Upload("First name,Last Name,Mobile,Status\nCsv,Lead,8888888801,New"),
            {"id": "u1", "full_name": "Admin"},
        )
    assert result["imported"] == 1
    ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_whatsapp_inbound_unknown_lead_never_sends_ack(monkeypatch):
    from crm.services import whatsapp_service as wa

    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value=None)
    mock_db.leads.insert_one = AsyncMock()
    mock_db.users.find_one = AsyncMock(return_value={"id": "admin-1", "full_name": "Admin", "email": "a@x.com"})
    monkeypatch.setattr(wa, "db", mock_db)
    ack = AsyncMock()
    monkeypatch.setattr(wa, "send_lead_ack", ack)
    with patch.object(wa, "create_notification", AsyncMock()):
        lead = await wa.create_whatsapp_unknown_lead("9876543210", "Priya Sharma", notify=False)
    assert lead and lead["lead_status"] == "New"
    ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_mcube_inbound_unknown_lead_never_sends_ack():
    from crm.services.mcube_lead_intake import create_mcube_unknown_lead

    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value=None)
    mock_db.leads.insert_one = AsyncMock()
    ack = AsyncMock()
    admin = {"id": "admin-1", "full_name": "Admin", "email": "a@x.com"}
    with patch("crm.services.mcube_lead_intake.db", mock_db), patch(
        "crm.services.mcube_lead_intake.resolve_admin_wa_assignee", AsyncMock(return_value=admin)
    ), patch("crm.services.mcube_lead_intake.create_notification", AsyncMock()), patch(
        "crm.services.mcube_lead_intake.apply_nurture_temperature_rules"
    ), patch("crm.services.mcube_lead_intake.determine_lead_intent", return_value="medium"), patch(
        "crm.services.mcube_lead_intake.is_vip_lead", return_value=False
    ), patch("crm.services.whatsapp_service.send_lead_ack", ack):
        await create_mcube_unknown_lead("9916043625", call_id="c1", assignee=admin, notify=False)
    ack.assert_not_awaited()


# ------------------------------------------------------ moved back to New / re-enquiry
@pytest.mark.asyncio
@pytest.mark.parametrize("from_status", ["Contacted", "RNR", "Interested", "Gone Cold", "Site Visit Scheduled"])
async def test_existing_lead_moved_back_to_new_does_not_send_ack(from_status):
    """SOP 5.1 lets agents set New manually - that is not a new enquiry."""
    from crm.services.lead_service import update_lead

    db, leads = _mq._make_db(_mq._base_lead(status=from_status, source="Direct Walk-in"))
    patches = _mq._patch_lead_service(db)
    mocks = _mq._enter_all(patches)
    ack = mocks[-1]
    try:
        result = await update_lead("lead-mq", LeadUpdatePatch(lead_status="New"), USER)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    finally:
        _mq._stop_all(patches)
    assert leads._lead["lead_status"].lower() == "new"
    ack.assert_not_awaited()


def test_resubmission_merge_path_has_no_whatsapp_send():
    """A re-enquiry inside the dedupe window is merged by _update_existing_submission,
    which must never send the welcome again."""
    import crm.services.lead_intake_service as intake

    src = inspect.getsource(intake._update_existing_submission)
    assert "send_lead_ack" not in src and "whatsapp" not in src.lower()


def test_ack_sender_is_only_referenced_by_the_two_creation_functions():
    """Guard: if someone wires send_lead_ack into a status change, a rename,
    or an update path, this fails and forces a conscious decision."""
    import crm.services.lead_intake_service as intake
    import crm.services.lead_service as lead_service

    root = TESTS.parent / "crm"
    callers = set()
    for f in root.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        if "send_lead_ack(" in text and f.name != "whatsapp_service.py":
            callers.add(f.name)
    assert callers == {"lead_intake_service.py", "lead_service.py"}

    assert "send_lead_ack" in inspect.getsource(intake._create_new_lead)
    assert "send_lead_ack" in inspect.getsource(lead_service.create_lead)
    assert "send_lead_ack" not in inspect.getsource(lead_service.update_lead)
    assert "whatsapp" not in inspect.getsource(lead_service.update_lead).lower()
