"""Unit tests for Zapier Meta Instant Form webhook helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.services import zapier_leads_service as zls


def test_verify_webhook_secret(monkeypatch):
    monkeypatch.setattr(zls, "ZAPIER_WEBHOOK_SECRET", "zap-secret")
    assert zls.verify_webhook_secret(token="zap-secret") is True
    assert zls.verify_webhook_secret(header_secret="zap-secret") is True
    assert zls.verify_webhook_secret(token="wrong") is False
    assert zls.verify_webhook_secret(token=None, header_secret=None) is False


def test_verify_webhook_secret_empty_env(monkeypatch):
    monkeypatch.setattr(zls, "ZAPIER_WEBHOOK_SECRET", "")
    assert zls.verify_webhook_secret(token="anything") is False


def test_project_from_form_id_all_five(monkeypatch):
    monkeypatch.setattr(
        zls,
        "META_LEAD_FORM_PROJECT_MAP",
        {
            "2124096745052549": "reserve-16",
            "1874174036585908": "mira",
            "4309061012643289": "melange",
            "28059295887006740": "krsna",
            "1858929181319661": "vivriti",
        },
    )
    assert zls.project_from_form_id("4309061012643289")["id"] == "melange"
    assert zls.project_from_form_id("2124096745052549")["id"] == "reserve-16"
    assert zls.project_from_form_id("999") is None
    assert zls.project_from_form_id(None) is None


def test_map_zap_optional_blanks():
    body = zls.map_zap_payload_to_intake(
        {
            "Form ID": "4309061012643289",
            "Phone Number": "+919790942415",
            "First Name": "",
            "Last Name": "",
            "Email": "",
            "Budget": "",
            "Site Visit Preference": "",
        },
        leadgen_id="lg1",
        form_id="4309061012643289",
    )
    assert body["first_name"] == "Unknown"
    assert body["last_name"] == ""
    assert body["phone"] == "+919790942415"
    assert body["email"] is None
    assert "budget" not in body
    assert "schedule_visit" not in body
    assert body["source"] == "Facebook Lead Form"
    assert body["meta"]["via"] == "zapier"
    assert body["meta"]["leadgen_id"] == "lg1"


def test_map_zap_client_field_names():
    body = zls.map_zap_payload_to_intake(
        {
            "Created At": "2026-08-13T10:00:00+05:30",
            "Lead ID": "123",
            "Form ID": "2124096745052549",
            "First Name": "Manish",
            "Last Name": "Thakkar",
            "Email": "ruling.piping-5n@icloud.com",
            "Phone Number": "+918754025211",
            "Budget": "1.5 Cr",
            "Site Visit Preference": "Weekend",
        },
        leadgen_id="123",
        form_id="2124096745052549",
    )
    assert body["first_name"] == "Manish"
    assert body["last_name"] == "Thakkar"
    assert body["email"] == "ruling.piping-5n@icloud.com"
    assert body["phone"] == "+918754025211"
    assert body["budget"] == "1.5 Cr"
    assert body["schedule_visit"] == "Weekend"
    assert body["meta"]["created_at"] == "2026-08-13T10:00:00+05:30"


def test_map_zap_campaign_attribution_absent_by_default():
    """Today's standard Zapier Meta trigger doesn't send these - meta must
    not contain campaign/adset/ad keys unless the payload actually has them."""
    body = zls.map_zap_payload_to_intake(
        {"Form ID": "1", "First Name": "A", "Phone Number": "9000000000"},
        leadgen_id="lg1",
        form_id="1",
    )
    for key in ("campaign_id", "campaign_name", "adset_id", "adset_name", "ad_id", "ad_name"):
        assert key not in body["meta"]


def test_map_zap_campaign_attribution_captured_when_present():
    """If/once a Zap lookup step adds these fields, they must flow into meta."""
    body = zls.map_zap_payload_to_intake(
        {
            "Form ID": "1",
            "First Name": "A",
            "Phone Number": "9000000000",
            "Campaign ID": "120250129831400549",
            "Campaign Name": "Mira Lead Gen",
            "Adset ID": "120250129831440549",
            "Adset Name": "Broad Interest-HNI",
            "Ad ID": "120250130279250549",
            "Ad Name": "Video-Launch",
        },
        leadgen_id="lg1",
        form_id="1",
    )
    assert body["meta"]["campaign_id"] == "120250129831400549"
    assert body["meta"]["campaign_name"] == "Mira Lead Gen"
    assert body["meta"]["adset_id"] == "120250129831440549"
    assert body["meta"]["adset_name"] == "Broad Interest-HNI"
    assert body["meta"]["ad_id"] == "120250130279250549"
    assert body["meta"]["ad_name"] == "Video-Launch"


def test_map_zap_campaign_attribution_accepts_spaced_ad_set_label():
    """Zapier labels can read "Ad Set ID" / "Ad Set Name" (with a space)."""
    body = zls.map_zap_payload_to_intake(
        {"Form ID": "1", "First Name": "A", "Phone Number": "9000000000",
         "Ad Set ID": "111", "Ad Set Name": "Broad Interest-HNI"},
        leadgen_id="lg1", form_id="1",
    )
    assert body["meta"]["adset_id"] == "111"
    assert body["meta"]["adset_name"] == "Broad Interest-HNI"


def test_map_zap_duplicate_full_name_split():
    body = zls.map_zap_payload_to_intake(
        {
            "Form ID": "1874174036585908",
            "First Name": "Iyda Robert",
            "Last Name": "Iyda Robert",
            "Phone Number": "916382848893",
        },
        leadgen_id="lg-dup",
        form_id="1874174036585908",
    )
    assert body["first_name"] == "Iyda"
    assert body["last_name"] == "Robert"


@pytest.mark.asyncio
async def test_process_unmapped_form_skips_ingest(monkeypatch):
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {"1": "melange"})
    mock_db = MagicMock()
    mock_db.zapier_leads_logs.find_one = AsyncMock(return_value=None)
    mock_db.zapier_leads_logs.update_one = AsyncMock()
    monkeypatch.setattr(zls, "db", mock_db)
    ingest = AsyncMock()
    monkeypatch.setattr(zls, "ingest_lead", ingest)

    result = await zls.process_zapier_lead(
        {"Lead ID": "lg-x", "Form ID": "unmapped", "Phone Number": "1"}
    )
    assert result["reason"] == "unmapped_form"
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_missing_email_and_phone(monkeypatch):
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {"4309061012643289": "melange"})
    mock_db = MagicMock()
    mock_db.zapier_leads_logs.find_one = AsyncMock(return_value=None)
    mock_db.zapier_leads_logs.update_one = AsyncMock()
    monkeypatch.setattr(zls, "db", mock_db)
    ingest = AsyncMock()
    monkeypatch.setattr(zls, "ingest_lead", ingest)

    result = await zls.process_zapier_lead(
        {"Lead ID": "lg-empty", "Form ID": "4309061012643289", "First Name": "X"}
    )
    assert result["reason"] == "missing_email_and_phone"
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_already_processed(monkeypatch):
    mock_db = MagicMock()
    mock_db.zapier_leads_logs.find_one = AsyncMock(
        return_value={"leadgen_id": "lg1", "success": True, "lead_id": "L1"}
    )
    monkeypatch.setattr(zls, "db", mock_db)
    ingest = AsyncMock()
    monkeypatch.setattr(zls, "ingest_lead", ingest)

    result = await zls.process_zapier_lead(
        {"Lead ID": "lg1", "Form ID": "4309061012643289", "Email": "a@b.com"}
    )
    assert result["reason"] == "already_processed"
    assert result["lead_id"] == "L1"
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_happy_path_melange(monkeypatch):
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {"4309061012643289": "melange"})
    mock_db = MagicMock()
    mock_db.zapier_leads_logs.find_one = AsyncMock(return_value=None)
    mock_db.zapier_leads_logs.update_one = AsyncMock()
    monkeypatch.setattr(zls, "db", mock_db)
    monkeypatch.setattr(
        zls,
        "ingest_lead",
        AsyncMock(return_value=({"success": True, "lead_id": "L99", "deduped": False}, 201)),
    )

    result = await zls.process_zapier_lead(
        {
            "Lead ID": "lg-happy",
            "Form ID": "4309061012643289",
            "First Name": "Latha",
            "Last Name": "Ramalingam",
            "Email": "latharam1964@gmail.com",
            "Phone Number": "+919790942415",
        }
    )
    assert result["reason"] == "ingested"
    assert result["lead_id"] == "L99"
    assert result["project_id"] == "melange"
    zls.ingest_lead.assert_awaited_once()
    call_kwargs = zls.ingest_lead.await_args.kwargs
    assert call_kwargs["api_key"]["id"] == "zapier-meta:melange"
    assert call_kwargs["body"]["email"] == "latharam1964@gmail.com"
    assert call_kwargs["body"]["source"] == "Facebook Lead Form"


# ---- unrecognised Meta form: recover by name, otherwise save + alert (never lose silently) ----
import importlib.util
from pathlib import Path


def _mock_db():
    db = MagicMock()
    db.zapier_leads_logs.find_one = AsyncMock(return_value=None)
    db.zapier_leads_logs.update_one = AsyncMock()
    db.users.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[
        {"id": "adm1", "full_name": "Admin"}, {"id": "adm2", "full_name": "Harish"}])))
    return db


@pytest.mark.parametrize(
    "form_id,fields,expected",
    [
        ("R-16 - Leads", {}, "reserve-16"),  # the real rejected value
        ("Melange-LG-May-2026", {}, "melange"),  # the real rejected value
        ("Mélange - LG", {}, "melange"),
        ("Reserve 16 Launch", {}, "reserve-16"),
        ("Mira Lead Gen", {}, "mira"),
        ("x", {"Campaign Name": "Vivriti Nov '24"}, "vivriti"),
        ("x", {"Form Name": "Krsna Instant Form"}, "krsna"),
        ("28592336347085244", {}, None),  # a numeric ID is never guessed at
        ("28592336347085244", {"campaign_name": "R-16 - Leads"}, "reserve-16"),  # but the campaign name can say
        ("R-16 - Leads", {"campaign_name": "Melange LG"}, None),  # two projects named: ambiguous, not guessed
        ("Admiration offer", {}, None),  # whole words only ("mira" is not inside "admiration")
        ("", {}, None),
    ],
)
def test_project_from_names(form_id, fields, expected):
    got = zls.project_from_names(fields, form_id)
    assert (got or {}).get("id") == expected


@pytest.mark.asyncio
async def test_form_id_carrying_a_campaign_name_still_creates_the_lead(monkeypatch):
    """Priya's case: the Zap sent 'R-16 - Leads' as the form id."""
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {"2124096745052549": "reserve-16"})
    monkeypatch.setattr(zls, "db", _mock_db())
    ingest = AsyncMock(return_value=({"success": True, "lead_id": "L1", "deduped": True}, 200))
    monkeypatch.setattr(zls, "ingest_lead", ingest)
    result = await zls.process_zapier_lead(
        {"Lead ID": "lg-r16", "Form ID": "R-16 - Leads", "Full Name": "Priya", "Email": "p@example.com", "Phone Number": "+919585855536"}
    )
    assert result["success"] is True and result["project_id"] == "reserve-16"
    kw = ingest.await_args.kwargs
    assert kw["api_key"]["id"] == "zapier-meta:reserve-16"
    assert kw["body"]["meta"]["project_resolved_by"] == "form_or_campaign_name"


