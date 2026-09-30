"""batch3(item4): #51 location accepts both the legacy scalar string and the
new multi-select list, on every schema that carries it, so a client sending
either shape validates and a pre-migration document still reads back fine."""

from datetime import datetime, timezone

from crm.models.schemas.lead_schemas import LeadCreate, LeadResponse, LeadUpdatePatch


def _min_response_kwargs(**overrides):
    now = datetime.now(timezone.utc)
    base = {"id": "lead-1", "first_name": "A", "last_name": "B", "created_at": now, "updated_at": now}
    base.update(overrides)
    return base


def test_lead_response_accepts_list_location():
    lead = LeadResponse(**_min_response_kwargs(location=["OMR", "Anna Nagar"]))
    assert lead.location == ["OMR", "Anna Nagar"]


def test_lead_response_accepts_legacy_scalar_location():
    lead = LeadResponse(**_min_response_kwargs(location="Chennai"))
    assert lead.location == "Chennai"


def test_lead_response_location_optional():
    lead = LeadResponse(**_min_response_kwargs())
    assert lead.location is None


def test_lead_create_accepts_list_location():
    lead = LeadCreate(first_name="A", last_name="B", location=["OMR", "Anna Nagar"])
    assert lead.location == ["OMR", "Anna Nagar"]


def test_lead_update_patch_accepts_list_location():
    patch = LeadUpdatePatch(location=["OMR", "Anna Nagar"])
    assert patch.model_dump(exclude_unset=True)["location"] == ["OMR", "Anna Nagar"]


def test_lead_update_patch_accepts_legacy_scalar_location():
    patch = LeadUpdatePatch(location="Chennai")
    assert patch.model_dump(exclude_unset=True)["location"] == "Chennai"


def test_lead_update_patch_can_clear_location():
    patch = LeadUpdatePatch(location=None)
    assert "location" in patch.model_dump(exclude_unset=True)
    assert patch.model_dump(exclude_unset=True)["location"] is None
