"""Unit smoke for IST wall-clock → UTC conversion used by task due_at_dt."""

from datetime import timezone
from zoneinfo import ZoneInfo

from crm.utils.helpers import ist_wall_to_utc_dt

IST = ZoneInfo("Asia/Kolkata")


def test_ist_wall_11am_is_0530_utc():
    dt = ist_wall_to_utc_dt("2026-08-04", "11:00")
    assert dt.tzinfo is not None
    utc = dt.astimezone(timezone.utc)
    assert utc.hour == 5
    assert utc.minute == 30
    ist = dt.astimezone(IST)
    assert ist.hour == 11
    assert ist.minute == 0
