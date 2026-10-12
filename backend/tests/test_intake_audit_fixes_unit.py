"""Intake audit fixes: doubled names, and unrecognised website forms are saved + alerted."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.utils.person_names import tidy_person_name


@pytest.mark.parametrize(
    "first,last,expected",
    [
        ("Thiru", "Thiru", ("Thiru", "")),  # a single word sent twice: keep one
        ("THIRU", "thiru", ("THIRU", "")),
        ("Anju Bagri Damani", "Anju Bagri Damani", ("Anju Bagri", "Damani")),  # full name sent twice: split once
        ("Anju Bagri Damani", "Damani", ("Anju Bagri", "Damani")),  # surname already inside the first name
        ("Prasanth Lu Lu", "Lu Lu", ("Prasanth", "Lu Lu")),
        ("Aloha K Kumaran", "Kumaran", ("Aloha K", "Kumaran")),
        ("சிகாமணி", "சிகாமணி", ("சிகாமணி", "")),
        ("Ravi", "Kumar", ("Ravi", "Kumar")),  # normal names are never touched
        ("Ram", "Ramesh", ("Ram", "Ramesh")),  # a prefix is not a repeat
        ("Kumar", "Kumar S", ("Kumar", "Kumar S")),
        ("Mr Raja", "Raja", ("Mr", "Raja")),
        ("Priya", "", ("Priya", "")),
        ("", "Sharma", ("", "Sharma")),
        ("  Anu   Radha ", " Radha ", ("Anu", "Radha")),  # stray spaces
    ],
)
def test_tidy_person_name(first, last, expected):
    assert tidy_person_name(first, last) == expected


def test_a_name_is_never_lost_or_invented():
    for first, last in [("Thiru", "Thiru"), ("Anju Bagri Damani", "Damani"), ("A B", "B"), ("Sri Ram", "Ram")]:
        f, l = tidy_person_name(first, last)
        assert f  # a first name always survives
        assert set((f + " " + l).casefold().split()) <= set((first + " " + last).casefold().split())  # only repeats removed


def test_intake_validation_applies_it_to_every_channel():
    from crm.services.lead_intake_service import validate_intake_payload

    data = validate_intake_payload({"first_name": "Thiru", "last_name": "Thiru", "email": "t@example.com", "consent": True})
    assert (data["first_name"], data["last_name"]) == ("Thiru", "")
    data = validate_intake_payload({"first_name": "Anju Bagri Damani", "last_name": "Damani", "email": "a@example.com", "consent": True})
    assert (data["first_name"], data["last_name"]) == ("Anju Bagri", "Damani")
    data = validate_intake_payload({"first_name": "Priya", "last_name": "Sharma", "email": "p@example.com", "consent": True})
    assert (data["first_name"], data["last_name"]) == ("Priya", "Sharma")


# ---- unrecognised website forms ----
import crm.services.webflow_leads_service as wls  # noqa: E402


def _db():
    db = MagicMock()
    db.webflow_leads_logs.find_one = AsyncMock(return_value=None)
    db.webflow_leads_logs.update_one = AsyncMock()
    return db


def _body(form_name):
    return {"payload": {"id": "sub-1", "name": form_name, "formId": "f1", "siteId": "s1",
                        "data": {"Name": "Real Customer", "Contact Number": "9000000001", "Email": "c@example.com", "Message": "Interested"}}}


@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["Partner Form", "Some Brand New Form"])
async def test_unrecognised_enquiry_form_is_saved_and_alerted(monkeypatch, form):
    db = _db()
    monkeypatch.setattr(wls, "db", db)
    alert = AsyncMock()
    import crm.services.intake_alerts as ia
    monkeypatch.setattr(ia, "alert_admins_unrecognised_form", alert)
    res = await wls.process_form_submission(_body(form))
    assert res["reason"] == "unmapped_form"
    saved = db.webflow_leads_logs.update_one.await_args.args[1]["$set"]
    assert saved["reason"] == "unmapped_form" and saved["rejected_payload"]["Contact Number"] == "9000000001"
    alert.assert_awaited_once_with("Website", form)


@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["Career Form", "Newsletter Form"])
async def test_non_lead_forms_are_still_rejected_without_an_alert(monkeypatch, form):
    monkeypatch.setattr(wls, "db", _db())
    alert = AsyncMock()
    import crm.services.intake_alerts as ia
    monkeypatch.setattr(ia, "alert_admins_unrecognised_form", alert)
    res = await wls.process_form_submission(_body(form))
    assert res["reason"] == "unmapped_form"
    alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_alert_goes_to_every_active_admin_once_per_form_per_day(monkeypatch):
    import crm.services.intake_alerts as ia
    import crm.services.notification_service as ns

    db = MagicMock()
    db.users.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[{"id": "a1", "full_name": "Admin"}, {"id": "a2", "full_name": "Harish"}])))
    monkeypatch.setattr(ia, "db", db)
    notify = AsyncMock()
    monkeypatch.setattr(ns, "create_notification", notify)
    await ia.alert_admins_unrecognised_form("Website", "Contact Us Form")
    assert notify.await_count == 2
    keys = {c.kwargs["dedupe_key"] for c in notify.await_args_list}
    assert len(keys) == 2 and all("Contact Us Form" in k for k in keys)
    assert "Contact Us Form" in notify.await_args.kwargs["title"] or "Website" in notify.await_args.kwargs["title"]


@pytest.mark.asyncio
async def test_alert_failure_never_breaks_intake(monkeypatch):
    import crm.services.intake_alerts as ia

    db = MagicMock()
    db.users.find = MagicMock(side_effect=RuntimeError("db down"))
    monkeypatch.setattr(ia, "db", db)
    await ia.alert_admins_unrecognised_form("Website", "X")  # must not raise


# ---- scripts/tidy_lead_names.py ----
import importlib.util
import json
from pathlib import Path


def _tidy_script():
    p = Path(__file__).resolve().parent.parent / "scripts" / "tidy_lead_names.py"
    spec = importlib.util.spec_from_file_location("tidy_lead_names", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Cur:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, _n):
        return [dict(r) for r in self.rows]


class _Leads:
    def __init__(self, docs):
        self.docs = [dict(d) for d in docs]
        self.sets = []

    def find(self, flt=None, proj=None):
        return _Cur(self.docs)

    async def update_one(self, flt, upd):
        for d in self.docs:
            if d["_id"] == flt["_id"]:
                before = dict(d)
                d.update(upd["$set"])
                self.sets.append(upd)
                return MagicMock(modified_count=1 if d != before else 0)
        return MagicMock(modified_count=0)


@pytest.mark.asyncio
async def test_tidy_script_dry_run_apply_and_idempotent(tmp_path):
    m = _tidy_script()
    db = MagicMock()
    db.leads = _Leads([
        {"_id": 1, "id": "a", "first_name": "Thiru", "last_name": "Thiru", "updated_at": "T0"},
        {"_id": 2, "id": "b", "first_name": "Anju Bagri Damani", "last_name": "Damani"},
        {"_id": 3, "id": "c", "first_name": "Ravi", "last_name": "Kumar"},
    ])
    plan = await m.build_plan(db, "all")
    assert [p["id"] for p in plan] == ["a", "b"]  # the normal name is left alone
    assert db.leads.sets == []  # preview wrote nothing

    res = await m.apply_plan(db, plan, backup_dir=tmp_path)
    assert res["updated"] == 2
    by = {d["id"]: d for d in db.leads.docs}
    assert (by["a"]["first_name"], by["a"]["last_name"]) == ("Thiru", "")
    assert (by["b"]["first_name"], by["b"]["last_name"]) == ("Anju Bagri", "Damani")
    assert by["a"]["updated_at"] == "T0"  # "Updated At" never moves
    for upd in db.leads.sets:
        assert set(upd["$set"]) == {"first_name", "last_name"}
    backup = json.loads(Path(res["backup_file"]).read_text(encoding="utf-8"))
    assert {b["id"]: b["before"]["first_name"] for b in backup} == {"a": "Thiru", "b": "Anju Bagri Damani"}
    assert await m.build_plan(db, "all") == []  # idempotent


def test_scopes_are_opt_in():
    m = _tidy_script()
    assert m.SCOPE_FILTERS["meta"] == {"intake_meta.via": "zapier"}
    assert m.SCOPE_FILTERS["all"] == {}


# ---- Contact Us / Homepage Enquiry forms: real customers, no project -> they become leads ----
@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["Contact Us Form", "Homepage Enquiry Form"])
async def test_general_enquiry_forms_create_a_lead_with_no_project(monkeypatch, form):
    db = _db()
    monkeypatch.setattr(wls, "db", db)
    ingest = AsyncMock(return_value=({"success": True, "lead_id": "L1"}, 201))
    monkeypatch.setattr(wls, "ingest_lead", ingest)
    res = await wls.process_form_submission(_body(form))
    assert res["success"] is True and res["project_id"] is None
    kw = ingest.await_args.kwargs
    assert kw["api_key"]["id"] == "webflow:general" and kw["api_key"]["project_id"] is None and kw["api_key"]["project_name"] is None
    body = kw["body"]
    assert body["source"] == "Website" and body["phone"] == "9000000001" and body["email"] == "c@example.com"
    assert (body["first_name"], body["last_name"]) == ("Real", "Customer")  # a single "Name" box is split
    assert body["meta"]["webflow_form_name"] == form


@pytest.mark.asyncio
async def test_general_form_with_a_project_dropdown_still_uses_that_project(monkeypatch):
    monkeypatch.setattr(wls, "db", _db())
    ingest = AsyncMock(return_value=({"success": True, "lead_id": "L1"}, 201))
    monkeypatch.setattr(wls, "ingest_lead", ingest)
    body = {"payload": {"id": "s2", "name": "Homepage Enquiry Form", "formId": "f", "siteId": "s",
                        "data": {"Name": "A B", "Phone": "9000000002", "Project-Name": "Melange"}}}
    res = await wls.process_form_submission(body)
    assert res["project_id"] == "melange"
    assert ingest.await_args.kwargs["body"]["source"] == "Mélange Website"


@pytest.mark.asyncio
async def test_failed_general_enquiry_keeps_its_details(monkeypatch):
    db = _db()
    monkeypatch.setattr(wls, "db", db)
    monkeypatch.setattr(wls, "ingest_lead", AsyncMock(side_effect=RuntimeError("boom")))
    res = await wls.process_form_submission(_body("Contact Us Form"))
    assert res["reason"] == "ingest_error"
    saved = db.webflow_leads_logs.update_one.await_args.args[1]["$set"]
    assert saved["rejected_payload"]["Contact Number"] == "9000000001" and saved["project_id"] is None

    db2 = _db()
    monkeypatch.setattr(wls, "db", db2)
    nocontact = {"payload": {"id": "s3", "name": "Contact Us Form", "formId": "f", "siteId": "s", "data": {"Name": "No Contact", "Message": "hi"}}}
    res = await wls.process_form_submission(nocontact)
    assert res["reason"] == "missing_email_and_phone"
    assert db2.webflow_leads_logs.update_one.await_args.args[1]["$set"]["rejected_payload"]["Message"] == "hi"


@pytest.mark.asyncio
async def test_successful_website_lead_stores_no_payload(monkeypatch):
    db = _db()
    monkeypatch.setattr(wls, "db", db)
    monkeypatch.setattr(wls, "ingest_lead", AsyncMock(return_value=({"success": True, "lead_id": "L1"}, 201)))
    await wls.process_form_submission(_body("Contact Us Form"))
    for call in db.webflow_leads_logs.update_one.await_args_list:
        assert "rejected_payload" not in call.args[1]["$set"]


@pytest.mark.parametrize("label", ["Name", "Full Name", "full-name", "Your Name", "Customer Name"])
def test_a_single_name_box_is_split_into_first_and_last(label):
    body = wls.map_webflow_data_to_intake(
        {label: "Real Customer Kumar", "Email": "a@b.co"}, project={"id": "", "name": ""},
        submission_id="s", form_id="f", site_id="x", form_name="Contact Us Form",
    )
    assert (body["first_name"], body["last_name"]) == ("Real", "Customer Kumar")


def test_first_and_last_boxes_still_win_over_a_name_box():
    body = wls.map_webflow_data_to_intake(
        {"First Name": "Priya", "Last Name": "Sharma", "Name": "Ignored Value", "Email": "a@b.co"},
        project={"id": "melange", "name": "Mélange"}, submission_id="s", form_id="f", site_id="x", form_name="Melange Enquiry Form",
    )
    assert (body["first_name"], body["last_name"]) == ("Priya", "Sharma") and body["source"] == "Mélange Website"
