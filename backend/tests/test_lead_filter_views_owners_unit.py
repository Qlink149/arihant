"""Regression: saved views retain sales_owners + mine."""

from crm.services.lead_filter_views_service import LeadFilterViewFilters


def test_lead_filter_view_keeps_sales_owners_and_mine():
    raw = {
        "statuses": ["RNR"],
        "sales_owners": ["Jigar"],
        "mine": True,
        "search": "test",
        "date_field": "updated",
        "updated_from": "2026-01-01",
        "updated_to": "2026-01-31",
    }
    parsed = LeadFilterViewFilters.model_validate(raw)
    dumped = parsed.model_dump()
    assert dumped["sales_owners"] == ["Jigar"]
    assert dumped["statuses"] == ["RNR"]
    assert dumped["mine"] is True
    assert dumped["search"] == "test"
    assert dumped["date_field"] == "updated"
    assert dumped["updated_from"] == "2026-01-01"
    assert dumped["updated_to"] == "2026-01-31"
