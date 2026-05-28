"""Unit tests for transfer query helpers (one-way transfers + since window)."""

from crm.services.transfer_queries import incoming_transfer_filter, outgoing_transfer_filter


def _find_or_list(q: dict) -> list[dict]:
    if "$or" in q:
        return q["$or"]
    if "$and" in q:
        for clause in q["$and"]:
            if isinstance(clause, dict) and "$or" in clause:
                return clause["$or"]
    return []


def _find_clause(or_list: list[dict], field: str) -> dict | None:
    for clause in or_list:
        if field in clause:
            return clause
    return None


def test_incoming_filter_rep_scoped_even_for_manager():
    q = incoming_transfer_filter("Alice", "uid-1", is_manager=True)
    or_list = _find_or_list(q)
    fields = {list(c.keys())[0] for c in or_list}
    assert "to_rep" in fields
    assert "to_user_id" in fields
    assert "to_name" in fields


def test_incoming_filter_uses_case_insensitive_name_regex():
    q = incoming_transfer_filter("Jane Doe", "uid-1", is_manager=False)
    to_rep = _find_clause(_find_or_list(q), "to_rep")
    assert to_rep is not None
    assert to_rep["to_rep"]["$regex"] == "^\\s*Jane\\ Doe\\s*$"
    assert to_rep["to_rep"]["$options"] == "i"


def test_outgoing_filter_rep_scoped_even_for_manager():
    q = outgoing_transfer_filter("Bob", "uid-2", is_manager=True)
    or_list = _find_or_list(q)
    keys = {list(c.keys())[0] for c in or_list}
    assert "from_rep" in keys
    assert "from_name" in keys
    assert "transferred_by" in keys
    assert "transferred_by_user_id" in keys


def test_outgoing_filter_uses_case_insensitive_name_regex():
    q = outgoing_transfer_filter("Bob Smith", "uid-2", is_manager=False)
    or_list = _find_or_list(q)
    from_rep = _find_clause(or_list, "from_rep")
    transferred_by = _find_clause(or_list, "transferred_by")
    assert from_rep is not None
    assert transferred_by is not None
    assert from_rep["from_rep"]["$options"] == "i"
    assert transferred_by["transferred_by"]["$regex"] == "^\\s*Bob\\ Smith\\s*$"
