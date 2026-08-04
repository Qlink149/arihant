from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from crm.utils.business_time import business_deadline, business_seconds_elapsed, is_business_hours_ist

IST = ZoneInfo("Asia/Kolkata")


def _ist(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=IST).astimezone(timezone.utc)


def test_lead_at_1720_1h_new_fires_next_day_1050():
    start = _ist(2026, 6, 2, 17, 20)  # Monday — ~10m left before end of business day
    end = business_deadline(start, 3600)
    end_ist = end.astimezone(IST)
    assert end_ist.hour == 10
    assert end_ist.minute == 50
    assert end_ist.day == 3


def test_sunday_excluded():
    # Saturday 17:20 (10m left) + Sunday skipped + Monday 10:00–10:10
    start = _ist(2026, 6, 6, 17, 20)
    elapsed = business_seconds_elapsed(start, _ist(2026, 6, 8, 10, 10))
    assert elapsed == 1200


def test_business_hours_window():
    assert is_business_hours_ist(_ist(2026, 6, 2, 10, 0))
    assert not is_business_hours_ist(_ist(2026, 6, 1, 9, 0))  # Sunday
