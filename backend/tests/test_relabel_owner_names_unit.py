"""scripts/relabel_owner_names.py: Roshini -> Admin label backfill (SOP v3.2 F2/F3)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _load():
    path = Path(__file__).resolve().parent.parent / "scripts" / "relabel_owner_names.py"
    spec = importlib.util.spec_from_file_location("relabel_owner_names", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, _n):
        return [dict(r) for r in self.rows]


def _matches(doc, flt):
    for k, v in flt.items():
        if isinstance(v, dict) and "$nin" in v:
            if doc.get(k) in v["$nin"]:
                return False
        elif doc.get(k) != v:
            return False
    return True


class _Coll:
    def __init__(self, docs):
        self.docs = [dict(d) for d in docs]
        self.updates = []

    def find(self, flt=None, proj=None):
        return _Cursor([d for d in self.docs if _matches(d, flt or {})])

    async def update_one(self, flt, upd):
        for d in self.docs:
            if d["_id"] == flt["_id"]:
                before = dict(d)
                d.update(upd["$set"])
                self.updates.append((flt, upd))
                return MagicMock(modified_count=1 if d != before else 0)
        return MagicMock(modified_count=0)


def _db(users=None):
    db = MagicMock()
    db.users = _Coll(users if users is not None else [
        {"_id": "U1", "id": "admin-id", "full_name": "Admin", "email": "roshni@arihantspaces.com"},
        {"_id": "U2", "id": "jigar-id", "full_name": "jigar"},
    ])
    db.leads = _Coll([
        # Roshini-labelled and owned by Admin: to be relabelled
        {"_id": 1, "id": "l1", "assigned_user_id": "admin-id", "assigned_to": "Roshini", "assigned_to_name": "Roshini", "presales_agent": "Roshini", "updated_at": "T0", "updated_at_dt": "T0"},
        # already Admin: untouched
        {"_id": 2, "id": "l2", "assigned_user_id": "admin-id", "assigned_to": "Admin", "assigned_to_name": "Admin", "presales_agent": "Admin"},
        # label says Roshini but a DIFFERENT agent owns it: never touched by the Roshini rule
        {"_id": 3, "id": "l3", "assigned_user_id": "jigar-id", "assigned_to": "Roshini", "assigned_to_name": "Roshini", "presales_agent": "Roshini"},
        # mislabeled: label Admin, owner jigar
        {"_id": 4, "id": "l4", "assigned_user_id": "jigar-id", "assigned_to": "Admin", "assigned_to_name": "Admin", "presales_agent": "Admin"},
        # owner id is not a registered user
        {"_id": 5, "id": "l5", "assigned_user_id": "ghost-id", "assigned_to": "Admin", "assigned_to_name": "Admin", "presales_agent": "Admin"},
    ])
    db.tasks = _Coll([
        {"_id": 10, "id": "t1", "assigned_user_id": "admin-id", "assigned_to": "Roshini", "assigned_to_name": "Roshini", "created_by": "Roshini"},
        {"_id": 11, "id": "t2", "assigned_user_id": "jigar-id", "assigned_to": "Roshini", "assigned_to_name": "Roshini"},
    ])
    return db


@pytest.mark.asyncio
async def test_plan_only_includes_records_owned_by_the_target_account():
    m = _load()
    plan = await m.build_plan(_db(), from_name="Roshini", to_name="Admin", include_mislabeled=False)
    assert [p["id"] for p in plan["leads"]] == ["l1"]
    assert [p["id"] for p in plan["tasks"]] == ["t1"]
    assert plan["mislabeled"] == []
    assert plan["leads"][0]["after"] == {"assigned_to": "Admin", "assigned_to_name": "Admin", "presales_agent": "Admin"}


@pytest.mark.asyncio
async def test_refuses_when_target_name_is_ambiguous():
    m = _load()
    db = _db(users=[{"_id": 1, "id": "a", "full_name": "Admin"}, {"_id": 2, "id": "b", "full_name": "Admin"}])
    with pytest.raises(m.RelabelError):
        await m.build_plan(db, from_name="Roshini", to_name="Admin", include_mislabeled=False)
    with pytest.raises(m.RelabelError):
        await m.build_plan(_db(users=[]), from_name="Roshini", to_name="Admin", include_mislabeled=False)


@pytest.mark.asyncio
async def test_apply_backs_up_then_sets_only_label_fields(tmp_path):
    m = _load()
    db = _db()
    plan = await m.build_plan(db, from_name="Roshini", to_name="Admin", include_mislabeled=False)
    res = await m.apply_plan(db, plan, backup_dir=tmp_path)
    assert res["updated"] == {"leads": 1, "tasks": 1, "mislabeled": 0}

    l1 = next(d for d in db.leads.docs if d["id"] == "l1")
    assert (l1["assigned_to"], l1["assigned_to_name"], l1["presales_agent"]) == ("Admin", "Admin", "Admin")
    assert l1["updated_at"] == "T0" and l1["updated_at_dt"] == "T0"  # activity timestamps never move
    assert next(d for d in db.leads.docs if d["id"] == "l3")["assigned_to"] == "Roshini"  # other owner untouched
    t1 = next(d for d in db.tasks.docs if d["id"] == "t1")
    assert t1["assigned_to"] == "Admin" and t1["created_by"] == "Roshini"  # history field untouched
    for _flt, upd in db.leads.updates + db.tasks.updates:
        assert set(upd) == {"$set"} and not (set(upd["$set"]) - {"assigned_to", "assigned_to_name", "presales_agent"})

    backup = json.loads(Path(res["backup_file"]).read_text(encoding="utf-8"))
    assert backup["leads"] == [{"id": "l1", "before": {"assigned_to": "Roshini", "assigned_to_name": "Roshini", "presales_agent": "Roshini"}}]


@pytest.mark.asyncio
async def test_is_idempotent(tmp_path):
    m = _load()
    db = _db()
    plan = await m.build_plan(db, from_name="Roshini", to_name="Admin", include_mislabeled=False)
    await m.apply_plan(db, plan, backup_dir=tmp_path)
    again = await m.build_plan(db, from_name="Roshini", to_name="Admin", include_mislabeled=False)
    assert not again["leads"] and not again["tasks"]
    res = await m.apply_plan(db, again, backup_dir=tmp_path)
    assert res["backup_file"] is None and res["updated"] == {"leads": 0, "tasks": 0, "mislabeled": 0}


@pytest.mark.asyncio
async def test_mislabeled_is_opt_in_and_only_for_registered_owners(tmp_path):
    m = _load()
    db = _db()
    default = await m.build_plan(db, from_name="Roshini", to_name="Admin", include_mislabeled=False)
    assert default["mislabeled"] == []

    plan = await m.build_plan(db, from_name="Roshini", to_name="Admin", include_mislabeled=True)
    ids = [p["id"] for p in plan["mislabeled"]]
    assert "l4" in ids and "l5" not in ids  # unknown owner id left alone
    assert "l3" in ids  # Roshini-labelled but owned by jigar: label disagrees with the real owner
    l4 = next(p for p in plan["mislabeled"] if p["id"] == "l4")
    assert l4["after"] == {"assigned_to": "jigar", "assigned_to_name": "jigar", "presales_agent": "jigar"}

    await m.apply_plan(db, plan, backup_dir=tmp_path)
    assert next(d for d in db.leads.docs if d["id"] == "l4")["assigned_to_name"] == "jigar"
    assert next(d for d in db.leads.docs if d["id"] == "l5")["assigned_to_name"] == "Admin"
