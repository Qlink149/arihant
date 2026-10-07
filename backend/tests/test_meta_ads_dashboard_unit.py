"""Unit tests for the Meta Ads dashboard overhaul: aggregation rules
(crm/services/meta_ads_queries.py), entity persistence in the sync, the new
admin-only endpoints and the seed-row cleanup script."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from crm.api.v1.endpoints import meta_ads
from crm.services import meta_ads_queries as q
from crm.services import meta_ads_sync_service as svc

ADMIN = {"id": "u1", "full_name": "Admin Ana", "role": "admin"}
REP = {"id": "u2", "full_name": "Rep Rita", "role": "rep"}


# ------------------------------------------------------------------ ranges
def test_parse_range_defaults_to_trailing_30_days():
    f, t = q.parse_range(None, None, today=date(2026, 10, 7))
    assert (f, t) == ("2026-09-08", "2026-10-07")


@pytest.mark.parametrize(
    "f,t",
    [("2026-10-08", "2026-10-07"), ("nope", None), (None, "2026-13-40"), ("2020-01-01", "2026-10-07")],
)
def test_parse_range_rejects_bad_ranges(f, t):
    with pytest.raises(q.RangeError):
        q.parse_range(f, t, today=date(2026, 10, 7))


def test_previous_period_is_equally_long_and_adjacent():
    assert q.previous_period("2026-10-01", "2026-10-07") == ("2026-09-24", "2026-09-30")
    assert q.previous_period("2026-10-07", "2026-10-07") == ("2026-10-06", "2026-10-06")


# ------------------------------------------------------------------ ratios
def test_with_ratios_recomputed_from_sums():
    r = q.with_ratios({"spend": 1000, "impressions": 50000, "clicks": 500, "leads": 20})
    assert r["ctr"] == 1.0  # 500/50000 %
    assert r["cpm"] == 20.0  # 1000/50000*1000
    assert r["cpc"] == 2.0
    assert r["cpl"] == 50.0


def test_with_ratios_zero_denominators_are_none_not_error():
    r = q.with_ratios({"spend": 100, "impressions": 0, "clicks": 0, "leads": 0})
    assert r["ctr"] is None and r["cpm"] is None and r["cpc"] is None and r["cpl"] is None
    assert q.with_ratios({})["spend"] == 0


def test_ratio_is_not_the_average_of_row_ratios():
    a = q.with_ratios({"spend": 100, "leads": 1})  # cpl 100
    b = q.with_ratios({"spend": 100, "leads": 9})  # cpl 11.11
    merged = q.with_ratios({"spend": 200, "leads": 10})
    assert merged["cpl"] == 20.0
    assert merged["cpl"] != round((a["cpl"] + b["cpl"]) / 2, 2)


def test_pct_change():
    assert q.pct_change(150, 100) == 50.0
    assert q.pct_change(50, 100) == -50.0
    assert q.pct_change(10, 0) is None
    assert q.pct_change(None, 5) is None


# ---------------------------------------------------------------- matching
def test_project_clause_variants():
    assert q.project_clause([]) is None
    assert q.project_clause(["A"]) == {"resolved_project": {"$in": ["A"]}}
    assert q.project_clause([q.UNASSIGNED_LABEL]) == {"resolved_project": None}
    both = q.project_clause(["A", q.UNASSIGNED_LABEL])
    assert both == {"$or": [{"resolved_project": {"$in": ["A"]}}, {"resolved_project": None}]}


def test_daily_match_scopes_level_dates_and_parents():
    m = q.daily_match("ad", "2026-10-01", "2026-10-07", ["A"], parent_adset_id="S1")
    assert m["level"] == "ad"
    assert m["date"] == {"$gte": "2026-10-01", "$lte": "2026-10-07"}
    assert m["parent_adset_id"] == "S1" and m["resolved_project"] == {"$in": ["A"]}


def test_totals_pipeline_never_includes_reach_or_frequency():
    group = q.totals_pipeline({})[1]["$group"]
    assert set(group) == {"_id", "spend", "impressions", "clicks", "leads"}
    assert "reach" not in q.entity_pipeline({})[2]["$group"]
    assert "frequency" not in q.entity_pipeline({})[2]["$group"]


def test_fill_series_zero_fills_gaps():
    rows = [{"_id": "2026-10-02", "spend": 10, "impressions": 100, "clicks": 1, "leads": 1}]
    out = q.fill_series(rows, "2026-10-01", "2026-10-03")
    assert [d["date"] for d in out] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert out[0]["spend"] == 0 and out[0]["cpl"] is None
    assert out[1]["cpl"] == 10.0


# ------------------------------------------------------ merge/filter/sort
def _entities():
    return {
        "c1": {"entity_id": "c1", "name": "Mira Leads", "effective_status": "ACTIVE", "objective": "OUTCOME_LEADS", "resolved_project": "Anna Nagar - Mira"},
        "c2": {"entity_id": "c2", "name": "Melange (old)", "effective_status": "PAUSED", "resolved_project": "Saligramam - Melange"},
        "c3": {"entity_id": "c3", "name": "Idle One", "effective_status": "ACTIVE", "resolved_project": None},
    }


def _agg():
    return [
        {"_id": "c1", "entity_name": "Mira Leads", "spend": 300, "impressions": 3000, "clicks": 30, "leads": 3, "resolved_project": "Anna Nagar - Mira", "days_with_data": 5},
        {"_id": "c2", "entity_name": "Melange (old)", "spend": 100, "impressions": 1000, "clicks": 5, "leads": 0, "resolved_project": "Saligramam - Melange", "days_with_data": 2},
    ]


def test_merge_entities_joins_status_and_objective():
    rows = {r["entity_id"]: r for r in q.merge_entities(_agg(), _entities())}
    assert rows["c1"]["effective_status"] == "ACTIVE" and rows["c1"]["objective"] == "OUTCOME_LEADS"
    assert rows["c1"]["cpl"] == 100.0 and rows["c2"]["cpl"] is None
    assert "c3" not in rows


def test_merge_entities_include_idle_lists_zero_spend_entities():
    rows = {r["entity_id"]: r for r in q.merge_entities(_agg(), _entities(), include_idle=True)}
    assert rows["c3"]["spend"] == 0 and rows["c3"]["days_with_data"] == 0


def test_merge_entities_idle_respects_project_filter():
    rows = q.merge_entities(_agg(), _entities(), include_idle=True, projects=["Anna Nagar - Mira"])
    assert "c3" not in {r["entity_id"] for r in rows}
    rows = q.merge_entities([], _entities(), include_idle=True, projects=[q.UNASSIGNED_LABEL])
    assert {r["entity_id"] for r in rows} == {"c3"}


def test_merge_entities_without_entity_docs_still_works():
    rows = q.merge_entities(_agg(), {})
    assert rows[0]["name"] == "Mira Leads" and rows[0]["effective_status"] is None


def test_status_group_buckets():
    assert q.status_group("ACTIVE") == "active"
    assert q.status_group("CAMPAIGN_PAUSED") == "paused"
    assert q.status_group(None) == "unknown"


def test_filter_sort_page_status_search_sort_paginate():
    rows = q.merge_entities(_agg(), _entities(), include_idle=True)
    page, total = q.filter_sort_page(rows, status="active")
    assert total == 2 and {r["entity_id"] for r in page} == {"c1", "c3"}
    page, total = q.filter_sort_page(rows, search="melange")
    assert total == 1 and page[0]["entity_id"] == "c2"
    page, _ = q.filter_sort_page(rows, sort_by="spend", sort_dir="asc")
    assert [r["entity_id"] for r in page][0] == "c3"
    page, total = q.filter_sort_page(rows, limit=1, offset=1)
    assert total == 3 and len(page) == 1


def test_search_is_regex_escaped():
    rows = q.merge_entities(_agg(), _entities())
    page, total = q.filter_sort_page(rows, search="(old")  # would be a regex error unescaped
    assert total == 1 and page[0]["entity_id"] == "c2"
    _, total = q.filter_sort_page(rows, search=".*")
    assert total == 0


def test_sort_puts_missing_ratio_last_both_directions():
    rows = q.merge_entities(_agg(), _entities())
    desc, _ = q.filter_sort_page(rows, sort_by="cpl", sort_dir="desc")
    asc, _ = q.filter_sort_page(rows, sort_by="cpl", sort_dir="asc")
    assert desc[-1]["cpl"] is None and asc[-1]["cpl"] is None


def test_unknown_sort_key_falls_back_to_spend():
    rows = q.merge_entities(_agg(), _entities())
    page, _ = q.filter_sort_page(rows, sort_by="$where")
    assert page[0]["entity_id"] == "c1"


def test_limit_is_capped():
    rows = [{"entity_id": str(i), "name": str(i)} for i in range(700)]
    page, total = q.filter_sort_page(rows, limit=10_000)
    assert len(page) == q.MAX_PAGE_LIMIT and total == 700


# ------------------------------------------------------------------ funnel
def test_assemble_funnel_joins_meta_and_crm_without_merging_definitions():
    meta = [
        {"_id": "ECR - Reserve 16", "spend": 1000, "impressions": 10000, "clicks": 100, "leads": 50},
        {"_id": None, "spend": 200, "impressions": 2000, "clicks": 10, "leads": 0},
    ]
    crm = [
        {"_id": "ECR - Reserve 16", "leads": 20, "site_visits": 4, "bookings": 1},
        {"_id": "Only In CRM", "leads": 3, "site_visits": 0, "bookings": 0},
    ]
    out = q.assemble_funnel(meta, crm)
    by = {r["project"]: r for r in out["rows"]}
    r16 = by["ECR - Reserve 16"]
    assert r16["leads"] == 50 and r16["crm_leads"] == 20  # two separate numbers
    assert r16["cost_per_crm_lead"] == 50.0
    assert r16["cost_per_site_visit"] == 250.0
    assert r16["cost_per_booking"] == 1000.0
    assert by[q.UNASSIGNED_LABEL]["cost_per_crm_lead"] is None
    assert by["Only In CRM"]["spend"] == 0 and by["Only In CRM"]["cost_per_crm_lead"] is None
    assert out["totals"]["spend"] == 1200 and out["totals"]["crm_leads"] == 23
    assert out["totals"]["cost_per_crm_lead"] == round(1200 / 23, 2)


def test_attribution_summary():
    crm = [{"leads": 10, "with_campaign_id": 4}, {"leads": 10, "with_campaign_id": 0}]
    assert q.attribution_summary(crm) == {"crm_meta_leads": 20, "with_campaign_id": 4, "coverage_pct": 20.0}
    assert q.attribution_summary([])["coverage_pct"] is None


def test_crm_funnel_pipeline_groups_and_filters():
    pipe = q.crm_funnel_pipeline({"created_at_dt": {"$gte": 1}}, ("Facebook", "Instagram"), "booked", group_key="$campaign_id")
    assert pipe[0]["$match"]["$and"][0] == {"lead_source": {"$in": ["Facebook", "Instagram"]}}
    assert pipe[1]["$group"]["_id"] == "$campaign_id"
    assert {"leads", "site_visits", "bookings", "with_campaign_id"} <= set(pipe[1]["$group"])


# ---------------------------------------------------- entity docs in sync
def test_build_entity_docs_covers_all_levels_and_parents():
    seen = datetime(2026, 10, 7, tzinfo=timezone.utc)
    campaigns = [{"id": "c1", "name": "Mira Leads", "effective_status": "ACTIVE", "objective": "OUTCOME_LEADS"}]
    adsets = [{"id": "s1", "name": "AS", "campaign_id": "c1", "effective_status": "PAUSED"}]
    ads = [{"id": "a1", "name": "AD", "adset_id": "s1", "campaign_id": "c1", "effective_status": "ACTIVE", "creative": {"id": "cr1"}}]
    docs = svc.build_entity_docs("act_1", campaigns, adsets, ads, {"c1": "Anna Nagar - Mira"}, seen)
    by = {(d["level"], d["entity_id"]): d for d in docs}
    assert by[("campaign", "c1")]["objective"] == "OUTCOME_LEADS"
    assert by[("adset", "s1")]["parent_campaign_id"] == "c1" and by[("adset", "s1")]["effective_status"] == "PAUSED"
    ad = by[("ad", "a1")]
    assert ad["parent_adset_id"] == "s1" and ad["creative_id"] == "cr1"
    assert all(d["resolved_project"] == "Anna Nagar - Mira" for d in docs)
    assert all(d["last_seen_at_dt"] == seen for d in docs)


def test_persist_entities_swallows_db_errors(monkeypatch):
    mock_db = MagicMock()
    mock_db.meta_ads_entities.bulk_write = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(svc, "db", mock_db)
    asyncio.run(svc._persist_entities([{"account_id": "a", "level": "campaign", "entity_id": "c1"}]))  # no raise
    mock_db.meta_ads_entities.bulk_write.assert_awaited_once()


def test_persist_entities_upserts_one_op_per_entity(monkeypatch):
    mock_db = MagicMock()
    mock_db.meta_ads_entities.bulk_write = AsyncMock()
    monkeypatch.setattr(svc, "db", mock_db)
    docs = [{"account_id": "a", "level": "campaign", "entity_id": str(i)} for i in range(3)]
    asyncio.run(svc._persist_entities(docs))
    ops = mock_db.meta_ads_entities.bulk_write.await_args.args[0]
    assert len(ops) == 3


# ------------------------------------------------------------- endpoints
NEW_ENDPOINTS = [
    ("get_meta_ads_overview", {}),
    ("get_meta_ads_breakdown", {"level": "campaign", "limit": 10, "offset": 0}),
    ("get_meta_ads_entity_daily", {"level": "campaign", "entity_id": "c1"}),
    ("get_meta_ads_project_funnel", {}),
]


@pytest.mark.parametrize("name,kwargs", NEW_ENDPOINTS)
def test_new_endpoints_reject_non_admin(monkeypatch, name, kwargs):
    monkeypatch.setattr(meta_ads, "db", MagicMock())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(getattr(meta_ads, name)(current_user=REP, **kwargs))
    assert exc.value.status_code == 403


def test_sync_endpoint_rejects_non_admin():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(meta_ads.trigger_meta_ads_sync(MagicMock(), current_user=REP))
    assert exc.value.status_code == 403


def test_breakdown_rejects_bad_level_and_bad_range(monkeypatch):
    monkeypatch.setattr(meta_ads, "db", MagicMock())
    with pytest.raises(HTTPException) as e1:
        asyncio.run(meta_ads.get_meta_ads_breakdown(level="bogus", limit=10, offset=0, current_user=ADMIN))
    assert e1.value.status_code == 400
    with pytest.raises(HTTPException) as e2:
        asyncio.run(
            meta_ads.get_meta_ads_overview(date_from="2026-10-09", date_to="2026-10-01", current_user=ADMIN)
        )
    assert e2.value.status_code == 400


def _cursor(rows):
    c = MagicMock()
    c.to_list = AsyncMock(return_value=rows)
    c.sort = MagicMock(return_value=c)
    return c


def test_overview_uses_campaign_level_only_and_returns_deltas(monkeypatch):
    seen_matches = []

    def agg(pipeline):
        seen_matches.append(pipeline[0]["$match"])
        m = pipeline[0]["$match"]
        if len(pipeline) == 3 or "$sort" in str(pipeline):
            return _cursor([{"_id": "2026-10-01", "spend": 100, "impressions": 1000, "clicks": 10, "leads": 2}])
        total = 200 if m["date"]["$gte"] >= "2026-10-01" else 100
        return _cursor([{"_id": None, "spend": total, "impressions": 2000, "clicks": 20, "leads": 4}])

    mock_db = MagicMock()
    mock_db.meta_ads_daily_metrics.aggregate = MagicMock(side_effect=agg)
    monkeypatch.setattr(meta_ads, "db", mock_db)
    out = asyncio.run(
        meta_ads.get_meta_ads_overview(date_from="2026-10-01", date_to="2026-10-03", current_user=ADMIN)
    )
    assert all(m["level"] == "campaign" for m in seen_matches)
    assert out["current"]["spend"] == 200 and out["previous"]["spend"] == 100
    assert out["deltas"]["spend"] == 100.0
    assert out["current"]["cpl"] == 50.0
    assert [d["date"] for d in out["series"]] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert (out["previous_from"], out["previous_to"]) == ("2026-09-28", "2026-09-30")


def test_sync_endpoint_not_configured(monkeypatch):
    import crm.core.state as state

    monkeypatch.setattr(state, "META_ADS_ACCESS_TOKEN", "")
    out = asyncio.run(meta_ads.trigger_meta_ads_sync(MagicMock(), current_user=ADMIN))
    assert out == {"started": False, "reason": "not_configured"}


def test_sync_endpoint_already_running_does_not_queue(monkeypatch):
    import crm.core.state as state

    monkeypatch.setattr(state, "META_ADS_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(state, "META_ADS_ACCOUNT_IDS", ["act_1"])
    mock_db = MagicMock()
    mock_db.cron_locks.find_one = AsyncMock(return_value={"job": "meta_ads_sync"})
    monkeypatch.setattr(meta_ads, "db", mock_db)
    bg = MagicMock()
    out = asyncio.run(meta_ads.trigger_meta_ads_sync(bg, current_user=ADMIN))
    assert out == {"started": False, "reason": "already_running"}
    bg.add_task.assert_not_called()


def test_sync_endpoint_starts_background_task(monkeypatch):
    import crm.core.state as state

    monkeypatch.setattr(state, "META_ADS_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(state, "META_ADS_ACCOUNT_IDS", ["act_1"])
    mock_db = MagicMock()
    mock_db.cron_locks.find_one = AsyncMock(return_value=None)
    monkeypatch.setattr(meta_ads, "db", mock_db)
    bg = MagicMock()
    out = asyncio.run(meta_ads.trigger_meta_ads_sync(bg, current_user=ADMIN))
    assert out == {"started": True}
    bg.add_task.assert_called_once()


def test_last_sync_reports_running(monkeypatch):
    mock_db = MagicMock()
    mock_db.meta_ads_sync_logs.find_one = AsyncMock(return_value={"status": "ok"})
    mock_db.cron_locks.find_one = AsyncMock(return_value={"job": "meta_ads_sync"})
    monkeypatch.setattr(meta_ads, "db", mock_db)
    out = asyncio.run(meta_ads.get_meta_ads_last_sync(current_user=ADMIN))
    assert out == {"status": "ok", "running": True}


# -------------------------------------------------------- seed cleanup
def _load_script():
    path = Path(__file__).resolve().parent.parent / "scripts" / "delete_marketing_seed_rows.py"
    spec = importlib.util.spec_from_file_location("delete_marketing_seed_rows", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeSpends:
    def __init__(self, docs):
        self.docs = list(docs)
        self.delete_filter = None

    def find(self, flt):
        out = [d for d in self.docs if all(d.get(k) == v for k, v in flt.items())]
        c = MagicMock()
        c.to_list = AsyncMock(return_value=out)
        return c

    async def delete_many(self, flt):
        self.delete_filter = flt
        ids = set(flt["_id"]["$in"])
        before = len(self.docs)
        self.docs = [d for d in self.docs if not (d["_id"] in ids and d.get("source") == "seed")]
        return MagicMock(deleted_count=before - len(self.docs))


def _fake_db():
    spends = _FakeSpends(
        [
            {"_id": 1, "source": "seed", "amount": 5},
            {"_id": 2, "source": "seed", "amount": 6},
            {"_id": 3, "source": "manual", "amount": 7},
            {"_id": 4, "amount": 8},
        ]
    )
    db = MagicMock()
    db.marketing_spends = spends
    return db, spends


def test_seed_script_dry_run_changes_nothing(tmp_path):
    script = _load_script()
    db, spends = _fake_db()
    out = asyncio.run(script.delete_seed_rows(db, apply=False, backup_dir=tmp_path))
    assert out["matched"] == 2 and out["deleted"] == 0
    assert len(spends.docs) == 4 and list(tmp_path.iterdir()) == []


def test_seed_script_apply_backs_up_then_deletes_only_seed(tmp_path):
    script = _load_script()
    db, spends = _fake_db()
    out = asyncio.run(script.delete_seed_rows(db, apply=True, backup_dir=tmp_path))
    assert out["deleted"] == 2
    assert {d["_id"] for d in spends.docs} == {3, 4}  # manual + legacy rows survive
    backup = json.loads(Path(out["backup_file"]).read_text(encoding="utf-8"))
    assert {d["_id"] for d in backup} == {1, 2}
    assert spends.delete_filter["source"] == "seed"


def test_seed_script_apply_with_no_seed_rows_is_a_noop(tmp_path):
    script = _load_script()
    db = MagicMock()
    db.marketing_spends = _FakeSpends([{"_id": 9, "source": "manual"}])
    out = asyncio.run(script.delete_seed_rows(db, apply=True, backup_dir=tmp_path))
    assert out["matched"] == 0 and out["deleted"] == 0 and out["backup_file"] is None
