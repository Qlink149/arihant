"""Edit-note identity: preserve Mongo index through response normalize."""

from crm.services.lead_service import normalize_lead_for_response


def test_normalize_attaches_mongo_index_through_dedupe_sort():
    lead = {
        "strategic_next_moves": [],
        "context_updates": [
            {
                "type": "created",
                "description": "Lead created",
                "timestamp": "2024-01-01T00:00:00Z",
            },
            {
                "type": "note",
                "description": "Older note",
                "timestamp": "2024-06-01T00:00:00Z",
            },
            {
                "type": "note",
                "description": "Newest note",
                "timestamp": "2024-12-01T00:00:00Z",
            },
        ],
    }
    normalize_lead_for_response(lead)
    updates = lead["context_updates"]
    assert updates[0]["description"] == "Newest note"
    assert updates[0]["_mongo_index"] == 2
    assert updates[1]["_mongo_index"] == 1
    assert updates[2]["_mongo_index"] == 0
