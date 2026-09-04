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
    assert created["description"] == "Lead created via Zapier (Meta Instant Form) — Mira"
    assert created["project_name"] == "Mira"
    assert created["project_id"] == "mira"
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


def _pushed_ctx(update_doc):
    return update_doc["$push"]["context_updates"]


@pytest.mark.asyncio
async def test_update_existing_overwrites_email_when_different(monkeypatch):
    existing = {
        "id": "lead-1",
        "first_name": "Priya",
        "last_name": "S",
        "email": "old@example.com",
        "phone": "9876543210",
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
            _intake_resub_data(email="new@example.com"),
            "Reserve 16",
            api_key={"project_name": "Reserve 16", "project_id": "reserve-16"},
        )

    main = mock_db.leads.update_one.await_args.args[1]
    assert main["$set"]["email"] == "new@example.com"
    email_change = next(c for c in _pushed_ctx(main)["changes"] if c["field"] == "email")
    assert email_change["from"] == "old@example.com"
    assert email_change["to"] == "new@example.com"


@pytest.mark.asyncio
async def test_update_existing_skips_email_when_same_or_missing(monkeypatch):
    existing = {
        "id": "lead-1",
        "first_name": "Priya",
        "last_name": "S",
        "email": "priya@example.com",
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
            _intake_resub_data(email="Priya@Example.com"),
            "Reserve 16",
            api_key={"project_name": "Reserve 16", "project_id": "reserve-16"},
        )
    same = mock_db.leads.update_one.await_args.args[1]
    assert "email" not in same["$set"]
    assert not any(c["field"] == "email" for c in _pushed_ctx(same)["changes"])

    mock_db.leads.update_one.reset_mock()
    with patch("crm.services.notification_service.create_notification", AsyncMock()):
        await intake._update_existing_submission(
            existing,
            _intake_resub_data(email=None),
            "Reserve 16",
            api_key={"project_name": "Reserve 16", "project_id": "reserve-16"},
        )
    missing = mock_db.leads.update_one.await_args.args[1]
    assert "email" not in missing["$set"]


@pytest.mark.asyncio
async def test_update_existing_never_overwrites_phone(monkeypatch):
    existing = {
        "id": "lead-1",
        "first_name": "Priya",
        "last_name": "S",
        "phone": "+919876543210",
        "normalized_phone": "9876543210",
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
            _intake_resub_data(phone="911111111111"),
            "Reserve 16",
            api_key={"project_name": "Reserve 16", "project_id": "reserve-16"},
        )

    main = mock_db.leads.update_one.await_args.args[1]
    assert "phone" not in main["$set"]
    assert "normalized_phone" not in main["$set"]
    assert not any(c["field"] == "phone" for c in _pushed_ctx(main)["changes"])


@pytest.mark.asyncio
async def test_update_existing_name_trim_equal_is_not_a_change(monkeypatch):
    existing = {
        "id": "lead-1",
        "first_name": "Madhu  ",
        "last_name": "",
        "lead_status": "RNR",
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
            _intake_resub_data(first_name="Madhu", last_name=""),
            "Facebook Lead Form",
            api_key={"project_name": "Reserve 16", "project_id": "reserve-16"},
        )

    main = mock_db.leads.update_one.await_args.args[1]
    assert "first_name" not in main["$set"]
    assert "last_name" not in main["$set"]
    assert not any(c["field"] == "name" for c in _pushed_ctx(main)["changes"])