@pytest.mark.asyncio
async def test_unmapped_form_saves_payload_and_alerts_admins(monkeypatch):
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {"1": "melange"})
    db = _mock_db()
    monkeypatch.setattr(zls, "db", db)
    ingest = AsyncMock()
    monkeypatch.setattr(zls, "ingest_lead", ingest)
    notify = AsyncMock()
    import crm.services.notification_service as ns
    monkeypatch.setattr(ns, "create_notification", notify)

    payload = {"Lead ID": "lg-new", "Form ID": "28592336347085244", "Full Name": "New Person", "Phone Number": "+919000000000"}
    result = await zls.process_zapier_lead(payload)

    assert result["reason"] == "unmapped_form"
    ingest.assert_not_awaited()
    set_fields = db.zapier_leads_logs.update_one.await_args.args[1]["$set"]
    assert set_fields["reason"] == "unmapped_form"
    assert set_fields["rejected_payload"]["Phone Number"] == "+919000000000"  # saved, so it can be replayed
    assert notify.await_count == 2  # both active Admin accounts
    assert notify.await_args.kwargs["severity"] == "high"
    assert "28592336347085244" in notify.await_args.kwargs["message"]


@pytest.mark.asyncio
async def test_alert_failure_never_breaks_intake(monkeypatch):
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {})
    db = _mock_db()
    db.users.find = MagicMock(side_effect=RuntimeError("db down"))
    monkeypatch.setattr(zls, "db", db)
    result = await zls.process_zapier_lead({"Lead ID": "lg-z", "Form ID": "999"})
    assert result["reason"] == "unmapped_form"


