"""Unit tests for bulk-update request validation and role scoping."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

from crm.api.v1.endpoints import leads
from crm.api.v1.endpoints.leads import BulkLeadUpdateRequest, _http_exc_reason


def test_bulk_update_request_accepts_200_ids():
    ids = [f"id-{i}" for i in range(200)]
    req = BulkLeadUpdateRequest(lead_ids=ids, lead_status="Contacted")
    assert len(req.lead_ids) == 200


def test_bulk_update_request_rejects_over_200_ids():
    ids = [f"id-{i}" for i in range(201)]
    with pytest.raises(ValidationError):
        BulkLeadUpdateRequest(lead_ids=ids, lead_status="Contacted")


def test_bulk_update_request_requires_lead_ids():
    with pytest.raises(ValidationError):
        BulkLeadUpdateRequest(lead_ids=[], lead_status="Contacted")


def test_http_exc_reason_string():
    assert _http_exc_reason(HTTPException(status_code=400, detail="bad")) == "bad"


def test_http_exc_reason_non_string():
    assert "x" in _http_exc_reason(HTTPException(status_code=400, detail={"x": 1}))


# batch1 #33: general_manager bulk-update is scoped to escalated leads only.


def _escalated_lead(lead_id):
    return {"id": lead_id, "escalation": {"active": True}}


def _non_escalated_lead(lead_id):
    return {"id": lead_id, "escalation": {"active": False}}


def _find_returning(docs):
    """Mock db.leads.find(...).to_list(n) returning the given docs."""
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=docs)
    return MagicMock(return_value=cursor)


@pytest.mark.asyncio
async def test_gm_bulk_update_all_escalated_succeeds(monkeypatch):
    mock_db = MagicMock()
    mock_db.leads.find = _find_returning([_escalated_lead("L1"), _escalated_lead("L2")])
    mock_db.leads.find_one = AsyncMock(side_effect=[_escalated_lead("L1"), _escalated_lead("L2")])
    monkeypatch.setattr(leads, "db", mock_db)
    monkeypatch.setattr(leads.lead_service, "update_lead", AsyncMock())
    monkeypatch.setattr(leads, "schedule_lead_ai_refresh", MagicMock())

    req = BulkLeadUpdateRequest(lead_ids=["L1", "L2"], lead_status="Contacted")
    result = await leads.bulk_update_leads(
        req, BackgroundTasks(), {"role": "general_manager", "id": "gm1", "full_name": "Shariff"}
    )
    assert result["updated"] == ["L1", "L2"]
    assert result["failed"] == []


@pytest.mark.asyncio
async def test_gm_bulk_update_rejects_whole_request_if_any_not_escalated(monkeypatch):
    """One non-escalated lead in the batch must reject everything - never a
    silent partial skip - and name the offending id."""
    mock_db = MagicMock()
    mock_db.leads.find = _find_returning([_escalated_lead("L1"), _non_escalated_lead("L2")])
    monkeypatch.setattr(leads, "db", mock_db)
    update_lead = AsyncMock()
    monkeypatch.setattr(leads.lead_service, "update_lead", update_lead)

    req = BulkLeadUpdateRequest(lead_ids=["L1", "L2"], lead_status="Contacted")
    with pytest.raises(HTTPException) as exc:
        await leads.bulk_update_leads(
            req, BackgroundTasks(), {"role": "general_manager", "id": "gm1", "full_name": "Shariff"}
        )
    assert exc.value.status_code == 403
    assert "L2" in exc.value.detail
    update_lead.assert_not_awaited()  # nothing touched, not even L1


@pytest.mark.asyncio
async def test_gm_bulk_update_rejects_unknown_lead_id(monkeypatch):
    """A lead id that doesn't exist can't be verified as escalated - reject."""
    mock_db = MagicMock()
    mock_db.leads.find = _find_returning([_escalated_lead("L1")])  # L2 not found
    monkeypatch.setattr(leads, "db", mock_db)
    update_lead = AsyncMock()
    monkeypatch.setattr(leads.lead_service, "update_lead", update_lead)

    req = BulkLeadUpdateRequest(lead_ids=["L1", "L2"], lead_status="Contacted")
    with pytest.raises(HTTPException) as exc:
        await leads.bulk_update_leads(
            req, BackgroundTasks(), {"role": "general_manager", "id": "gm1", "full_name": "Shariff"}
        )
    assert exc.value.status_code == 403
    assert "L2" in exc.value.detail
    update_lead.assert_not_awaited()


@pytest.mark.asyncio
async def test_rep_still_denied_bulk_update():
    with pytest.raises(HTTPException) as exc:
        await leads.bulk_update_leads(
            BulkLeadUpdateRequest(lead_ids=["L1"], lead_status="Contacted"),
            BackgroundTasks(),
            {"role": "rep", "id": "r1", "full_name": "Rep"},
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_bulk_update_unaffected_by_gm_scoping(monkeypatch):
    """Admin/manager behavior must be unchanged - no escalation check at all."""
    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value=_non_escalated_lead("L1"))
    mock_db.leads.find = MagicMock(side_effect=AssertionError("admin path must not query escalation state"))
    monkeypatch.setattr(leads, "db", mock_db)
    monkeypatch.setattr(leads.lead_service, "update_lead", AsyncMock())
    monkeypatch.setattr(leads, "schedule_lead_ai_refresh", MagicMock())

    req = BulkLeadUpdateRequest(lead_ids=["L1"], lead_status="Contacted")
    result = await leads.bulk_update_leads(
        req, BackgroundTasks(), {"role": "admin", "id": "a1", "full_name": "Admin"}
    )
    assert result["updated"] == ["L1"]