@pytest.mark.asyncio
async def test_update_existing_logs_new_project_name_in_changes(monkeypatch):
    existing = {
        "id": "lead-1",
        "first_name": "Priya",
        "last_name": "S",
        "lead_status": "Nurturing",
        "project": "ECR - Reserve 16",
        "project_id": "reserve-16",
        "projects": ["ECR - Reserve 16"],
        "project_ids": ["reserve-16"],
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
    ctx = _pushed_ctx(main)
    assert ctx["description"] == "Re-enquiry — added Vivriti"
    proj = next(c for c in ctx["changes"] if c["field"] == "projects")
    assert "ECR - Reserve 16" in proj["from"]
    assert "Vivriti" in proj["to"]


@pytest.mark.asyncio
async def test_update_existing_zapier_meta_resub_description(monkeypatch):
    existing = {
        "id": "lead-1",
        "first_name": "Priya",
        "last_name": "S",
        "lead_status": "Nurturing",
        "project": "ECR - Reserve 16",
        "project_id": "reserve-16",
        "projects": ["ECR - Reserve 16"],
        "project_ids": ["reserve-16"],
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
            "Facebook Lead Form",
            api_key={
                "id": "zapier-meta:vivriti",
                "project_name": "Vivriti",
                "project_id": "vivriti",
                "form_id": "1858929181319661",
            },
        )

    main = mock_db.leads.update_one.await_args.args[1]
    ctx = _pushed_ctx(main)
    assert ctx["description"] == "Meta Instant Form resubmission via Zapier — Vivriti"
    assert ctx["project_name"] == "Vivriti"
    assert ctx["form_id"] == "1858929181319661"


@pytest.mark.asyncio
async def test_update_existing_slug_only_does_not_claim_project_added(monkeypatch):
    existing = {
        "id": "lead-1",
        "first_name": "Priya",
        "last_name": "S",
        "lead_status": "Contacted",
        "project": "ECR - Reserve 16",
        "project_id": None,
        "projects": ["ECR - Reserve 16"],
        "project_ids": [],
    }
    mock_db = MagicMock()
    mock_db.leads.update_one = AsyncMock()
    mock_db.tasks.update_many = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)

    with patch("crm.services.notification_service.create_notification", AsyncMock()):
        await intake._update_existing_submission(
            existing,
            _intake_resub_data(),
            "Facebook Lead Form",
            api_key={"project_name": "ECR - Reserve 16", "project_id": "reserve-16"},
        )

    main = mock_db.leads.update_one.await_args.args[1]
    ctx = _pushed_ctx(main)
    assert ctx["description"] == "Re-enquiry — ECR - Reserve 16 (existing project)"
    assert not any(c["field"] == "projects" for c in ctx["changes"])


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


def test_coerce_consent_common_forms():
    assert intake.coerce_consent(True) is True
    assert intake.coerce_consent("yes") is True
    assert intake.coerce_consent("1") is True
    assert intake.coerce_consent(1) is True
    assert intake.coerce_consent("checked") is True
    assert intake.coerce_consent(False) is False
    assert intake.coerce_consent("no") is False
    assert intake.coerce_consent(0) is False
    assert intake.coerce_consent("maybe") is None


def test_normalize_intake_body_wp_aliases_and_utm_meta():
    body = intake.normalize_intake_body(
        {
            "First Name": "Aiswarya",
            "Last Name": "Naveen",
            "Email": "aiswaryaanaveen@gmail.com",
            "Mobile Number": "+918072565736",
            "Preferred Budget": "45 - 60 Lacs.",
            "Marketing Acceptance": "yes",
            "Source": "fb",
            "Medium": "Instagram_Feed",
            "Campaign": "R-16 - Leads",
            "Content": "Private slice of paradise",
        }
    )
    assert body["first_name"] == "Aiswarya"
    assert body["last_name"] == "Naveen"
    assert body["email"] == "aiswaryaanaveen@gmail.com"
    assert body["phone"] == "+918072565736"
    assert body["budget"] == "45 - 60 Lacs."
    assert body["consent"] is True
    assert body["source"] == "fb"
    assert body["meta"]["utm_source"] == "fb"
    assert body["meta"]["utm_medium"] == "Instagram_Feed"
    assert body["meta"]["utm_campaign"] == "R-16 - Leads"
    assert body["meta"]["utm_content"] == "Private slice of paradise"


def test_validate_accepts_consent_string_yes():
    data = intake.validate_intake_payload(
        {
            "First Name": "A",
            "Email": "a@b.com",
            "Marketing Acceptance": "yes",
        }
    )
    assert data["consent"] is True
    assert data["first_name"] == "A"


def test_contact_fingerprint_no_full_pii():
    fp = intake.contact_fingerprint(
        {"phone": "+918072565736", "email": "aiswaryaanaveen@gmail.com"}
    )
    assert fp is not None
    assert "8072565736" not in fp
    assert "aiswaryaanaveen" not in fp
    assert "phone_last4=5736" in fp
    assert "email_domain=gmail.com" in fp


@pytest.mark.asyncio
async def test_create_new_lead_omits_null_normalized_phone(monkeypatch):
    mock_db = MagicMock()
    mock_db.leads.insert_one = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)

    with patch("crm.services.assignment_router.route_new_lead", new_callable=AsyncMock):
        with patch("crm.services.whatsapp_service.send_lead_ack", new_callable=AsyncMock):
            await intake._create_new_lead(
                {
                    "first_name": "EmailOnly",
                    "last_name": "",
                    "email": "only@example.com",
                    "phone": None,
                    "budget": None,
                    "schedule_visit": None,
                    "consent": True,
                    "meta": None,
                    "intake_spam": False,
                },
                api_key={"project_name": "Reserve 16", "project_id": "reserve-16"},
                source="Reserve 16",
            )
    inserted = mock_db.leads.insert_one.await_args.args[0]
    assert "normalized_phone" not in inserted
    assert inserted.get("phone") is None