@pytest.mark.asyncio
async def test_successful_submissions_do_not_store_a_payload(monkeypatch):
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {"4309061012643289": "melange"})
    db = _mock_db()
    monkeypatch.setattr(zls, "db", db)
    monkeypatch.setattr(zls, "ingest_lead", AsyncMock(return_value=({"success": True, "lead_id": "L2"}, 201)))
    await zls.process_zapier_lead({"Lead ID": "lg-ok", "Form ID": "4309061012643289", "Email": "a@b.co"})
    for call in db.zapier_leads_logs.update_one.await_args_list:
        assert "rejected_payload" not in call.args[1]["$set"]  # no contact details kept for normal leads


def _replay_script():
    p = Path(__file__).resolve().parent.parent / "scripts" / "replay_unmapped_zapier_leads.py"
    spec = importlib.util.spec_from_file_location("replay_unmapped", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.asyncio
async def test_replay_only_replays_what_can_be_matched_now(monkeypatch):
    m = _replay_script()
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {})
    rows = [
        {"leadgen_id": "a", "form_id": "R-16 - Leads", "rejected_payload": {"Lead ID": "a", "Form ID": "R-16 - Leads", "Email": "a@b.co"}},
        {"leadgen_id": "b", "form_id": "28592336347085244", "rejected_payload": {"Lead ID": "b", "Form ID": "28592336347085244"}},
    ]
    db = MagicMock()
    db.zapier_leads_logs.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=rows)))
    plan = await m.plan_replay(db, zls)
    assert [(p["leadgen_id"], p["project"]) for p in plan] == [("a", "reserve-16"), ("b", None)]

    processed = []

    async def fake_process(payload):
        processed.append(payload["Lead ID"])
        return {"success": True}

    monkeypatch.setattr(zls, "process_zapier_lead", fake_process)
    res = await m.replay(zls, plan)
    assert processed == ["a"] and res == {"replayed": 1, "failed": 0, "still_unmatched": 1}


