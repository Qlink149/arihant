from datetime import datetime, timezone

from crm.utils.helpers import coerce_datetime


def test_coerce_naive_string_becomes_utc_aware():
    dt = coerce_datetime("2025-05-27T10:30:00")
    assert dt is not None
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 10
    assert dt.minute == 30


def test_coerce_z_suffix_unchanged_instant():
    dt = coerce_datetime("2025-05-27T10:30:00Z")
    assert dt == datetime(2025, 5, 27, 10, 30, 0, tzinfo=timezone.utc)


def test_coerce_offset_string_normalized_to_utc():
    dt = coerce_datetime("2025-05-27T16:00:00+05:30")
    assert dt == datetime(2025, 5, 27, 10, 30, 0, tzinfo=timezone.utc)


def test_coerce_naive_datetime_instance():
    naive = datetime(2025, 5, 27, 10, 30, 0)
    dt = coerce_datetime(naive)
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 10


def test_coerce_wati_long_fractional_seconds():
    dt = coerce_datetime("2025-11-27T10:14:16.6268572Z")
    assert dt is not None
    assert dt.year == 2025
    assert dt.month == 11
    assert dt.day == 27
    assert dt.hour == 10
    assert dt.minute == 14
    assert dt.second == 16