@pytest.mark.asyncio
async def test_ingest_duplicate_key_null_phone_soft_dedupes_by_email(monkeypatch):
    """Regression: DuplicateKeyError on null phone must not become HTTP 500."""
    from pymongo.errors import DuplicateKeyError

    intake.reset_rate_limits_for_tests()
    api_key = {
        "id": "key-r16",
        "project_name": "Reserve 16",
        "project_id": "reserve-16",
        "rate_limit_per_min": 60,
    }
    existing = {
        "id": "existing-email",
        "email": "only@example.com",
        "first_name": "Old",
        "last_name": "",
        "lead_status": "Contacted",
        "project": "Reserve 16",
        "project_id": "reserve-16",
    }
    mock_db = MagicMock()
    mock_db.lead_intake_logs.insert_one = AsyncMock()
    mock_db.leads.find_one = AsyncMock(return_value=existing)
    monkeypatch.setattr(intake, "db", mock_db)
    monkeypatch.setattr(intake, "_find_recent_lead", AsyncMock(return_value=None))
    monkeypatch.setattr(
        intake,
        "_create_new_lead",
        AsyncMock(side_effect=DuplicateKeyError("E11000 normalized_phone null")),
    )
    monkeypatch.setattr(
        intake,
        "_update_existing_submission",
        AsyncMock(return_value="existing-email"),
    )

    result, status = await intake.ingest_lead(
        body={"first_name": "New", "email": "only@example.com", "consent": True},
        api_key=api_key,
    )
    assert status == 200
    assert result["deduped"] is True
    assert result["lead_id"] == "existing-email"


@pytest.mark.asyncio
async def test_ingest_duplicate_key_unmerged_returns_409(monkeypatch):
    from pymongo.errors import DuplicateKeyError

    intake.reset_rate_limits_for_tests()
    api_key = {
        "id": "key-1",
        "project_name": "Reserve 16",
        "project_id": "reserve-16",
        "rate_limit_per_min": 60,
    }
    mock_db = MagicMock()
    mock_db.lead_intake_logs.insert_one = AsyncMock()
    mock_db.leads.find_one = AsyncMock(return_value=None)
    monkeypatch.setattr(intake, "db", mock_db)
    monkeypatch.setattr(intake, "_find_recent_lead", AsyncMock(return_value=None))
    monkeypatch.setattr(
        intake,
        "_create_new_lead",
        AsyncMock(side_effect=DuplicateKeyError("E11000")),
    )

    result, status = await intake.ingest_lead(
        body={"first_name": "X", "email": "x@y.com", "consent": True},
        api_key=api_key,
    )
    assert status == 409
    assert result["success"] is False


@pytest.mark.asyncio
async def test_ingest_wp_shaped_payload_dedupes_unqualified_phone(monkeypatch):
    intake.reset_rate_limits_for_tests()
    api_key = {
        "id": "b2c24299-2c3f-48af-aae8-d36b70fae91f",
        "project_name": "Reserve 16",
        "project_id": "reserve-16",
        "rate_limit_per_min": 60,
    }
    existing = {
        "id": "a26eee18",
        "first_name": "Meenakshi",
        "last_name": "Meenakshi",
        "lead_status": "Unqualified",
        "normalized_phone": "8072565736",
        "project": "Reserve 16",
        "project_id": "reserve-16",
    }
    mock_db = MagicMock()
    mock_db.lead_intake_logs.insert_one = AsyncMock()
    monkeypatch.setattr(intake, "db", mock_db)
    # 10s miss, 30d phone hit
    find = AsyncMock(side_effect=[None, existing])
    monkeypatch.setattr(intake, "_find_recent_lead", find)
    monkeypatch.setattr(
        intake,
        "_update_existing_submission",
        AsyncMock(return_value="a26eee18"),
    )
    create = AsyncMock()
    monkeypatch.setattr(intake, "_create_new_lead", create)

    result, status = await intake.ingest_lead(
        body={
            "First Name": "Aiswarya",
            "Last Name": "Naveen",
            "Email": "aiswaryaanaveen@gmail.com",
            "Mobile Number": "+918072565736",
            "Preferred Budget": "45 - 60 Lacs.",
            "Marketing Acceptance": "yes",
            "Source": "fb",
            "Medium": "Instagram_Feed",
            "Campaign": "R-16 - Leads",
        },
        api_key=api_key,
    )
    assert status == 200
    assert result["lead_id"] == "a26eee18"
    create.assert_not_awaited()
    # phone_only 30d merge used normalized phone
    assert find.await_args_list[1].kwargs["phone_only"] is True
