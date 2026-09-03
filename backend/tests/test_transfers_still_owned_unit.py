"""Unit tests for #50: Received transfers = still assigned to current user."""
from unittest.mock import MagicMock

import pytest

from crm.services import transfer_queries


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for doc in self._docs:
            yield doc


@pytest.mark.asyncio
async def test_still_owned_lead_ids_returns_ids_from_rep_lead_filter(monkeypatch):
    mock_db = MagicMock()
    docs = [{"id": "lead-1"}, {"id": "lead-2"}, {"id": ""}, {}]
    mock_db.leads.find = MagicMock(return_value=_FakeCursor(docs))
    monkeypatch.setattr(transfer_queries, "db", mock_db)

    ids = await transfer_queries.still_owned_lead_ids("uid-1", "Rep One")
    assert ids == ["lead-1", "lead-2"]


def test_still_owned_filter_empty_list_never_matches():
    filt = transfer_queries.still_owned_filter([])
    assert filt == {"lead_id": {"$in": ["__none__"]}}


def test_still_owned_filter_nonempty_list():
    filt = transfer_queries.still_owned_filter(["lead-1", "lead-2"])
    assert filt == {"lead_id": {"$in": ["lead-1", "lead-2"]}}


@pytest.mark.asyncio
async def test_incoming_transfer_filter_still_owned_intersects_base_and_owned(monkeypatch):
    mock_db = MagicMock()
    mock_db.leads.find = MagicMock(return_value=_FakeCursor([{"id": "lead-9"}]))
    monkeypatch.setattr(transfer_queries, "db", mock_db)

    filt = await transfer_queries.incoming_transfer_filter_still_owned(
        "Rep One", "uid-1", is_manager=False
    )
    assert "$and" in filt
    base, owned = filt["$and"]
    assert "to_user_id" in str(base) or "$or" in str(base)  # incoming_transfer_filter clauses
    assert owned == {"lead_id": {"$in": ["lead-9"]}}


@pytest.mark.asyncio
async def test_incoming_transfer_filter_still_owned_no_current_leads_matches_nothing(monkeypatch):
    mock_db = MagicMock()
    mock_db.leads.find = MagicMock(return_value=_FakeCursor([]))
    monkeypatch.setattr(transfer_queries, "db", mock_db)

    filt = await transfer_queries.incoming_transfer_filter_still_owned(
        "Rep One", "uid-1", is_manager=False
    )
    _, owned = filt["$and"]
    assert owned == {"lead_id": {"$in": ["__none__"]}}
