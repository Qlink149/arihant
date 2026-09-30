"""batch2 item 4: CSV import must not write fake calls, and must reject rows
with an unparseable date instead of defaulting to "now"."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import crm.services.lead_service as lead_service
from crm.services.lead_service import import_csv


class _Upload:
    def __init__(self, csv_text: str):
        self._csv_text = csv_text

    async def read(self):
        return self._csv_text.encode("utf-8")


class _DummyLeads:
    def __init__(self):
        self.inserted: list[dict] = []

    async def find_one(self, query, projection=None):
        return None

    async def insert_one(self, doc):
        self.inserted.append(doc)


class _DummyDB:
    def __init__(self):
        self.leads = _DummyLeads()


def _apply_patches(stack: ExitStack, db) -> None:
    stack.enter_context(patch.object(lead_service, "db", db))
    stack.enter_context(patch.object(lead_service, "assert_assignee_allowed", lambda *_a, **_k: None))
    stack.enter_context(patch.object(lead_service, "apply_nurture_temperature_rules", lambda *_a, **_k: None))
    stack.enter_context(patch.object(lead_service, "determine_lead_intent", lambda *_a, **_k: "Unknown"))
    stack.enter_context(patch.object(lead_service, "is_vip_lead", lambda *_a, **_k: False))
    stack.enter_context(patch.object(lead_service, "resolve_user_id_by_full_name", AsyncMock(return_value=None)))
    stack.enter_context(patch.object(lead_service, "resolve_project_id", lambda *_a, **_k: None))


def test_recent_note_imports_as_note_not_call():
    async def _run():
        db = _DummyDB()
        csv_text = (
            "First name,Last Name,Mobile,Status,Recent note\n"
            "Csv,Lead,8888888888,New,Customer asked about pricing"
        )
        with ExitStack() as stack:
            _apply_patches(stack, db)
            result = await import_csv(_Upload(csv_text), {"id": "u1", "full_name": "Admin"})

        assert result["imported"] == 1
        inserted = db.leads.inserted[0]
        note_entries = [c for c in inserted["context_updates"] if c.get("description") == "Customer asked about pricing"]
        assert len(note_entries) == 1
        entry = note_entries[0]
        # The core ask: never type:"call" for a CSV free-text note.
        assert entry["type"] == "note"
        assert entry["type"] != "call"
        assert entry.get("source") == "csv_import"
        # No fabricated call entry exists anywhere in the timeline.
        assert not any(c.get("type") == "call" for c in inserted["context_updates"])

    asyncio.run(_run())


def test_location_column_imports_as_single_item_list():
    """batch3(item4): #51 - location is stored as a list everywhere now, so a
    CSV's single "Location Interested" column becomes a one-item list, not
    a bare scalar string."""
    async def _run():
        db = _DummyDB()
        csv_text = (
            "First name,Last Name,Mobile,Status,Location Interested\n"
            "Csv,Lead,8888888888,New,OMR"
        )
        with ExitStack() as stack:
            _apply_patches(stack, db)
            result = await import_csv(_Upload(csv_text), {"id": "u1", "full_name": "Admin"})

        assert result["imported"] == 1
        assert db.leads.inserted[0]["location"] == ["OMR"]

    asyncio.run(_run())


def test_blank_location_column_omits_field():
    async def _run():
        db = _DummyDB()
        csv_text = "First name,Last Name,Mobile,Status\nCsv,Lead,8888888888,New"
        with ExitStack() as stack:
            _apply_patches(stack, db)
            result = await import_csv(_Upload(csv_text), {"id": "u1", "full_name": "Admin"})

        assert result["imported"] == 1
        assert db.leads.inserted[0]["location"] is None

    asyncio.run(_run())


def test_unparseable_created_at_rejects_row_with_row_number_and_value():
    async def _run():
        db = _DummyDB()
        csv_text = (
            "First name,Last Name,Mobile,Status,Created at\n"
            "Good,Lead,8888888881,New,2026-05-01\n"
            "Bad,Lead,8888888882,New,not-a-real-date\n"
            "AlsoGood,Lead,8888888883,New,2026-05-03\n"
        )
        with ExitStack() as stack:
            _apply_patches(stack, db)
            result = await import_csv(_Upload(csv_text), {"id": "u1", "full_name": "Admin"})

        # Two good rows imported; the bad-date row is rejected, not defaulted to now.
        assert result["imported"] == 2
        assert len(result["errors"]) == 1
        error = result["errors"][0]
        # Row 3 = header (row 1) + first data row (row 2) + this row (row 3).
        assert "Row 3" in error
        assert "not-a-real-date" in error
        imported_names = {d["first_name"] for d in db.leads.inserted}
        assert imported_names == {"Good", "AlsoGood"}
        assert "Bad" not in imported_names

    asyncio.run(_run())


def test_blank_created_at_still_defaults_to_import_time():
    """A blank date is not the same as unparseable - existing behavior for a
    genuinely missing date column value is unchanged."""
    async def _run():
        db = _DummyDB()
        csv_text = "First name,Last Name,Mobile,Status,Created at\nCsv,Lead,8888888884,New,"
        with ExitStack() as stack:
            _apply_patches(stack, db)
            result = await import_csv(_Upload(csv_text), {"id": "u1", "full_name": "Admin"})
        assert result["imported"] == 1
        assert result["errors"] == []

    asyncio.run(_run())


def test_ist_datetime_created_at_stored_correctly():
    """End-to-end: a CSV row with an IST datetime imports with the correctly
    converted UTC created_at, not stamped as UTC directly."""
    async def _run():
        db = _DummyDB()
        csv_text = (
            "First name,Last Name,Mobile,Status,Created at\n"
            "Csv,Lead,8888888885,New,2026-09-25 23:30"
        )
        with ExitStack() as stack:
            _apply_patches(stack, db)
            result = await import_csv(_Upload(csv_text), {"id": "u1", "full_name": "Admin"})
        assert result["imported"] == 1
        inserted = db.leads.inserted[0]
        assert inserted["created_at"].startswith("2026-09-25T18:00:00")

    asyncio.run(_run())
