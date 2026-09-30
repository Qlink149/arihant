"""batch2 item 4b: CSV dates must be interpreted as IST wall-clock time and
converted to UTC for storage; an unparseable value must return None so the
caller rejects the row, never silently default to "now"."""

from datetime import timezone

from crm.utils.helpers import parse_csv_date


def test_datetime_with_time_is_interpreted_as_ist():
    # 2026-09-25 23:30 IST == 2026-09-25 18:00 UTC (the exact example in the prompt)
    result = parse_csv_date("2026-09-25 23:30")
    assert result is not None
    assert result.startswith("2026-09-25T18:00:00")


def test_datetime_dmy_with_seconds_is_interpreted_as_ist():
    result = parse_csv_date("25-09-2026 23:30:00")
    assert result.startswith("2026-09-25T18:00:00")


def test_near_midnight_ist_lands_on_correct_utc_day():
    # 2026-09-26 00:15 IST is still 2026-09-25 18:45 UTC - the previous UTC day.
    # This is exactly the "rows near midnight land on the wrong day" bug.
    result = parse_csv_date("2026-09-26 00:15")
    assert result.startswith("2026-09-25T18:45:00")


def test_date_only_value_is_midnight_ist_of_that_day():
    result = parse_csv_date("2026-09-25")
    # 2026-09-25 00:00 IST == 2026-09-24 18:30 UTC
    assert result.startswith("2026-09-24T18:30:00")


def test_date_only_dmy_slash_format():
    result = parse_csv_date("25/09/2026")
    assert result.startswith("2026-09-24T18:30:00")


def test_unparseable_date_returns_none_not_now():
    assert parse_csv_date("not a date") is None
    assert parse_csv_date("32-13-2026") is None
    assert parse_csv_date("") is None
    assert parse_csv_date(None) is None
    assert parse_csv_date("   ") is None


def test_result_is_valid_utc_iso_string():
    result = parse_csv_date("2026-01-01 12:00")
    assert result is not None
    from datetime import datetime

    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)
