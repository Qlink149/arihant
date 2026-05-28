"""Unit tests for nurture temperature rules (no database)."""
import pytest
from fastapi import HTTPException

from crm.services.nurture_temperature import apply_nurture_temperature_rules


def test_non_nurturing_clears_temperature():
    patch = {"lead_status": "Contacted", "temperature": "Hot"}
    apply_nurture_temperature_rules({"lead_status": "Nurturing", "temperature": "Hot"}, patch)
    assert patch["temperature"] is None


def test_nurturing_requires_label_on_status_change():
    with pytest.raises(HTTPException) as exc:
        apply_nurture_temperature_rules(
            {"lead_status": "New", "temperature": None},
            {"lead_status": "Nurturing"},
        )
    assert exc.value.status_code == 400


def test_nurturing_accepts_hot_or_warm():
    patch = {"lead_status": "Nurturing", "temperature": "hot"}
    apply_nurture_temperature_rules({}, patch, is_create=True)
    assert patch["temperature"] == "Hot"

    patch2 = {"lead_status": "Nurturing", "temperature": "Warm"}
    apply_nurture_temperature_rules({}, patch2, is_create=True)
    assert patch2["temperature"] == "Warm"


def test_invalid_nurture_label_rejected():
    with pytest.raises(HTTPException) as exc:
        apply_nurture_temperature_rules(
            {"lead_status": "Nurturing"},
            {"temperature": "Cold"},
        )
    assert exc.value.status_code == 400


def test_temperature_on_non_nurturing_rejected():
    with pytest.raises(HTTPException) as exc:
        apply_nurture_temperature_rules(
            {"lead_status": "Contacted"},
            {"temperature": "Hot"},
        )
    assert exc.value.status_code == 400


def test_staying_nurturing_keeps_existing_label():
    patch = {"presales_description": "note"}
    apply_nurture_temperature_rules(
        {"lead_status": "Nurturing", "temperature": "Warm"},
        patch,
    )
    assert patch["temperature"] == "Warm"


def test_create_non_nurturing_defaults_null():
    patch = {"lead_status": "New"}
    apply_nurture_temperature_rules({}, patch, is_create=True)
    assert patch["temperature"] is None