# ---- project from the FORM NAME (agreed with the client: Form IDs change when a form is edited) ----
@pytest.mark.parametrize(
    "form_name,expected",
    [
        ("Reserve - 16 | Oct 26", "reserve-16"),
        ("Reserve - 16 | Large Plots LG", "reserve-16"),
        ("Reserve - 16 | Lead Generation (Jan)", "reserve-16"),
        ("Melange - May26", "melange"),
        ("Mira Launch Updated Pricing - Jun'26", "mira"),
        ("Vivriti_aug_2025", "vivriti"),
        ("Krsna Leads 2026 Jun", "krsna"),
        ("Melange vs Reserve 16", None),  # two projects: not guessed
        ("Generic Brand Awareness", None),
    ],
)
def test_project_from_form_name(form_name, expected):
    assert (zls.project_from_form_name({"Form Name": form_name}) or {}).get("id") == expected


@pytest.mark.parametrize("key", ["Form Name", "form_name", "Form Title", "Project"])
def test_form_name_is_read_from_the_usual_zap_keys(key):
    assert zls.project_from_form_name({key: "Melange - May26"})["id"] == "melange"


@pytest.mark.asyncio
async def test_form_name_wins_over_a_stale_or_unknown_form_id(monkeypatch):
    """The Form ID changed after a form edit and is unknown/stale - the name still decides."""
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {"2124096745052549": "reserve-16"})
    monkeypatch.setattr(zls, "db", _mock_db())
    ingest = AsyncMock(return_value=({"success": True, "lead_id": "L1"}, 201))
    monkeypatch.setattr(zls, "ingest_lead", ingest)
    res = await zls.process_zapier_lead(
        {"Lead ID": "lg-fn", "Form ID": "999000111", "Form Name": "Melange - May26", "Email": "a@b.co"}
    )
    assert res["success"] and res["project_id"] == "melange"
    meta = ingest.await_args.kwargs["body"]["meta"]
    assert meta["project_resolved_by"] == "form_name" and meta["form_name"] == "Melange - May26"


