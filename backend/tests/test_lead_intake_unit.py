"""Unit tests for public lead intake (validation, auth hash, dedupe, rate limit)."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crm.services import api_key_service as keys
from crm.services import lead_intake_service as intake


def test_hash_api_key_stable():
    assert keys.hash_api_key("arihant_abc") == hashlib.sha256(b"arihant_abc").hexdigest()


def test_resolve_project_for_key_melange():
    p = keys.resolve_project_for_key("Mélange")
    assert p["id"] == "melange"
    assert p["name"] == "Mélange"
    assert keys.resolve_project_for_key("melange")["id"] == "melange"


def test_resolve_project_for_key_unknown():
    with pytest.raises(ValueError):
        keys.resolve_project_for_key("Not A Project")


def test_validate_requires_first_name_and_contact():
    with pytest.raises(intake.IntakeValidationError) as exc:
        intake.validate_intake_payload({"consent": True})
    locs = {tuple(e["loc"]) for e in exc.value.errors}
    assert ("first_name",) in locs


def test_validate_requires_consent_present():
    with pytest.raises(intake.IntakeValidationError) as exc:
        intake.validate_intake_payload(
            {"first_name": "A", "email": "a@b.com"}
        )
    assert any(e["loc"] == ["consent"] for e in exc.value.errors)


def test_validate_accepts_consent_false():
    data = intake.validate_intake_payload(
        {"first_name": "A", "email": "a@b.com", "consent": False}
    )
    assert data["consent"] is False


def test_validate_email_or_phone_and_normalizes():
    data = intake.validate_intake_payload(
        {
            "first_name": " Priya ",
            "last_name": " Sharma ",
            "email": " Priya@Example.COM ",
            "phone": "+91 98765-43210",
            "consent": True,
            "meta": {"utm_source": "google", "$bad": "x"},
        }
    )
    assert data["first_name"] == "Priya"
    assert data["last_name"] == "Sharma"
    assert data["email"] == "priya@example.com"
    assert data["phone"] == "919876543210"
    assert data["meta"] == {"utm_source": "google"}
    assert data["intake_spam"] is False


def test_validate_honeypot_marks_spam():
    data = intake.validate_intake_payload(
        {
            "first_name": "Bot",
            "email": "bot@example.com",
            "consent": True,
            "website": "http://spam",
        }
    )
    assert data["intake_spam"] is True


def test_rate_limit_raises():
    intake.reset_rate_limits_for_tests()
    for _ in range(3):
        intake.check_rate_limit("k1", 3)
    with pytest.raises(intake.IntakeRateLimitError):
        intake.check_rate_limit("k1", 3)
    intake.reset_rate_limits_for_tests()


@pytest.mark.asyncio
async def test_ingest_creates_new_lead(monkeypatch):
    intake.reset_rate_limits_for_tests()
    api_key = {
        "id": "key-1",
        "project_name": "Mélange",
        "project_id": "melange",
        "rate_limit_per_min": 60,
    }

    mock_db = MagicMock()
    mock_db.leads.find_one = AsyncMock(return_value=None)
    mock_db.leads.insert_one = AsyncMock()
    mock_db.lead_intake_logs.insert_one = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)

    monkeypatch.setattr(
        intake,
        "_create_new_lead",
        AsyncMock(return_value="new-lead-id"),
    )

    body = {
        "first_name": "Priya",
        "email": "priya@example.com",
        "phone": "919876543210",
        "consent": True,
    }
    result, status = await intake.ingest_lead(body=body, api_key=api_key, ip="1.2.3.4")
    assert status == 201
    assert result == {"success": True, "lead_id": "new-lead-id", "deduped": False}
    mock_db.lead_intake_logs.insert_one.assert_awaited()


@pytest.mark.asyncio
async def test_ingest_dedupes_30d(monkeypatch):
    intake.reset_rate_limits_for_tests()
    api_key = {
        "id": "key-1",
        "project_name": "Mélange",
        "project_id": "melange",
        "rate_limit_per_min": 60,
    }
    existing = {"id": "existing-1", "email": "priya@example.com"}

    mock_db = MagicMock()
    mock_db.lead_intake_logs.insert_one = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)

    # First call: 10s idempotency miss; second: 30d hit
    find = AsyncMock(side_effect=[None, existing])
    monkeypatch.setattr(intake, "_find_recent_lead", find)
    monkeypatch.setattr(
        intake,
        "_update_existing_submission",
        AsyncMock(return_value="existing-1"),
    )
    create = AsyncMock()
    monkeypatch.setattr(intake, "_create_new_lead", create)

    result, status = await intake.ingest_lead(
        body={
            "first_name": "Priya",
            "email": "priya@example.com",
            "consent": True,
        },
        api_key=api_key,
    )
    assert status == 200
    assert result["deduped"] is True
    assert result["lead_id"] == "existing-1"
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_idempotent_10s(monkeypatch):
    intake.reset_rate_limits_for_tests()
    api_key = {
        "id": "key-1",
        "project_name": "Mélange",
        "project_id": "melange",
        "rate_limit_per_min": 60,
    }
    recent = {"id": "recent-1"}

    mock_db = MagicMock()
    mock_db.lead_intake_logs.insert_one = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)
    monkeypatch.setattr(intake, "_find_recent_lead", AsyncMock(return_value=recent))
    update = AsyncMock()
    monkeypatch.setattr(intake, "_update_existing_submission", update)

    result, status = await intake.ingest_lead(
        body={"first_name": "A", "phone": "919999999999", "consent": True},
        api_key=api_key,
    )
    assert status == 200
    assert result["deduped"] is True
    update.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_new_lead_skips_routing_when_spam(monkeypatch):
    mock_db = MagicMock()
    mock_db.leads.insert_one = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)

    with patch("crm.services.assignment_router.route_new_lead", new_callable=AsyncMock) as route:
        with patch("crm.services.whatsapp_service.send_lead_ack", new_callable=AsyncMock) as ack:
            lead_id = await intake._create_new_lead(
                {
                    "first_name": "Bot",
                    "last_name": "",
                    "email": "bot@x.com",
                    "phone": None,
                    "budget": None,
                    "schedule_visit": None,
                    "consent": True,
                    "meta": None,
                    "intake_spam": True,
                },
                api_key={"project_name": "Mélange", "project_id": "melange"},
                source="Mélange",
            )
            assert lead_id
            route.assert_not_awaited()
            ack.assert_not_called()


def test_intake_actor_zapier_meta():
    actor_id, name, created, resub = intake._intake_actor({"id": "zapier-meta:mira"})
    assert actor_id == "system-zapier-meta"
    assert name == "Zapier Meta Lead"
    assert "Zapier" in created
    assert "Zapier" in resub
    _, website, website_created, _ = intake._intake_actor({"id": "some-real-key"})
    assert website == "Website Intake"
    assert website_created == "Lead created via website intake"


@pytest.mark.asyncio
async def test_create_new_lead_zapier_meta_actor(monkeypatch):
    mock_db = MagicMock()
    mock_db.leads.insert_one = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)

    with patch("crm.services.assignment_router.route_new_lead", new_callable=AsyncMock):
        with patch("crm.services.whatsapp_service.send_lead_ack", new_callable=AsyncMock):
            await intake._create_new_lead(
                {
                    "first_name": "Lydia",
                    "last_name": "Robert",
                    "email": "a@b.com",
                    "phone": "999",
                    "budget": None,
                    "schedule_visit": None,
                    "consent": True,
                    "meta": {"via": "zapier"},
                    "intake_spam": False,
                },
                api_key={
                    "id": "zapier-meta:mira",
                    "project_name": "Mira",
                    "project_id": "mira",
                },
                source="Facebook Lead Form",
            )
    inserted = mock_db.leads.insert_one.await_args.args[0]
    created = inserted["context_updates"][0]
    assert created["agent"] == "Zapier Meta Lead"
    assert created["description"] == "Lead created via Zapier (Meta Instant Form)"
    assert created["actor_name"] == "Zapier Meta Lead"
    assert inserted["projects"] == ["Mira"]
    assert inserted["project_ids"] == ["mira"]
    assert inserted["project"] == "Mira"
    assert inserted["project_id"] == "mira"


def test_match_query_phone_only_is_global():
    q = intake._match_query("melange", "a@b.com", "9198", phone_only=True, require_project_id=False)
    assert q == {"normalized_phone": "9198"}


def test_match_query_email_only_is_project_scoped():
    q = intake._match_query("melange", "a@b.com", None, require_project_id=True)
    assert "$and" in q
    assert {"$or": [{"project_id": "melange"}, {"project_ids": "melange"}]} in q["$and"]
    assert {"email": "a@b.com"} in q["$and"]


def test_match_query_10s_same_project_includes_array():
    q = intake._match_query("melange", "a@b.com", "9198", require_project_id=True)
    assert any("project_ids" in str(part) for part in q["$and"])


def _intake_resub_data(**overrides):
    data = {
        "consent": True,
        "first_name": "Priya",
        "last_name": "S",
        "email": "priya@example.com",
        "phone": "919876543210",
        "budget": None,
        "schedule_visit": None,
        "meta": None,
    }
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_ingest_10s_does_not_flag_re_enquiry(monkeypatch):
    intake.reset_rate_limits_for_tests()
    api_key = {
        "id": "key-1",
        "project_name": "Mélange",
        "project_id": "melange",
        "rate_limit_per_min": 60,
    }
    mock_db = MagicMock()
    mock_db.lead_intake_logs.insert_one = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)
    monkeypatch.setattr(intake, "_find_recent_lead", AsyncMock(return_value={"id": "recent-1"}))
    update = AsyncMock()
    monkeypatch.setattr(intake, "_update_existing_submission", update)

    result, status = await intake.ingest_lead(
        body={"first_name": "A", "phone": "919999999999", "consent": True},
        api_key=api_key,
    )
    assert status == 200
    assert result["deduped"] is True
    update.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_30d_phone_merge_is_global(monkeypatch):
    intake.reset_rate_limits_for_tests()
    api_key = {
        "id": "key-1",
        "project_name": "Vivriti",
        "project_id": "vivriti",
        "rate_limit_per_min": 60,
    }
    existing = {"id": "existing-1"}
    mock_db = MagicMock()
    mock_db.lead_intake_logs.insert_one = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)
    find = AsyncMock(side_effect=[None, existing])
    monkeypatch.setattr(intake, "_find_recent_lead", find)
    monkeypatch.setattr(intake, "_update_existing_submission", AsyncMock(return_value="existing-1"))

    await intake.ingest_lead(
        body={"first_name": "Priya", "phone": "919876543210", "consent": True},
        api_key=api_key,
    )
    assert find.await_count == 2
    first, second = find.await_args_list
    assert first.kwargs["require_project_id"] is True
    assert first.kwargs["within_seconds"] == 10
    assert second.kwargs["phone_only"] is True
    assert second.kwargs["require_project_id"] is False


@pytest.mark.asyncio
async def test_ingest_email_only_stays_same_project(monkeypatch):
    intake.reset_rate_limits_for_tests()
    api_key = {
        "id": "key-1",
        "project_name": "Mélange",
        "project_id": "melange",
        "rate_limit_per_min": 60,
    }
    mock_db = MagicMock()
    mock_db.lead_intake_logs.insert_one = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)
    find = AsyncMock(side_effect=[None, None])
    monkeypatch.setattr(intake, "_find_recent_lead", find)
    monkeypatch.setattr(intake, "_create_new_lead", AsyncMock(return_value="new-1"))

    await intake.ingest_lead(
        body={"first_name": "Priya", "email": "priya@example.com", "consent": True},
        api_key=api_key,
    )
    second = find.await_args_list[1]
    assert second.kwargs["require_project_id"] is True
    assert second.kwargs.get("phone_only") is not True
    assert second.kwargs["email"] == "priya@example.com"


@pytest.mark.asyncio
async def test_update_existing_appends_project_without_duplicate_slug(monkeypatch):
    existing = {
        "id": "lead-1",
        "first_name": "Priya",
        "last_name": "S",
        "lead_status": "Contacted",
        "project": "ECR - Reserve 16",
        "project_id": "reserve-16",
        "projects": ["ECR - Reserve 16"],
        "project_ids": ["reserve-16"],
    }
    mock_db = MagicMock()
    mock_db.leads.update_one = AsyncMock()
    mock_db.tasks.update_many = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)

    with patch("crm.services.notification_service.create_notification", AsyncMock()):
        await intake._update_existing_submission(
            existing,
            _intake_resub_data(),
            "Reserve 16",
            api_key={"project_name": "Reserve 16", "project_id": "reserve-16"},
        )

    main = mock_db.leads.update_one.await_args.args[1]
    assert main["$set"]["re_enquiry"] is True
    assert "lead_status" not in main["$set"]
    assert main["$set"]["projects"] == ["ECR - Reserve 16"]
    assert "$addToSet" not in main


@pytest.mark.asyncio
async def test_update_existing_phone_merge_appends_new_project(monkeypatch):
    existing = {
        "id": "lead-1",
        "first_name": "Priya",
        "last_name": "S",
        "lead_status": "Nurturing",
        "project": "ECR - Reserve 16",
        "project_id": "reserve-16",
        "assigned_user_id": "u1",
        "assigned_to_name": "Rep",
    }
    mock_db = MagicMock()
    mock_db.leads.update_one = AsyncMock()
    mock_db.tasks.update_many = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)

    with patch("crm.services.notification_service.create_notification", AsyncMock()):
        await intake._update_existing_submission(
            existing,
            _intake_resub_data(),
            "Vivriti",
            api_key={"project_name": "Vivriti", "project_id": "vivriti"},
        )

    main = mock_db.leads.update_one.await_args.args[1]
    assert main["$set"]["re_enquiry"] is True
    assert "ECR - Reserve 16" in main["$set"]["projects"]
    assert "Vivriti" in main["$set"]["projects"]
    assert "vivriti" in main["$set"]["project_ids"]
    assert "lead_status" not in main["$set"]
    assert main["$set"]["project"].startswith("ECR - Reserve 16")


@pytest.mark.asyncio
async def test_update_existing_closed_lost_reengages_and_creates_task(monkeypatch):
    existing = {
        "id": "lead-1",
        "first_name": "Priya",
        "last_name": "S",
        "lead_status": "Closed Lost",
        "project": "ECR - Reserve 16",
        "project_id": "reserve-16",
        "assigned_user_id": "u1",
        "assigned_to_name": "Rep",
    }
    mock_db = MagicMock()
    mock_db.leads.update_one = AsyncMock()
    mock_db.tasks.update_many = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)
    sla = AsyncMock()

    with patch("crm.services.sla_helpers.create_sla_task_for_lead", sla):
        with patch("crm.services.notification_service.create_notification", AsyncMock()):
            await intake._update_existing_submission(
                existing,
                _intake_resub_data(),
                "Vivriti",
                api_key={"project_name": "Vivriti", "project_id": "vivriti"},
            )

    main = mock_db.leads.update_one.await_args_list[-1].args[1]
    assert main["$set"]["lead_status"] == "Re-engaged"
    assert main["$set"]["re_enquiry"] is True
    sla.assert_awaited()
    mock_db.tasks.update_many.assert_awaited()


@pytest.mark.asyncio
async def test_update_existing_junk_badge_only(monkeypatch):
    existing = {
        "id": "lead-1",
        "first_name": "Priya",
        "last_name": "S",
        "lead_status": "Junk",
        "project": "ECR - Reserve 16",
        "project_id": "reserve-16",
    }
    mock_db = MagicMock()
    mock_db.leads.update_one = AsyncMock()
    mock_db.tasks.update_many = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)
    sla = AsyncMock()

    with patch("crm.services.sla_helpers.create_sla_task_for_lead", sla):
        with patch("crm.services.notification_service.create_notification", AsyncMock()):
            await intake._update_existing_submission(
                existing,
                _intake_resub_data(),
                "Vivriti",
                api_key={"project_name": "Vivriti", "project_id": "vivriti"},
            )

    main = mock_db.leads.update_one.await_args.args[1]
    assert main["$set"]["re_enquiry"] is True
    assert "lead_status" not in main["$set"]
    sla.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_existing_null_submission_count_sets_re_enquiry(monkeypatch):
    existing = {
        "id": "lead-1",
        "first_name": "Madhu  ",
        "last_name": "",
        "lead_status": "RNR",
        "project": "ECR - Reserve 16",
        "project_id": None,
        "projects": ["ECR - Reserve 16"],
        "project_ids": [],
        "submission_count": None,
        "assigned_user_id": "u1",
        "assigned_to_name": "Rep",
    }
    mock_db = MagicMock()
    mock_db.leads.update_one = AsyncMock()
    mock_db.tasks.update_many = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)

    with patch("crm.services.notification_service.create_notification", AsyncMock()):
        await intake._update_existing_submission(
            existing,
            _intake_resub_data(first_name="Madhu  ", last_name=""),
            "Facebook Lead Form",
            api_key={
                "id": "zapier-meta:melange",
                "project_name": "Mélange",
                "project_id": "melange",
            },
        )

    main = mock_db.leads.update_one.await_args.args[1]
    assert "$inc" not in main
    assert main["$set"]["submission_count"] == 1
    assert main["$set"]["re_enquiry"] is True


def test_next_submission_count_null_and_numeric():
    assert intake._next_submission_count({"submission_count": None}) == 1
    assert intake._next_submission_count({}) == 1
    assert intake._next_submission_count({"submission_count": 3}) == 4


@pytest.mark.asyncio
async def test_resolve_api_key_looks_up_hash(monkeypatch):
    plaintext = "arihant_testkey"
    expected_hash = keys.hash_api_key(plaintext)
    mock_db = MagicMock()
    mock_db.api_keys.find_one = AsyncMock(
        return_value={"id": "k1", "key_hash": expected_hash, "is_active": True}
    )
    monkeypatch.setattr(keys, "db", mock_db)

    doc = await keys.resolve_api_key(plaintext)
    assert doc["id"] == "k1"
    mock_db.api_keys.find_one.assert_awaited_once()
    call_q = mock_db.api_keys.find_one.await_args.args[0]
    assert call_q == {"key_hash": expected_hash, "is_active": True}


@pytest.mark.asyncio
async def test_create_api_key_stores_hash_not_plaintext(monkeypatch):
    mock_db = MagicMock()
    mock_db.api_keys.insert_one = AsyncMock()
    monkeypatch.setattr(keys, "db", mock_db)

    result = await keys.create_api_key(
        project_name="Mélange",
        client_name="Melange Website",
        rate_limit_per_min=30,
    )
    assert result["plaintext_key"].startswith("arihant_")
    inserted = mock_db.api_keys.insert_one.await_args.args[0]
    assert "plaintext" not in inserted
    assert inserted["key_hash"] == keys.hash_api_key(result["plaintext_key"])
    assert inserted["project_id"] == "melange"
    assert inserted["rate_limit_per_min"] == 30
