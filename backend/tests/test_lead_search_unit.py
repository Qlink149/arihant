"""Unit tests for lead_search query builder (no database)."""
from crm.services.lead_search import (
    build_exact_phone_lookup_queries,
    build_leads_list_query,
    build_sales_owners_filter,
    build_text_search_clause,
    case_insensitive_regex_or_filter,
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


def test_build_leads_list_query_status_case_insensitive_exact():
    q = build_leads_list_query(status="New")
    parts = q["$and"] if "$and" in q else [q]
    status_part = next(p for p in parts if "lead_status" in p)
    assert status_part["lead_status"]["$regex"] == "^New$"
    assert status_part["lead_status"]["$options"] == "i"


def test_build_leads_list_query_temperature_case_insensitive_exact():
    q = build_leads_list_query(temperature="Hot")
    parts = q["$and"] if "$and" in q else [q]
    temp_part = next(p for p in parts if "temperature" in p)
    assert temp_part["temperature"]["$regex"] == "^Hot$"
    assert temp_part["temperature"]["$options"] == "i"


def test_build_leads_list_query_created_at_range():
    q = build_leads_list_query(
        created_at_from_iso="2026-05-01T00:00:00.000Z",
        created_at_to_iso="2026-05-27T23:59:59.999Z",
    )
    parts = q["$and"] if "$and" in q else [q]
    created_part = next(p for p in parts if "created_at" in p)
    assert created_part["created_at"]["$gte"] == "2026-05-01T00:00:00.000Z"
    assert created_part["created_at"]["$lte"] == "2026-05-27T23:59:59.999Z"


def test_build_leads_list_query_multi_project_or():
    q = build_leads_list_query(projects=["Tower A", "Tower B"])
    parts = q["$and"] if "$and" in q else [q]
    project_part = next(p for p in parts if "$or" in p)
    assert len(project_part["$or"]) == 2
    assert project_part["$or"][0]["project"]["$regex"] == "Tower\\ A"


def test_build_leads_list_query_legacy_single_project():
    q = build_leads_list_query(project="Tower A")
    parts = q["$and"] if "$and" in q else [q]
    project_part = next(p for p in parts if "project" in p)
    assert project_part["project"]["$regex"] == "Tower\\ A"


def test_build_leads_list_query_sources_filter():
    q = build_leads_list_query(sources=["facebook_ad", "website"])
    parts = q["$and"] if "$and" in q else [q]
    source_part = next(p for p in parts if "$or" in p)
    assert len(source_part["$or"]) == 2


def test_build_leads_list_query_meta_qualified_filter():
    q = build_leads_list_query(meta_qualified=True)
    parts = q["$and"] if "$and" in q else [q]
    mq_part = next(p for p in parts if "meta_qualified" in p)
    assert mq_part["meta_qualified"] is True


def test_build_leads_list_query_updated_at_range():
    q = build_leads_list_query(
        updated_at_from_iso="2026-05-01T00:00:00.000Z",
        updated_at_to_iso="2026-05-27T23:59:59.999Z",
    )
    parts = q["$and"] if "$and" in q else [q]
    updated_part = next(p for p in parts if "updated_at" in p)
    assert updated_part["updated_at"]["$gte"] == "2026-05-01T00:00:00.000Z"


def test_build_leads_list_query_site_visit_count_range():
    q = build_leads_list_query(site_visit_min=1, site_visit_max=3)
    parts = q["$and"] if "$and" in q else [q]
    sv_part = next(p for p in parts if "site_visit_count" in p)
    assert sv_part["site_visit_count"]["$gte"] == 1
    assert sv_part["site_visit_count"]["$lte"] == 3


def test_build_text_search_clause_includes_work_phone():
    clause = build_text_search_clause("99999")
    fields = {list(c.keys())[0] if "$expr" not in c else "$expr" for c in clause["$or"]}
    assert "work_phone" in fields
    assert "original_source" in fields


def test_build_leads_list_query_project_and_location_and():
    q = build_leads_list_query(projects=["A", "B"], locations=["Chennai"])
    assert "$and" in q
    project_part = next(p for p in q["$and"] if "$or" in p and "project" in str(p))
    location_part = next(p for p in q["$and"] if "location" in p)
    assert len(project_part["$or"]) == 2
    assert location_part["location"]["$regex"] == "Chennai"


def test_case_insensitive_regex_or_filter_dedupes():
    clause = case_insensitive_regex_or_filter("project", ["A", "a", "B"])
    assert "$or" in clause
    assert len(clause["$or"]) == 2


def test_build_exact_phone_lookup_queries_empty():
    assert build_exact_phone_lookup_queries("") == []
    assert build_exact_phone_lookup_queries("   ") == []


def test_build_exact_phone_lookup_queries_typed_then_normalized():
    queries = build_exact_phone_lookup_queries("+6596161814")
    assert len(queries) >= 1
    # First pass: exact typed phone / work_phone
    first = queries[0]
    assert "$or" in first
    phone_patterns = [c["phone"]["$regex"] for c in first["$or"] if "phone" in c]
    assert "^\\+6596161814$" in phone_patterns
    # Second pass includes normalized_phone last-10
    assert len(queries) >= 2
    second = queries[1]
    assert any(c.get("normalized_phone") == "6596161814" for c in second["$or"])


def test_build_exact_phone_lookup_queries_indian_country_code():
    queries = build_exact_phone_lookup_queries("+919876543210")
    assert queries
    second = queries[1]
    assert any(c.get("normalized_phone") == "9876543210" for c in second["$or"])


def test_build_sales_owners_filter_matches_owner_fields():
    clause = build_sales_owners_filter(["Anusha O"])
    assert "$or" in clause
    fields = {list(c.keys())[0] for c in clause["$or"]}
    assert fields == {"assigned_to", "assigned_to_name", "presales_agent"}
    for part in clause["$or"]:
        field = list(part.keys())[0]
        assert part[field]["$regex"] == "^Anusha\\ O$"
        assert part[field]["$options"] == "i"


def test_build_leads_list_query_sales_owners():
    q = build_leads_list_query(sales_owners=["Rep A", "Rep B"])
    parts = q["$and"] if "$and" in q else [q]
    owner_part = next(p for p in parts if "$or" in p and "assigned_to" in str(p))
    assert len(owner_part["$or"]) == 6  # 2 names × 3 fields


def test_build_leads_list_query_project_id_matches_array():
    q = build_leads_list_query(project_id="reserve-16")
    parts = q["$and"] if "$and" in q else [q]
    clause = next(p for p in parts if "$or" in p and "project_ids" in str(p))
    assert {"project_id": "reserve-16"} in clause["$or"]
    assert {"project_ids": "reserve-16"} in clause["$or"]


def test_build_leads_list_query_re_enquiry():
    q = build_leads_list_query(re_enquiry=True)
    parts = q["$and"] if "$and" in q else [q]
    flag_part = next(p for p in parts if "re_enquiry" in p)
    assert flag_part["re_enquiry"] is True
