"""scripts/backfill_meta_leads_from_sheet.py - classification of raw Meta export rows."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest


def _m():
    p = Path(__file__).resolve().parent.parent / "scripts" / "backfill_meta_leads_from_sheet.py"
    spec = importlib.util.spec_from_file_location("backfill_meta_sheet", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


FORM = datetime(2026, 10, 9, 9, 32)


def _row(**kw):
    base = {"created_at": FORM, "first_name": "Priya", "last_name": "P", "phone": "9585855536", "email": "p@x.co",
            "form_name": "Reserve - 16 | Oct 26", "lead_id": "2054935775151470", "form_id": "", "site_visit": "",
            "campaign_name": "", "campaign_id": "", "adset_name": "", "adset_id": "", "ad_name": "", "ad_id": ""}
    base.update(kw)
    return base


def test_phone_and_lead_id_cleaning():
    m = _m()
    assert m.phone10(919585855536) == "9585855536" and m.phone10("+91 95858 55536") == "9585855536"
    assert m.lead_id_text(1512475490630030.0) == "1512475490630030" and m.lead_id_text(None) == ""


def test_classification():
    m = _m()
    assert m.classify(_row(), None) == "NEW"
    assert m.classify(_row(phone="123"), None) == "SKIP_BAD_PHONE"
    old = {"created_at": "2026-09-01T16:29:18+00:00"}
    assert m.classify(_row(), old) == "REENQUIRY"  # lead is older than the form submission
    came_from_it = {"created_at": "2026-10-09T09:30:00+00:00"}  # created minutes before/at the form time
    assert m.classify(_row(), came_from_it) == "SKIP"
    created_after = {"created_at": "2026-10-12T06:52:00+00:00"}  # e.g. imported from the CSV later
    assert m.classify(_row(), created_after) == "SKIP"
    already = {"created_at": "2026-09-01T16:29:18+00:00", "re_enquired_at": datetime(2026, 10, 9, 9, 33)}
    assert m.classify(_row(), already) == "SKIP"  # re-enquiry already recorded: idempotent
    earlier_tag = {"created_at": "2026-09-01T16:29:18+00:00", "re_enquired_at": datetime(2026, 9, 14)}
    assert m.classify(_row(), earlier_tag) == "REENQUIRY"  # an older tag does not cover this one


def test_whatsapp_first_touch_is_detected_but_only_listed():
    m = _m()
    wa = {"lead_source": "Whatsapp", "created_at": "2026-10-09T09:32:00+00:00"}
    assert m.whatsapp_first_touch(_row(), wa)
    assert not m.whatsapp_first_touch(_row(), {"lead_source": "Facebook", "created_at": "2026-10-09T09:32:00+00:00"})
    assert not m.whatsapp_first_touch(_row(), {"lead_source": "Whatsapp", "created_at": "2026-09-01T00:00:00+00:00"})  # WhatsApp really was first


def test_repeated_export_rows_are_collapsed():
    m = _m()
    rows = [_row(), _row(created_at=FORM + timedelta(seconds=1)), _row(lead_id="999", phone="9000000001")]
    assert len(m.dedupe_rows(rows)) == 2


def test_payload_uses_the_form_name_and_real_lead_id():
    m = _m()
    pl = m.to_zapier_payload(_row(campaign_name="R-16 - Leads"), "2054935775151472")
    assert pl["Lead ID"] == "2054935775151472" and pl["Form Name"] == "Reserve - 16 | Oct 26"
    assert pl["Phone Number"] == "+919585855536" and pl["Campaign Name"] == "R-16 - Leads"
    assert "Campaign ID" not in pl and "Form ID" not in pl  # blanks are not sent
    assert pl["Created at"] == "2026-10-09 09:32:00"  # the key the live Zap sends
    assert m.to_zapier_payload(_row(), None)["Lead ID"] == "2054935775151470"


def test_every_agreed_form_name_resolves_to_a_project():
    from crm.services import zapier_leads_service as zls

    for name in ["Reserve - 16 | Oct 26", "Reserve - 16 | Large Plots LG", "Melange - May26", "Mira Launch Updated Pricing - Jun'26"]:
        assert zls.project_from_form_name({"Form Name": name})
