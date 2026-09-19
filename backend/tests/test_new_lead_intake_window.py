"""New-lead intake window matches business hours."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from crm.services.sla_engine import is_new_lead_intake_window_ist

IST = ZoneInfo("Asia/Kolkata")


def _ist(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=IST).astimezone(timezone.utc)


def test_sunday_1715_in_window():
    assert is_new_lead_intake_window_ist(_ist(2026, 6, 7, 17, 15))


def test_sunday_1745_out_of_window():
    assert not is_new_lead_intake_window_ist(_ist(2026, 6, 7, 17, 45))


def test_saturday_1000_in_window():
    assert is_new_lead_intake_window_ist(_ist(2026, 6, 6, 10, 0))


def test_saturday_0900_out_of_window():
    assert not is_new_lead_intake_window_ist(_ist(2026, 6, 6, 9, 0))
