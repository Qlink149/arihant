"""Unit tests for #53/#54: append-only site visit completion events + report."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from crm.services.site_visit_events import (
    build_site_visit_report,
    build_site_visit_report_filter,
    record_site_visit_event,
    resolve_report_window,
)


# ---------------------------------------------------------------------------
# record_site_visit_event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_site_visit_event_captures_lead_snapshot(monkeypatch):
    mock_db = MagicMock()
    mock_db.site_visit_events.insert_one = AsyncMock()
    import crm.services.site_visit_events as sve

    monkeypatch.setattr(sve, "db", mock_db)

    lead = {
        "first_name": "Priya",
        "last_name": "S",
        "phone": "9876543210",
        "project": "ECR - Reserve 16",
        "projects": ["ECR - Reserve 16"],
        "assigned_user_id": "rep-1",
        "assigned_to_name": "Rep One",
    }
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    actor = {"id": "admin-1", "full_name": "Admin"}

    event_id = await record_site_visit_event("lead-1", lead, actor=actor, completed_at_dt=now)

    assert event_id
    mock_db.site_visit_events.insert_one.assert_awaited_once()
    event = mock_db.site_visit_events.insert_one.call_args[0][0]
    assert event["lead_id"] == "lead-1"
    assert event["completed_at_dt"] == now
    assert event["project"] == "ECR - Reserve 16"
    assert event["projects"] == ["ECR - Reserve 16"]
    assert event["assigned_user_id"] == "rep-1"
    assert event["actor_name"] == "Admin"
    assert event["lead_name"] == "Priya S"
    assert event["phone"] == "9876543210"


@pytest.mark.asyncio
async def test_record_site_visit_event_never_raises_on_db_error(monkeypatch):
    mock_db = MagicMock()
    mock_db.site_visit_events.insert_one = AsyncMock(side_effect=RuntimeError("boom"))
    import crm.services.site_visit_events as sve

    monkeypatch.setattr(sve, "db", mock_db)

    # Must not raise even if the write fails — logging is best-effort.
    event_id = await record_site_visit_event(
        "lead-2", {}, actor={"id": "u1", "full_name": "U"}, completed_at_dt=datetime.now(timezone.utc)
    )
    assert event_id


# ---------------------------------------------------------------------------
# resolve_report_window / build_site_visit_report_filter
# ---------------------------------------------------------------------------

def test_resolve_report_window_month_preset_is_ist_calendar_month():
    now = datetime(2026, 6, 15, 3, 0, 0, tzinfo=timezone.utc)  # ~08:30 IST June 15
    window = resolve_report_window(preset="month", now_dt=now)
    assert window["from"] is not None and window["to"] is not None
    assert window["from"] < window["to"]


def test_resolve_report_window_week_preset():
    now = datetime(2026, 6, 15, 3, 0, 0, tzinfo=timezone.utc)
    window = resolve_report_window(preset="week", now_dt=now)
    assert (window["to"] - window["from"]).days == 7


def test_resolve_report_window_quarter_preset():
    now = datetime(2026, 6, 15, 3, 0, 0, tzinfo=timezone.utc)
    window = resolve_report_window(preset="quarter", now_dt=now)
    assert window["from"] < window["to"]


def test_resolve_report_window_explicit_date_range():
    window = resolve_report_window(date_from="2026-06-01", date_to="2026-06-10")
    assert window["from"] is not None
    assert window["to"] is not None
    assert window["from"] < window["to"]


def test_resolve_report_window_no_args_returns_none_bounds():
    window = resolve_report_window()
    assert window == {"from": None, "to": None}


def test_build_site_visit_report_filter_with_owner_and_window():
    window = resolve_report_window(date_from="2026-06-01", date_to="2026-06-10")
    filt = build_site_visit_report_filter(window=window, sales_owner_id="rep-9")
    assert filt["assigned_user_id"] == "rep-9"
    assert "completed_at_dt" in filt
    assert "$gte" in filt["completed_at_dt"]
    assert "$lt" in filt["completed_at_dt"]


def test_build_site_visit_report_filter_empty_window_no_range_clause():
    filt = build_site_visit_report_filter(window={"from": None, "to": None})
    assert "completed_at_dt" not in filt


# ---------------------------------------------------------------------------
# build_site_visit_report (aggregation)
# ---------------------------------------------------------------------------

class _FakeAggCursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, n):
        return self._rows[:n]


@pytest.mark.asyncio
async def test_build_site_visit_report_groups_by_project(monkeypatch):
    mock_db = MagicMock()
    mock_db.site_visit_events.aggregate = MagicMock(
        return_value=_FakeAggCursor(
            [
                {"_id": {"project": "ECR - Reserve 16", "projects": ["ECR - Reserve 16"]}, "count": 5},
                {"_id": {"project": None, "projects": None}, "count": 2},
            ]
        )
    )
    import crm.services.site_visit_events as sve

    monkeypatch.setattr(sve, "db", mock_db)

    report = await build_site_visit_report(window={"from": None, "to": None})
    assert report["total"] == 7
    assert report["by_project"][0]["project"] == "ECR - Reserve 16"
    assert report["by_project"][0]["count"] == 5


# ---------------------------------------------------------------------------
# Project merge: old spellings fold into the canonical project (same mapping as leads)
# ---------------------------------------------------------------------------

from crm.services.site_visit_events import (  # noqa: E402
    MULTIPLE_PROJECTS_LABEL,
    UNSPECIFIED_LABEL,
    event_project_bucket,
)


@pytest.mark.parametrize(
    "project,projects,expected",
    [
        ("Saligramam Melange", None, "Saligramam - Melange"),
        ("Saligramam - Melange", ["Saligramam - Melange"], "Saligramam - Melange"),
        ("Mélange", None, "Saligramam - Melange"),
        ("Reserve 16", None, "ECR - Reserve 16"),
        ("  reserve   16 ", None, "ECR - Reserve 16"),
        ("Vivriti", None, "OMR - Vivriti"),
        ("Abhiramapuram - Krishna", None, "Abhiramapuram - Krsna"),
        ("Krsna", None, "Abhiramapuram - Krsna"),
        ("OMR - Vivriti; Saligramam Melange", None, MULTIPLE_PROJECTS_LABEL),
        ("OMR - Vivriti;Saligramam Melange", None, MULTIPLE_PROJECTS_LABEL),
        ("Saligramam Melange, OMR - Vivriti", None, MULTIPLE_PROJECTS_LABEL),
        ("Reserve 16; Vivriti", None, MULTIPLE_PROJECTS_LABEL),
        ("Melange", ["Saligramam Melange", "Vivriti"], MULTIPLE_PROJECTS_LABEL),
        # two spellings of the SAME project are one project, not "multiple"
        ("Reserve 16; ECR - Reserve 16", None, "ECR - Reserve 16"),
        (None, None, UNSPECIFIED_LABEL),
        ("", [], UNSPECIFIED_LABEL),
        ("E2E Visit Report Project", None, "E2E Visit Report Project"),  # unmapped names pass through
    ],
)
def test_event_project_bucket(project, projects, expected):
    assert event_project_bucket(project, projects) == expected


@pytest.mark.asyncio
async def test_report_merges_spellings_into_one_bar_per_project(monkeypatch):
    """Mirrors the production distribution (129 events) that showed ~15 bars."""
    raw = [
        ("Saligramam Melange", 48), ("ECR - Reserve 16", 46), (None, 9), ("Reserve 16", 9),
        ("Saligramam - Melange", 3), ("OMR - Vivriti", 2), ("Abhiramapuram - Krishna", 2),
        ("Vivriti", 2), ("OMR - Vivriti; Saligramam Melange", 2), ("OMR - Vivriti;Saligramam Melange", 1),
        ("Krsna", 1), ("Reserve 16; Vivriti", 1), ("M�lange", 1),
        ("Saligramam Melange, OMR - Vivriti", 1), ("OMR - Vivriti; ECR - Reserve 16", 1),
    ]
    mock_db = MagicMock()
    mock_db.site_visit_events.aggregate = MagicMock(
        return_value=_FakeAggCursor([{"_id": {"project": p, "projects": None}, "count": c} for p, c in raw])
    )
    import crm.services.site_visit_events as sve

    monkeypatch.setattr(sve, "db", mock_db)
    report = await build_site_visit_report(window={"from": None, "to": None})
    got = {r["project"]: r["count"] for r in report["by_project"]}
    assert got == {
        "Saligramam - Melange": 52,
        "ECR - Reserve 16": 55,
        "OMR - Vivriti": 4,
        "Abhiramapuram - Krsna": 3,
        MULTIPLE_PROJECTS_LABEL: 6,
        UNSPECIFIED_LABEL: 9,
    }
    assert report["total"] == 129 == sum(got.values())  # merging never loses or double-counts a visit
    names = [r["project"] for r in report["by_project"]]
    assert names[0] == "ECR - Reserve 16"  # sorted by count desc


@pytest.mark.asyncio
async def test_report_groups_on_project_and_projects_fields(monkeypatch):
    mock_db = MagicMock()
    mock_db.site_visit_events.aggregate = MagicMock(return_value=_FakeAggCursor([]))
    import crm.services.site_visit_events as sve

    monkeypatch.setattr(sve, "db", mock_db)
    await build_site_visit_report(window={"from": None, "to": None})
    pipeline = mock_db.site_visit_events.aggregate.call_args.args[0]
    assert pipeline[1]["$group"]["_id"] == {"project": "$project", "projects": "$projects"}


@pytest.mark.asyncio
async def test_new_event_is_stored_with_canonical_project(monkeypatch):
    from unittest.mock import AsyncMock

    import crm.services.site_visit_events as sve

    mock_db = MagicMock()
    mock_db.site_visit_events.insert_one = AsyncMock()
    monkeypatch.setattr(sve, "db", mock_db)
    lead = {"first_name": "A", "project": "Reserve 16", "projects": ["Reserve 16"], "phone": "9"}
    await sve.record_site_visit_event(
        "l1", lead, actor={"id": "u", "full_name": "U"}, completed_at_dt=datetime(2026, 10, 7, tzinfo=timezone.utc)
    )
    ev = mock_db.site_visit_events.insert_one.await_args.args[0]
    assert ev["project"] == "ECR - Reserve 16" and ev["projects"] == ["ECR - Reserve 16"]

    lead2 = {"first_name": "B", "project": "Vivriti; Melange", "phone": "9"}
    await sve.record_site_visit_event(
        "l2", lead2, actor={"id": "u"}, completed_at_dt=datetime(2026, 10, 7, tzinfo=timezone.utc)
    )
    ev2 = mock_db.site_visit_events.insert_one.await_args.args[0]
    assert ev2["project"] == "OMR - Vivriti; Saligramam - Melange"
    assert ev2["projects"] == ["OMR - Vivriti", "Saligramam - Melange"]


# ---------------------------------------------------------------------------
# Backfill script: scripts/normalize_site_visit_event_projects.py
# ---------------------------------------------------------------------------

def _load_backfill():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "normalize_site_visit_event_projects.py"
    spec = importlib.util.spec_from_file_location("normalize_site_visit_event_projects", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeEvents:
    def __init__(self, docs):
        self.docs = [dict(d) for d in docs]

    def find(self, _flt):
        return _FakeAggCursor([dict(d) for d in self.docs])

    async def update_one(self, flt, upd):
        for d in self.docs:
            if d["_id"] == flt["_id"]:
                before = dict(d)
                d.update(upd["$set"])
                return MagicMock(modified_count=1 if d != before else 0)
        return MagicMock(modified_count=0)


def _backfill_db():
    db = MagicMock()
    db.site_visit_events = _FakeEvents(
        [
            {"_id": 1, "project": "Reserve 16", "projects": ["Reserve 16"], "lead_name": "A"},
            {"_id": 2, "project": "Saligramam Melange", "projects": [], "lead_name": "B"},
            {"_id": 3, "project": "ECR - Reserve 16", "projects": ["ECR - Reserve 16"], "lead_name": "C"},  # already canonical
            {"_id": 4, "project": None, "projects": [], "lead_name": "D"},  # no project: untouched
            {"_id": 5, "project": "Vivriti;Melange", "projects": None, "lead_name": "E"},
        ]
    )
    return db


@pytest.mark.asyncio
async def test_backfill_dry_run_writes_nothing(tmp_path):
    script = _load_backfill()
    db = _backfill_db()
    s = await script.normalize_events(db, apply=False, backup_dir=tmp_path)
    assert s["to_change"] == 3 and s["updated"] == 0
    assert db.site_visit_events.docs[0]["project"] == "Reserve 16"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_backfill_apply_backs_up_originals_then_updates_only_project_fields(tmp_path):
    import json
    from pathlib import Path

    script = _load_backfill()
    db = _backfill_db()
    s = await script.normalize_events(db, apply=True, backup_dir=tmp_path)
    assert s["updated"] == 3
    by_id = {d["_id"]: d for d in db.site_visit_events.docs}
    assert by_id[1]["project"] == "ECR - Reserve 16" and by_id[1]["projects"] == ["ECR - Reserve 16"]
    assert by_id[2]["project"] == "Saligramam - Melange"
    assert by_id[5]["project"] == "OMR - Vivriti; Saligramam - Melange"
    assert by_id[3]["project"] == "ECR - Reserve 16"  # untouched
    assert by_id[4]["project"] is None  # untouched
    assert by_id[1]["lead_name"] == "A"  # no other field changed
    backup = json.loads(Path(s["backup_file"]).read_text(encoding="utf-8"))
    assert {d["_id"] for d in backup} == {1, 2, 5}
    assert {d["_id"]: d["project"] for d in backup}[1] == "Reserve 16"  # ORIGINAL value preserved


@pytest.mark.asyncio
async def test_backfill_is_idempotent(tmp_path):
    script = _load_backfill()
    db = _backfill_db()
    await script.normalize_events(db, apply=True, backup_dir=tmp_path)
    again = await script.normalize_events(db, apply=True, backup_dir=tmp_path)
    assert again["to_change"] == 0 and again["updated"] == 0 and again["backup_file"] is None
