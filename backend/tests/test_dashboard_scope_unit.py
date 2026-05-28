"""Unit tests for My Dashboard per-user scope (no database)."""
import asyncio

from crm.services.dashboard_scope import rep_lead_filter, resolve_leads_base_filter
from crm.services.transfer_queries import is_manager_user


def test_rep_lead_filter_includes_user_id():
    filt = rep_lead_filter("uid-1", "Jane Doe")
    assert "$or" in filt
    assert {"assigned_user_id": "uid-1"} in filt["$or"]


def test_rep_lead_filter_name_fields_case_insensitive():
    filt = rep_lead_filter("uid-1", "Jane Doe")
    name_clauses = [c for c in filt["$or"] if "assigned_to_name" in c]
    assert len(name_clauses) == 1
    assert name_clauses[0]["assigned_to_name"]["$options"] == "i"
    assert name_clauses[0]["assigned_to_name"]["$regex"] == "^Jane\\ Doe$"


def test_rep_lead_filter_never_empty_or_clause():
    filt = rep_lead_filter("uid-1", "Rep")
    assert filt != {}
    assert len(filt["$or"]) >= 1


def test_is_manager_user_rep_with_zero_leads_is_not_manager():
    user = {"role": "rep", "email": "rep@example.com"}
    assert is_manager_user(user, rep_lead_count=0) is False


def test_is_manager_user_admin_is_manager():
    user = {"role": "admin", "email": "admin@example.com"}
    assert is_manager_user(user) is True


def test_is_manager_user_manager_role():
    user = {"role": "manager", "email": "mgr@example.com"}
    assert is_manager_user(user) is True


def test_resolve_leads_base_filter_always_rep_scope():
    admin = {"id": "a1", "full_name": "Admin User", "role": "admin", "email": "a@x.com"}
    base_filter, is_manager = asyncio.run(resolve_leads_base_filter("a1", "Admin User", admin))
    assert is_manager is True
    assert base_filter == rep_lead_filter("a1", "Admin User")
    assert base_filter != {}

    rep = {"id": "r1", "full_name": "Sales Rep", "role": "rep", "email": "r@x.com"}
    base_filter_rep, is_manager_rep = asyncio.run(resolve_leads_base_filter("r1", "Sales Rep", rep))
    assert is_manager_rep is False
    assert base_filter_rep == rep_lead_filter("r1", "Sales Rep")
