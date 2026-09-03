"""Unit tests for note mentions + assignee notify helpers."""

from crm.services.note_notify import _MENTION_RE


def test_mention_regex_captures_names():
    text = "Hi @Malathy and @Anusha Omprakash please review"
    found = [m.group(1).strip() for m in _MENTION_RE.finditer(text)]
    assert "Malathy" in found
    assert any("Anusha" in f for f in found)
