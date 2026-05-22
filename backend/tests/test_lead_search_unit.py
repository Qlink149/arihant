"""Unit tests for lead_search query builder (no database)."""
from crm.services.lead_search import (
    build_leads_list_query,
    build_text_search_clause,
    escape_regex_literal,
    merge_query,
)


def test_escape_regex_literal():
    assert escape_regex_literal("1-2 Cr") == "1\\-2\\ Cr"


def test_build_text_search_clause_empty():
    assert build_text_search_clause("") == {}
    assert build_text_search_clause("   ") == {}


def test_build_text_search_clause_has_or_and_full_name_expr():
    clause = build_text_search_clause("John")
    assert "$or" in clause
    fields = {list(c.keys())[0] if "$expr" not in c else "$expr" for c in clause["$or"]}
    assert "first_name" in fields
    assert "$expr" in fields


def test_merge_query_single_base():
    assert merge_query({"temperature": "Hot"}) == {"temperature": "Hot"}


def test_merge_query_and_combines_base_and_search():
    base = {"$or": [{"assigned_to": "Rep"}]}
    search = build_text_search_clause("test")
    merged = merge_query(base, search)
    assert "$and" in merged
    assert len(merged["$and"]) == 2


def test_build_leads_list_query_budget_escaped():
    q = build_leads_list_query(budget="1-2 Cr", search="x")
    assert "$and" in q
    budget_part = next(p for p in q["$and"] if "budget" in p)
    assert budget_part["budget"]["$regex"] == "1\\-2\\ Cr"
