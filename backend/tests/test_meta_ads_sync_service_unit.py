"""Unit tests for the daily Meta Ads sync service. No live Meta calls -
_debug_token/_get_paginated are monkeypatched, same pattern test_meta_capi_unit.py
uses for meta_capi_service.py's _post_once."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.services import meta_ads_sync_service as svc


# ---- campaign -> project resolver ----

@pytest.mark.parametrize(
    "name,expected",
    [
        ("Mira Lead Gen", "Anna Nagar - Mira"),
        ("Mira Awareness - Landing Page", "Anna Nagar - Mira"),
        ("Melange-LG-May-2026", "Saligramam - Melange"),
        ("R-16 - Leads", "ECR - Reserve 16"),
        ("Reserve 16 Launch Campaign (Traffic)", "ECR - Reserve 16"),
        ("KRSNA- Leads campaign", "Abhiramapuram - Krsna"),
        ("Instagram post: Vipassana was never meant to...", "Srinagar Colony - Vipassana"),
        ("Instagram post: Arihant Saraswathi is a testament...", "Venus Colony - Saraswathi"),
        ("Instagram post: A peek inside Chirla.", "Poes Garden - Chirla"),
        ("Vilaya - Lead Gen - Nov 2021", "Bangalore - Vilaya"),
        ("Vinyasa - LG - Nov 2021", "Vinyasa"),
        ("Sri Niketan - Lead Gen - Sept 2021", "Sri Niketan"),
        ("Sri Nivas_Calls", "Sri Nivas"),
        ("Greenwood City - Lead Gen - April 2021", "Greenwood City"),
        ("Villa Viviana - Lead Gen - May 2024", "Villa Viviana Plots"),
        ("Tiara - Lead Gen - June 2021", "Tiara"),
        ("Vihaana is more than just...", "Vihaana"),
        ("Ekanta - Lead Gen - July 2021", "Perambur - Ekanta"),
        ("Vivriti Nov '24", "OMR - Vivriti"),
        ("The Bhoomi puja at Chamiers Road...", "Chamiers Road - Project"),
    ],
)
def test_resolve_project_clear_matches(name, expected):
    assert svc.resolve_project_from_campaign_name(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "Instagram post: There is a quiet choreography...",
        "Engagement - Oct 2021",
        "Refer a friend",
        "Design Quote",
        "Post: \"Pongal is an occasion that marks the joy and...\"",
        "",
        None,
    ],
)
def test_resolve_project_no_match_for_generic_campaigns(name):
    assert svc.resolve_project_from_campaign_name(name) is None


def test_resolve_project_no_match_for_discontinued_project_names():
    """Magnolia Woods/Vedant/Escapade/Shloka/Panache aren't in the current
    CRM project list (confirmed in the audit) - must resolve to None, not
    fabricate a guess."""
    for name in ("Magnolia - LG - Dec 2021", "Arihant Vedant is an abode...", "Arihant Escapade"):
        assert svc.resolve_project_from_campaign_name(name) is None


# ---- lead-action summing ----

def test_sum_lead_actions_does_not_double_count():
    """Meta reports the same lead under `lead` (total) AND
    `onsite_conversion.lead_grouped` (subset). Summing both doubled leads on
    live data (325 vs 166) - take `lead`, not the sum."""
    actions = [
        {"action_type": "link_click", "value": "6"},
        {"action_type": "lead", "value": "10"},
        {"action_type": "onsite_conversion.lead_grouped", "value": "7"},
        {"action_type": "post_engagement", "value": "95"},
    ]
    assert svc.sum_lead_actions(actions) == 10


def test_sum_lead_actions_falls_back_to_grouped_when_no_lead_type():
    actions = [{"action_type": "onsite_conversion.lead_grouped", "value": "3"}]
    assert svc.sum_lead_actions(actions) == 3


def test_sum_lead_actions_empty_or_missing():
    assert svc.sum_lead_actions(None) == 0
    assert svc.sum_lead_actions([]) == 0
    assert svc.sum_lead_actions([{"action_type": "video_view", "value": "89"}]) == 0


def test_resolver_requires_whole_keyword():
    assert svc.resolve_project_from_campaign_name("Instagram post: admiration for design") is None
    assert svc.resolve_project_from_campaign_name("Miracle on the ECR") is None
    assert svc.resolve_project_from_campaign_name("Sri Nivas_Calls") == "Sri Nivas"
    assert svc.resolve_project_from_campaign_name("Melange-LG-May-2026") == "Saligramam - Melange"


# ---- token must never reach DB / notifications / logs ----

def test_redact_strips_token(monkeypatch):
    monkeypatch.setattr(svc, "META_ADS_ACCESS_TOKEN", "SECRETTOKEN123")
    msg = "Client error '400' for url 'https://graph.facebook.com/v21.0/debug_token?input_token=SECRETTOKEN123'"
    assert "SECRETTOKEN123" not in svc._redact(msg)
    assert "***" in svc._redact(msg)


def test_sync_failure_never_stores_or_notifies_token_and_releases_lock(monkeypatch):
    token = "SECRETTOKEN123"
    monkeypatch.setattr(svc, "META_ADS_ACCESS_TOKEN", token)
    monkeypatch.setattr(svc, "META_ADS_ACCOUNT_IDS", ["act_1"])
    monkeypatch.setattr(svc, "_acquire_cron_lock", AsyncMock(return_value=True))
    release = AsyncMock()
    monkeypatch.setattr(svc, "_release_cron_lock", release)
    monkeypatch.setattr(
        svc, "_debug_token",
        AsyncMock(side_effect=RuntimeError(f"Client error for url '...debug_token?input_token={token}'")),
    )
    mock_db = MagicMock()
    mock_db.meta_ads_sync_logs.insert_one = AsyncMock()
    monkeypatch.setattr(svc, "db", mock_db)
    notify = AsyncMock()
    monkeypatch.setattr(svc, "_notify_admin", notify)

    result = asyncio.run(svc.sync_daily_meta_ads())

    assert result["ok"] is False
    assert token not in (result["error"] or "")
    logged = mock_db.meta_ads_sync_logs.insert_one.await_args.args[0]
    assert token not in (logged["error_message"] or "")
    assert token not in notify.await_args.kwargs["message"]
    release.assert_awaited_once()


# ---- token expiry flag ----

def test_check_token_expiry_flags_within_window():
    now_dt = datetime.now(timezone.utc)
    soon = now_dt + timedelta(days=3)
    raw = {"expires_at": int((now_dt + timedelta(days=59)).timestamp()), "data_access_expires_at": int(soon.timestamp())}
    result = svc._check_token_expiry(raw, now_dt)
    assert result["expiring_soon"] is True


def test_check_token_expiry_not_flagged_when_far_out():
    now_dt = datetime.now(timezone.utc)
    far = now_dt + timedelta(days=30)
    raw = {"expires_at": int((now_dt + timedelta(days=59)).timestamp()), "data_access_expires_at": int(far.timestamp())}
    result = svc._check_token_expiry(raw, now_dt)
    assert result["expiring_soon"] is False


# ---- sync_daily_meta_ads: not configured / lock / upsert shape ----

def test_sync_skipped_when_not_configured(monkeypatch):
    monkeypatch.setattr(svc, "META_ADS_ACCESS_TOKEN", "")
    monkeypatch.setattr(svc, "META_ADS_ACCOUNT_IDS", [])
    result = asyncio.run(svc.sync_daily_meta_ads())
    assert result == {"ok": False, "skipped": True, "reason": "not_configured"}


def test_sync_skipped_when_lock_held(monkeypatch):
    monkeypatch.setattr(svc, "META_ADS_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(svc, "META_ADS_ACCOUNT_IDS", ["act_1"])
    monkeypatch.setattr(svc, "_acquire_cron_lock", AsyncMock(return_value=False))
    result = asyncio.run(svc.sync_daily_meta_ads())
    assert result == {"skipped": True, "reason": "lock_held"}


def test_sync_one_account_upserts_each_row(monkeypatch):
    """One campaign-level row, one adset-level row, one ad-level row ->
    exactly 3 upserts, each keyed by (account_id, level, entity_id, date),
    with resolved_project copied down from the campaign to its children."""
    mock_leads_update = AsyncMock()
    mock_db = MagicMock()
    mock_db.meta_ads_daily_metrics.update_one = mock_leads_update
    monkeypatch.setattr(svc, "db", mock_db)

    async def fake_get_paginated(client, path, params):
        if path.endswith("/campaigns"):
            return [{"id": "c1", "name": "Mira Lead Gen", "effective_status": "ACTIVE"}]
        if path.endswith("/adsets"):
            return [{"id": "as1", "name": "Broad Interest-HNI", "campaign_id": "c1"}]
        if path.endswith("/ads"):
            return [{"id": "ad1", "name": "Video-Launch", "adset_id": "as1", "campaign_id": "c1", "creative": {"id": "cr1"}}]
        if path.endswith("/insights"):
            level = params.get("level")
            if level == "campaign":
                return [{"campaign_id": "c1", "campaign_name": "Mira Lead Gen", "date_start": "2026-09-24",
                          "spend": "285.16", "impressions": "618", "reach": "471", "clicks": "10",
                          "ctr": "1.6", "cpm": "461.4", "frequency": "1.31", "actions": [{"action_type": "lead", "value": "1"}]}]
            if level == "adset":
                return [{"adset_id": "as1", "adset_name": "Broad Interest-HNI", "date_start": "2026-09-24",
                          "spend": "285.16", "impressions": "618", "reach": "471", "clicks": "10",
                          "ctr": "1.6", "cpm": "461.4", "frequency": "1.31", "actions": [{"action_type": "lead", "value": "1"}]}]
            return [{"ad_id": "ad1", "ad_name": "Video-Launch", "date_start": "2026-09-24",
                      "spend": "216.74", "impressions": "485", "reach": "402", "clicks": "9",
                      "ctr": "1.86", "cpm": "446.9", "frequency": "1.21", "actions": [{"action_type": "lead", "value": "1"}]}]
        return []

    monkeypatch.setattr(svc, "_get_paginated", AsyncMock(side_effect=fake_get_paginated))

    rows = asyncio.run(svc._sync_one_account(MagicMock(), "act_1", "2026-09-24", "2026-09-30"))

    assert rows == 3
    assert mock_leads_update.await_count == 3
    docs = [c.args[1]["$set"] for c in mock_leads_update.await_args_list]
    campaign_doc = next(d for d in docs if d["level"] == "campaign")
    adset_doc = next(d for d in docs if d["level"] == "adset")
    ad_doc = next(d for d in docs if d["level"] == "ad")

    assert campaign_doc["resolved_project"] == "Anna Nagar - Mira"
    assert adset_doc["resolved_project"] == "Anna Nagar - Mira"
    assert adset_doc["parent_campaign_id"] == "c1"
    assert ad_doc["resolved_project"] == "Anna Nagar - Mira"
    assert ad_doc["parent_campaign_id"] == "c1"
    assert ad_doc["parent_adset_id"] == "as1"
    assert ad_doc["creative_id"] == "cr1"
    assert ad_doc["leads"] == 1
    # reach is never summed/derived across levels - each level's own value.
    assert campaign_doc["reach"] == 471
    assert ad_doc["reach"] == 402