@pytest.mark.asyncio
async def test_form_name_beats_a_conflicting_known_form_id(monkeypatch):
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {"2124096745052549": "reserve-16"})
    monkeypatch.setattr(zls, "db", _mock_db())
    monkeypatch.setattr(zls, "ingest_lead", AsyncMock(return_value=({"success": True, "lead_id": "L1"}, 201)))
    res = await zls.process_zapier_lead(
        {"Lead ID": "lg-c", "Form ID": "2124096745052549", "Form Name": "Mira Launch Updated Pricing - Jun'26", "Email": "a@b.co"}
    )
    assert res["project_id"] == "mira"


@pytest.mark.asyncio
async def test_known_form_id_still_works_without_a_form_name(monkeypatch):
    monkeypatch.setattr(zls, "META_LEAD_FORM_PROJECT_MAP", {"4309061012643289": "melange"})
    monkeypatch.setattr(zls, "db", _mock_db())
    monkeypatch.setattr(zls, "ingest_lead", AsyncMock(return_value=({"success": True, "lead_id": "L1"}, 201)))
    res = await zls.process_zapier_lead({"Lead ID": "lg-id", "Form ID": "4309061012643289", "Email": "a@b.co"})
    assert res["project_id"] == "melange"


# ---- recovered (backfilled) submissions keep their real time and never message the customer ----
def test_parse_created_time():
    from datetime import timezone

    t = zls._parse_created_time("2026-10-09 09:32:00")
    assert (t.year, t.month, t.day, t.hour, t.minute) == (2026, 10, 9, 9, 32) and t.tzinfo == timezone.utc
    assert zls._parse_created_time("2026-10-09T09:32:00Z").hour == 9
    assert zls._parse_created_time("") is None and zls._parse_created_time("not a date") is None


@pytest.mark.parametrize("key", ["Created at", "Created Time", "created_time"])
def test_created_time_is_read_under_each_spelling(key):
    body = zls.map_zap_payload_to_intake({key: "2026-10-09 09:32:00", "Email": "a@b.co"}, leadgen_id="x", form_id=None)
    assert body["meta"]["created_at"] == "2026-10-09 09:32:00"


@pytest.mark.asyncio
async def test_backfill_flag_marks_the_submission_with_its_real_time(monkeypatch):
    monkeypatch.setattr(zls, "db", _mock_db())
    ingest = AsyncMock(return_value=({"success": True, "lead_id": "L1"}, 201))
    monkeypatch.setattr(zls, "ingest_lead", ingest)
    payload = {"Lead ID": "lg-b", "Form Name": "Melange - May26", "Email": "a@b.co", "Created at": "2026-10-09 09:32:00"}
    await zls.process_zapier_lead(payload, backfill=True)
    meta = ingest.await_args.kwargs["body"]["meta"]
    assert meta["backfill"] is True and meta["occurred_at"].startswith("2026-10-09T09:32:00")
    await zls.process_zapier_lead({**payload, "Lead ID": "lg-c"})  # a live submission carries no such mark
    assert "backfill" not in ingest.await_args.kwargs["body"]["meta"]


def test_backfill_time_helper_ignores_live_submissions():
    from crm.services.lead_intake_service import _backfill_time

    assert _backfill_time({"meta": {"created_at": "2026-10-09 09:32:00"}}) is None
    assert _backfill_time({"meta": {"backfill": True, "occurred_at": "garbage"}}) is None
    t = _backfill_time({"meta": {"backfill": True, "occurred_at": "2026-10-09T09:32:00+00:00"}})
    assert (t.day, t.hour, t.minute) == (9, 9, 32)
