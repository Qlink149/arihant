"""
Business-time elapsed seconds for SLA (Mon–Sat 10:00–17:30 Asia/Kolkata).

Timers pause outside business hours and resume at 10:00 with remaining duration.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
BUSINESS_START = time(10, 0)
BUSINESS_END = time(17, 30)
BUSINESS_SECONDS_PER_DAY = int(
    (datetime.combine(datetime.min.date(), BUSINESS_END) - datetime.combine(datetime.min.date(), BUSINESS_START)).total_seconds()
)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _to_ist(dt: datetime) -> datetime:
    return _ensure_utc(dt).astimezone(IST)


def is_business_day_ist(dt: datetime) -> bool:
    return _to_ist(dt).weekday() != 6


def is_business_hours_ist(now_dt: datetime) -> bool:
    """Point-in-time check: Mon–Sat between 10:00 and 17:30 IST inclusive."""
    ist = _to_ist(now_dt)
    if ist.weekday() == 6:
        return False
    t = ist.time()
    return BUSINESS_START <= t <= BUSINESS_END


def _business_window_seconds_for_day(day_start_ist: datetime) -> tuple[datetime, datetime, int]:
    """Return (window_start_utc, window_end_utc, seconds_in_window) for one IST calendar day."""
    d = day_start_ist.date()
    start_local = datetime.combine(d, BUSINESS_START, tzinfo=IST)
    end_local = datetime.combine(d, BUSINESS_END, tzinfo=IST)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc), BUSINESS_SECONDS_PER_DAY


def business_seconds_elapsed(start: datetime, end: datetime) -> int:
    """
    Count seconds elapsed between start and end that fall inside business hours.
    """
    if end <= start:
        return 0

    start_ist = _to_ist(start)
    end_ist = _to_ist(end)
    total = 0
    day = start_ist.date()
    last_day = end_ist.date()

    while day <= last_day:
        if day.weekday() != 6:
            win_start, win_end, win_seconds = _business_window_seconds_for_day(
                datetime.combine(day, time.min, tzinfo=IST)
            )
            seg_start = max(start_ist, win_start)
            seg_end = min(end_ist, win_end)
            if seg_end > seg_start:
                total += int((seg_end - seg_start).total_seconds())
        day += timedelta(days=1)

    return total


def business_deadline(start: datetime, business_seconds: int) -> datetime:
    """UTC datetime when business_seconds of elapsed time will be reached from start."""
    if business_seconds <= 0:
        return _ensure_utc(start)

    remaining = business_seconds
    cursor = _to_ist(start)
    safety = 0
    while remaining > 0 and safety < 4000:
        safety += 1
        if cursor.weekday() == 6:
            cursor = datetime.combine(cursor.date() + timedelta(days=1), BUSINESS_START, tzinfo=IST)
            continue
        win_start, win_end, _ = _business_window_seconds_for_day(cursor)
        seg_start = max(cursor, win_start)
        available = int((win_end - seg_start).total_seconds())
        if available <= 0:
            cursor = datetime.combine(cursor.date() + timedelta(days=1), BUSINESS_START, tzinfo=IST)
            continue
        if remaining <= available:
            return (seg_start + timedelta(seconds=remaining)).astimezone(timezone.utc)
        remaining -= available
        cursor = datetime.combine(cursor.date() + timedelta(days=1), BUSINESS_START, tzinfo=IST)

    return _ensure_utc(start)


def business_seconds_ago_threshold(now: datetime, business_seconds: int) -> datetime:
    """
    Latest UTC start time such that business_seconds_elapsed(start, now) >= business_seconds.
    Approximate inverse via linear search from (now - 7d).
    """
    now_u = _ensure_utc(now)
    low = now_u - timedelta(days=14)
    high = now_u
    while business_seconds_elapsed(low, high) < business_seconds:
        low -= timedelta(hours=12)
    # Binary search
    for _ in range(64):
        mid = low + (high - low) / 2
        if business_seconds_elapsed(mid, now_u) >= business_seconds:
            high = mid
        else:
            low = mid
    return high
