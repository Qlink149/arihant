"""Tests for context_updates deduplication."""
from datetime import datetime, timezone

from crm.services.context_updates import dedupe_context_updates, normalize_description


def test_normalize_description_collapses_whitespace_and_punctuation():
    assert normalize_description("  Hello   World  ") == "hello world"
    assert normalize_description("[2026-05-03] Hello World??") == "hello world"
    assert normalize_description("Hello-World!! ") == "hello world"


def test_dedupe_same_description_keeps_newest():
    older = {
        "type": "note",
        "agent": "freshworks",
        "description": "Not answering , dropping message via WA",
        "timestamp": "2024-04-22T00:00:00+00:00",
        "timestamp_dt": datetime(2024, 4, 22, 0, 0, tzinfo=timezone.utc),
    }
    newer = {
        "type": "note",
        "agent": "freshworks",
        "description": "Not answering , dropping message via WA",
        "timestamp": "2024-04-22T10:54:00+00:00",
        "timestamp_dt": datetime(2024, 4, 22, 10, 54, tzinfo=timezone.utc),
    }
    result = dedupe_context_updates([older, newer])
    assert len(result) == 1
    assert result[0]["timestamp_dt"] == newer["timestamp_dt"]


def test_dedupe_different_descriptions_keeps_both():
    a = {
        "type": "note",
        "agent": "freshworks",
        "description": "First note",
        "timestamp_dt": datetime(2024, 4, 22, 8, 0, tzinfo=timezone.utc),
    }
    b = {
        "type": "note",
        "agent": "freshworks",
        "description": "Second note",
        "timestamp_dt": datetime(2024, 4, 23, 8, 0, tzinfo=timezone.utc),
    }
    assert len(dedupe_context_updates([a, b])) == 2


def test_dedupe_same_description_different_type_keeps_both():
    note = {
        "type": "note",
        "agent": "freshworks",
        "description": "Same text",
        "timestamp_dt": datetime(2024, 4, 22, 8, 0, tzinfo=timezone.utc),
    }
    call = {
        "type": "call",
        "agent": "freshworks",
        "description": "Same text",
        "timestamp_dt": datetime(2024, 4, 22, 9, 0, tzinfo=timezone.utc),
    }
    result = dedupe_context_updates([note, call])
    assert len(result) == 2
    assert {r["type"] for r in result} == {"note", "call"}


def test_dedupe_by_note_id():
    first = {
        "type": "note",
        "note_id": "123",
        "description": "Version A",
        "timestamp_dt": datetime(2024, 4, 20, 8, 0, tzinfo=timezone.utc),
    }
    second = {
        "type": "note",
        "note_id": "123",
        "description": "Version B",
        "timestamp_dt": datetime(2024, 4, 21, 8, 0, tzinfo=timezone.utc),
    }
    result = dedupe_context_updates([first, second])
    assert len(result) == 1
    assert result[0]["description"] == "Version B"


def test_dedupe_same_description_different_agent_keeps_both():
    older = {
        "type": "note",
        "agent": "freshsales",
        "description": "Same text content",
        "timestamp_dt": datetime(2024, 4, 22, 8, 0, tzinfo=timezone.utc),
    }
    newer = {
        "type": "note",
        "agent": "freshworks",
        "description": "Same text content",
        "timestamp_dt": datetime(2024, 4, 22, 10, 0, tzinfo=timezone.utc),
    }
    result = dedupe_context_updates([older, newer])
    assert len(result) == 2
    assert {r["agent"] for r in result} == {"freshsales", "freshworks"}


def test_dedupe_output_sorted_newest_first():
    a = {
        "type": "note",
        "agent": "freshworks",
        "description": "First note",
        "timestamp_dt": datetime(2024, 4, 22, 8, 0, tzinfo=timezone.utc),
    }
    b = {
        "type": "task",
        "agent": "rep",
        "description": "Follow up",
        "timestamp_dt": datetime(2024, 4, 25, 8, 0, tzinfo=timezone.utc),
    }
    c = {
        "type": "created",
        "agent": "system",
        "description": "Lead created",
        "timestamp_dt": datetime(2024, 4, 1, 8, 0, tzinfo=timezone.utc),
    }
    result = dedupe_context_updates([c, a, b])
    timestamps = [e["timestamp_dt"] for e in result]
    assert timestamps == sorted(timestamps, reverse=True)
