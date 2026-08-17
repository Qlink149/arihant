"""Unit tests for Meta Qualified auto-set + CAPI trigger helpers."""

from crm.services.meta_qualified_trigger import (
    is_meta_lead,
    is_qualify_status,
    meta_qualified_became_yes,
    should_auto_set_meta_qualified,
    should_send_qualified_lead_capi,
)


def test_is_meta_lead_facebook_sources():
    assert is_meta_lead({"lead_source": "Facebook Lead Form"}) is True
    assert is_meta_lead({"lead_source": "facebook_ad"}) is True
    assert is_meta_lead({"lead_source": "Facebook Lead Ads"}) is True
    assert is_meta_lead({"original_source": "facebook_ad", "lead_source": "website"}) is True
    assert is_meta_lead({"lead_source": "website"}) is False
    assert is_meta_lead({"lead_source": "instagram"}) is False
    assert is_meta_lead({}) is False
    assert is_meta_lead(None) is False


def test_is_qualify_status():
    assert is_qualify_status("Contacted") is True
    assert is_qualify_status("interested") is True
    assert is_qualify_status("New") is False
    assert is_qualify_status("RNR") is False
    assert is_qualify_status("Site Visit Scheduled") is False


def test_auto_set_from_new_and_rnr():
    lead = {"lead_source": "Facebook Lead Form"}
    assert should_auto_set_meta_qualified(lead, status_changed=True, next_status="Contacted") is True
    assert should_auto_set_meta_qualified(lead, status_changed=True, next_status="Interested") is True
    assert should_auto_set_meta_qualified(lead, status_changed=False, next_status="Contacted") is False
    assert should_auto_set_meta_qualified(lead, status_changed=True, next_status="Nurturing") is False


def test_auto_set_skips_website():
    lead = {"lead_source": "website"}
    assert should_auto_set_meta_qualified(lead, status_changed=True, next_status="Contacted") is False


def test_meta_qualified_became_yes():
    assert meta_qualified_became_yes(None, True) is True
    assert meta_qualified_became_yes(False, True) is True
    assert meta_qualified_became_yes(True, True) is False
    assert meta_qualified_became_yes(True, False) is False
    assert meta_qualified_became_yes(None, False) is False


def test_should_send_capi_meta_only_on_yes_transition():
    meta = {"lead_source": "facebook_ad"}
    web = {"lead_source": "website"}
    assert should_send_qualified_lead_capi(
        meta, previous_meta_qualified=None, next_meta_qualified=True
    ) is True
    assert should_send_qualified_lead_capi(
        meta, previous_meta_qualified=True, next_meta_qualified=True
    ) is False
    assert should_send_qualified_lead_capi(
        web, previous_meta_qualified=None, next_meta_qualified=True
    ) is False
