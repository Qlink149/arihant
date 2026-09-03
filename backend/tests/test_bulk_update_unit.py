"""Unit tests for bulk-update request validation."""

import pytest
from pydantic import ValidationError

from crm.api.v1.endpoints.leads import BulkLeadUpdateRequest, _http_exc_reason
from fastapi import HTTPException


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
