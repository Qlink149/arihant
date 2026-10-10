"""Site Visits report: lead drill-down, walk-ins created as Visit Completed, and the
backfill for the ones missed before."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import crm.services.site_visit_events as sve
from crm.services.site_visit_events import build_site_visit_leads, build_site_visit_report

UTC = timezone.utc
T1 = datetime(2026, 10, 3, 6, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_a, **_k):
        self.rows = sorted(self.rows, key=lambda r: r.get("completed_at_dt") or datetime.min.replace(tzinfo=UTC), reverse=True)
        return self

    async def to_list(self, n):
        return [dict(r) for r in self.rows[: n or None]]


def _events():
    return [
        {"id": "e1", "lead_id": "l1", "completed_at_dt": T1, "project": "Reserve 16", "projects": ["Reserve 16"], "lead_name": "Old Name", "assigned_to_name": "Jigar"},
        {"id": "e2", "lead_id": "l2", "completed_at_dt": T2, "project": "Saligramam Melange", "projects": [], "lead_name": "B"},
        {"id": "e3", "lead_id": "l2", "completed_at_dt": T1, "project": "Saligramam Melange", "projects": [], "lead_name": "B"},  # same lead, 2nd visit
        {"id": "e4", "lead_id": "gone", "completed_at_dt": T2, "project": None, "projects": None, "lead_name": "Deleted Lead"},
    ]


def _db(events=None):
    db = MagicMock()
    db.site_visit_events.find = MagicMock(side_effect=lambda f, p=None: _Cursor(events if events is not None else _events()))
    leads = [
        {"id": "l1", "first_name": "Priya", "last_name": "S", "phone": "9000000001", "lead_status": "Closed Lost", "assigned_to_name": "jigar"},
        {"id": "l2", "first_name": "Ram", "last_name": "K", "phone": "9000000002", "lead_status": "Visit Completed", "assigned_to_name": "Malathy"},
    ]
    db.leads.find = MagicMock(return_value=_Cursor(leads))
    return db


@pytest.mark.asyncio
async def test_leads_list_matches_the_report_total_and_shows_current_status(monkeypatch):
    monkeypatch.setattr(sve, "db", _db())
    win = {"from": None, "to": None}
    rows = await build_site_visit_leads(window=win)
    monkeypatch.setattr(sve, "db", MagicMock(site_visit_events=MagicMock(aggregate=MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[
        {"_id": {"project": e["project"], "projects": e["projects"]}, "count": 1} for e in _events()]))))))
    report = await build_site_visit_report(window=win)
    assert rows["total"] == report["total"] == 4  # the list always adds up to the report
    by_lead = {}
    for v in rows["visits"]:
        by_lead.setdefault(v["lead_id"], []).append(v)
    assert by_lead["l1"][0]["current_status"] == "Closed Lost"
    assert by_lead["l1"][0]["lead_name"] == "Priya S"  # current name, not the one stored on the event
    assert by_lead["l1"][0]["project"] == "ECR - Reserve 16"  # canonical bucket
    assert len(by_lead["l2"]) == 2 and rows["distinct_leads"] == 3  # 4 visits by 3 leads
    assert by_lead["gone"][0]["current_status"] is None  # lead removed: shown, not hidden


@pytest.mark.asyncio
async def test_leads_list_is_newest_first_and_filters_by_project_bucket(monkeypatch):
    monkeypatch.setattr(sve, "db", _db())
    rows = await build_site_visit_leads(window={"from": None, "to": None})
    times = [v["visit_completed_at"] for v in rows["visits"]]
    assert times == sorted(times, reverse=True)
    mel = await build_site_visit_leads(window={"from": None, "to": None}, project="Saligramam - Melange")
    assert mel["total"] == 2 and {v["lead_id"] for v in mel["visits"]} == {"l2"}
    un = await build_site_visit_leads(window={"from": None, "to": None}, project="Unspecified")
    assert un["total"] == 1


@pytest.mark.asyncio
async def test_leads_list_limit_is_capped_but_total_is_not(monkeypatch):
    monkeypatch.setattr(sve, "db", _db())
    rows = await build_site_visit_leads(window={"from": None, "to": None}, limit=1)
    assert len(rows["visits"]) == 1 and rows["total"] == 4


@pytest.mark.asyncio
async def test_a_rep_only_sees_their_own_visits():
    from crm.api.v1.endpoints import analytics

    captured = {}

    async def fake(**kw):
        captured.update(kw)
        return {"total": 0, "distinct_leads": 0, "visits": []}

    orig = analytics.build_site_visit_leads
    analytics.build_site_visit_leads = fake
    try:
        await analytics.get_site_visit_leads(
            preset=None, date_from="2026-10-01", date_to="2026-10-10", sales_owner_id="someone-else", project=None,
            current_user={"id": "rep-1", "role": "rep"},
        )
        assert captured["sales_owner_id"] == "rep-1"
        await analytics.get_site_visit_leads(
            preset=None, date_from=None, date_to=None, sales_owner_id="x", project=None,
            current_user={"id": "adm", "role": "admin"},
        )
        assert captured["sales_owner_id"] == "x"
    finally:
        analytics.build_site_visit_leads = orig


# ---- create_lead logs a walk-in created as Visit Completed ----
async def _create(status):
    import crm.services.lead_service as ls
    from crm.models.schemas.lead_schemas import LeadCreate

    spec = importlib.util.spec_from_file_location("mq_sv", Path(__file__).parent / "test_meta_qualified_update_unit.py")
    mq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mq)
    db, _ = mq._make_db({"id": "unused"})
    patches = mq._patch_lead_service(db)
    mq._enter_all(patches)
    rec = AsyncMock()
    try:
        from unittest.mock import patch

        with patch.object(ls, "record_site_visit_event", rec):
            payload = {"first_name": "Walk", "last_name": "In", "phone": "919999900777", "lead_source": "Direct Walk-in"}
            if status:
                payload["lead_status"] = status
            await ls.create_lead(LeadCreate(**payload), {"id": "u1", "full_name": "Tester"})
    finally:
        mq._stop_all(patches)
    return rec


@pytest.mark.asyncio
async def test_lead_created_as_visit_completed_is_logged():
    rec = await _create("Visit Completed")
    rec.assert_awaited_once()
    assert rec.await_args.args[1]["lead_status"] == "Visit Completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [None, "New", "Contacted", "Site Visit Scheduled", "Interested"])
async def test_other_creation_statuses_are_not_logged(status):
    rec = await _create(status)
    rec.assert_not_awaited()


# ---- backfill script ----
def _script():
    p = Path(__file__).resolve().parent.parent / "scripts" / "backfill_missing_site_visit_events.py"
    spec = importlib.util.spec_from_file_location("backfill_sv", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _lead(i, status, note=False, created=T1, vc=None):
    cu = [{"type": "note", "description": "Status set to Visit Completed"}] if note else []
    return {"id": f"l{i}", "first_name": f"N{i}", "last_name": "", "phone": "9", "lead_status": status, "project": "Reserve 16",
            "projects": ["Reserve 16"], "assigned_user_id": "u", "assigned_to_name": "A", "created_at_dt": created,
            "visit_completed_at_dt": vc, "context_updates": cu}


def test_backfill_qualification_rules():
    m = _script()
    assert m.qualifies(_lead(1, "Visit Completed"))  # in Visit Completed now
    assert m.qualifies(_lead(2, "Closed Lost", note=True))  # later stage WITH evidence
    assert not m.qualifies(_lead(3, "Closed Lost"))  # later stage without evidence: not guessed
    assert not m.qualifies(_lead(4, "New", note=True))
    assert not m.qualifies(_lead(5, "Gone Cold"))


def test_backfill_event_date_and_canonical_project():
    m = _script()
    e = m.build_event(_lead(1, "Visit Completed", created=T2))
    assert e["completed_at_dt"] == T2 and e["backfilled"] is True and e["project"] == "ECR - Reserve 16"
    vc = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)
    assert m.build_event(_lead(1, "Visit Completed", created=T2, vc=vc))["completed_at_dt"] == vc


class _Coll:
    def __init__(self, docs):
        self.docs = [dict(d) for d in docs]
        self.inserted = []

    def find(self, flt=None, proj=None):
        return _Cursor(self.docs)

    async def find_one(self, *_a, **_k):
        return {"completed_at_dt": T2} if self.docs else None

    async def insert_many(self, docs):
        self.inserted.extend(docs)
        self.docs.extend(docs)


@pytest.mark.asyncio
async def test_backfill_apply_backs_up_inserts_once_and_is_idempotent(tmp_path):
    m = _script()
    db = MagicMock()
    db.site_visit_events = _Coll([{"id": "e0", "lead_id": "l9", "completed_at_dt": T2}])
    db.leads = _Coll([_lead(1, "Visit Completed"), _lead(2, "Closed Lost", note=True), _lead(3, "Closed Lost"), _lead(9, "Visit Completed")])
    plan = await m.plan_events(db)
    assert sorted(e["lead_id"] for e in plan) == ["l1", "l2"]  # l9 already has an event, l3 has no evidence
    res = await m.apply_events(db, plan, backup_dir=tmp_path)
    assert res["inserted"] == 2 and len(json.loads(Path(res["backup_file"]).read_text(encoding="utf-8"))) == 2
    assert await m.plan_events(db) == []  # idempotent
    assert (await m.apply_events(db, [], backup_dir=tmp_path))["inserted"] == 0
