"""Unit tests for MCUBE helpers (no DB)."""

from datetime import timezone
from zoneinfo import ZoneInfo

from crm.constants.mcube import normalize_inbound_dialstatus, is_missed_status
from crm.services.mcube.duration import parse_duration
from crm.services.mcube.payload import lowercase_keys, redact_payload, _maybe_parse_data_wrapper
from crm.utils.helpers import parse_mcube_dt

IST = ZoneInfo("Asia/Kolkata")


def test_parse_mcube_dt_naive_ist_to_utc():
    dt = parse_mcube_dt("2026-09-09 12:03:34")
    assert dt is not None
    assert dt.tzinfo is not None
    # 12:03 IST = 06:33 UTC
    assert dt.astimezone(timezone.utc).hour == 6
    assert dt.astimezone(timezone.utc).minute == 33


def test_parse_mcube_dt_empty_and_garbage():
    assert parse_mcube_dt(None) is None
    assert parse_mcube_dt("") is None
    assert parse_mcube_dt("0000-00-00 00:00:00") is None
    assert parse_mcube_dt("not-a-date") is None


def test_parse_duration_seconds_and_hms():
    assert parse_duration("193") == 193
    assert parse_duration(193) == 193
    assert parse_duration("00:00:04") == 4
    assert parse_duration("01:02:03") == 3723
    assert parse_duration("") is None
    assert parse_duration(None) is None


def test_normalize_inbound_dialstatus():
    assert normalize_inbound_dialstatus("ANSWER") == ("ANSWERED", True)
    assert normalize_inbound_dialstatus("NoAnswer") == ("NO_ANSWER", False)
    assert normalize_inbound_dialstatus("Executive Busy") == ("BUSY_AGENT", False)
    assert normalize_inbound_dialstatus("Busy") == ("BUSY_CUSTOMER", False)
    assert normalize_inbound_dialstatus("CANCEL") == ("CANCELLED", False)
    assert normalize_inbound_dialstatus("weird") == ("UNKNOWN", False)
    assert is_missed_status("NO_ANSWER") is True
    assert is_missed_status("ANSWERED") is False


def test_redact_apikey_and_data_wrapper():
    raw = {"callid": "1", "apikey": "secret", "callfrom": "9514452942"}
    red = redact_payload(raw)
    assert red["apikey"] == "[REDACTED]"
    assert red["callfrom"] == "9514452942"

    wrapped = {"data": '{"callid":"abc","CallFrom":"999"}'}
    inner = _maybe_parse_data_wrapper(wrapped)
    assert inner["callid"] == "abc"
    low = lowercase_keys(inner)
    # keys already mixed — lowercase_keys on CallFrom if present at top
    assert lowercase_keys({"CallFrom": "1"})["callfrom"] == "1"
