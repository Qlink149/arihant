"""Unit tests for MCUBE recording URL normalization."""

from crm.services.mcube.calls import map_inbound_fields
from crm.services.mcube.recordings import normalize_mcube_recording_url
from crm.services.mcube.timeline import build_call_timeline_entry


def test_normalize_full_url():
    raw = "https://recordings.mcube.com/mcubefiles110/classic/2026/09/1576/inbound/abc.wav"
    url, filename = normalize_mcube_recording_url(raw)
    assert url == raw
    assert filename == "abc.wav"


def test_normalize_bare_filename():
    raw = "9489356932-20260917153010.wav"
    url, filename = normalize_mcube_recording_url(raw)
    assert url == ""
    assert filename == raw


def test_map_inbound_postman_style_filename():
    mapped = map_inbound_fields(
        {
            "callid": "test-call",
            "callfrom": "9489356932",
            "dialstatus": "ANSWER",
            "duration": "125",
            "endtime": "2026-09-17 15:30:10",
            "filename": "9489356932-20260917153010.wav",
        }
    )
    assert mapped["recording_url"] == ""
    assert mapped["recording_filename"] == "9489356932-20260917153010.wav"
    assert mapped["recording_available"] is True


def test_timeline_entry_no_recording_url_for_bare_filename():
    entry = build_call_timeline_entry(
        call={
            "call_id": "c1",
            "direction": "inbound",
            "status": "ANSWERED",
            "duration_seconds": 125,
            "recording_url": "",
            "recording_filename": "9489356932-20260917153010.wav",
            "customer_number": "9489356932",
        }
    )
    assert entry["recording_url"] == ""
    assert any("(URL not provided)" in kp for kp in entry["key_points"])


def test_timeline_entry_includes_recording_url_for_absolute_link():
    url = "https://recordings.mcube.com/test.wav"
    entry = build_call_timeline_entry(
        call={
            "call_id": "c2",
            "direction": "inbound",
            "status": "ANSWERED",
            "recording_url": url,
            "recording_filename": "test.wav",
        }
    )
    assert entry["recording_url"] == url
    assert any(url in kp for kp in entry["key_points"])
