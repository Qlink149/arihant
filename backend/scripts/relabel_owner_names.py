#!/usr/bin/env python3
"""
relabel_owner_names.py
======================
SOP v3.2 F2/F3: the Admin account is shown as "Admin" and the assigned agent
(`assigned_user_id`) is the single source of ownership. Leads that still carry the
older owner label "Roshini" belong to the Admin account; this rewrites that stored
LABEL so every list, export and card reads "Admin". No lead is reassigned and no
count changes (counts already go by `assigned_user_id`).

What it changes (only where the record's owner id is the target account):
  leads : assigned_to, assigned_to_name, presales_agent   (label == --from-name)
  tasks : assigned_to, assigned_to_name                   (label == --from-name)
What it NEVER touches: updated_at / updated_at_dt (so "Updated At" and activity
reports do not move), timeline entries, notifications, transfer history, created_by.

Optional --include-mislabeled (off by default): also fixes leads whose stored owner
name disagrees with their real owner (e.g. label "Admin" but assigned_user_id is
another agent) by setting the label to that owner's current name.

Safety: dry run by default; --apply writes a JSON backup of every field it will
change (scripts/static_data/, git-ignored) before updating; idempotent.

Usage
-----
  python scripts/relabel_owner_names.py                          # preview
  python scripts/relabel_owner_names.py --apply                  # Roshini -> Admin
  python scripts/relabel_owner_names.py --include-mislabeled     # preview incl. mislabeled
  python scripts/relabel_owner_names.py --include-mislabeled --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT_DIR / "scripts" / "static_data"
LEAD_LABEL_FIELDS = ("assigned_to", "assigned_to_name", "presales_agent")
TASK_LABEL_FIELDS = ("assigned_to", "assigned_to_name")


class RelabelError(RuntimeError):
    pass


async def resolve_target_user(db: Any, to_name: str) -> dict:
    users = await db.users.find({"full_name": to_name}, {"_id": 0, "id": 1, "full_name": 1, "email": 1}).to_list(5)
    if len(users) != 1:
        raise RelabelError(f"Expected exactly one user named {to_name!r}, found {len(users)} - refusing to guess")
    return users[0]


def _plan_renames(docs: List[dict], fields: tuple, from_name: str, to_name: str) -> List[dict]:
    plan = []
    for d in docs:
        changes = {f: to_name for f in fields if (d.get(f) or "").strip().lower() == from_name.lower()}
        if changes:
            plan.append({"_id": d["_id"], "id": d.get("id"), "before": {f: d.get(f) for f in changes}, "after": changes})
    return plan


async def build_plan(db: Any, *, from_name: str, to_name: str, include_mislabeled: bool) -> Dict[str, Any]:
    target = await resolve_target_user(db, to_name)
    proj = {f: 1 for f in LEAD_LABEL_FIELDS}
    proj.update({"id": 1, "assigned_user_id": 1})
    leads = await db.leads.find({"assigned_user_id": target["id"]}, proj).to_list(None)
    tasks = await db.tasks.find({"assigned_user_id": target["id"]}, {f: 1 for f in (*TASK_LABEL_FIELDS, "id")}).to_list(None)
    plan: Dict[str, Any] = {
        "target": target,
        "leads": _plan_renames(leads, LEAD_LABEL_FIELDS, from_name, to_name),
        "tasks": _plan_renames(tasks, TASK_LABEL_FIELDS, from_name, to_name),
        "mislabeled": [],
    }
    if include_mislabeled:
        names = {u["id"]: u["full_name"] for u in await db.users.find({}, {"_id": 0, "id": 1, "full_name": 1}).to_list(1000)}
        others = await db.leads.find({"assigned_user_id": {"$nin": [target["id"], None, ""]}}, proj).to_list(None)
        for d in others:
            owner_name = names.get(d.get("assigned_user_id"))
            if not owner_name:
                continue  # owner is not a registered user: leave alone
            stale = d.get("assigned_to_name") or d.get("assigned_to")
            if not stale or stale == owner_name:
                continue
            changes = {f: owner_name for f in ("assigned_to", "assigned_to_name") if d.get(f) not in (None, owner_name)}
            # presales_agent only follows when it carried the same stale label
            if d.get("presales_agent") == stale:
                changes["presales_agent"] = owner_name
            if changes:
                plan["mislabeled"].append({"_id": d["_id"], "id": d.get("id"), "before": {f: d.get(f) for f in changes}, "after": changes})
    return plan


async def build_plan(db: Any, *, from_name: str, to_name: str, include_mislabeled: bool) -> Dict[str, Any]:
    target = await resolve_target_user(db, to_name)
    proj = {f: 1 for f in LEAD_LABEL_FIELDS}
    proj.update({"id": 1, "assigned_user_id": 1})
    leads = await db.leads.find({"assigned_user_id": target["id"]}, proj).to_list(None)
    tasks = await db.tasks.find({"assigned_user_id": target["id"]}, {f: 1 for f in (*TASK_LABEL_FIELDS, "id")}).to_list(None)
    plan: Dict[str, Any] = {
        "target": target,
        "leads": _plan_renames(leads, LEAD_LABEL_FIELDS, from_name, to_name),
        "tasks": _plan_renames(tasks, TASK_LABEL_FIELDS, from_name, to_name),
        "mislabeled": [],
    }
    if include_mislabeled:
        names = {u["id"]: u["full_name"] for u in await db.users.find({}, {"_id": 0, "id": 1, "full_name": 1}).to_list(1000)}
        mis_proj = dict(proj)
        cursor = await db.leads.find({"assigned_user_id": {"$nin": [target["id"], None, ""]}}, mis_proj).to_list(None)
        for d in cursor:
            owner_name = names.get(d.get("assigned_user_id"))
            if not owner_name:
                continue  # owner is not a registered user: leave alone
            changes = {f: owner_name for f in LEAD_LABEL_FIELDS if d.get(f) is not None and d.get(f) != owner_name and f != "presales_agent"}
            # presales_agent mirrors the owner name only when it currently mirrors the stale label
            if d.get("presales_agent") not in (None, owner_name) and d.get("presales_agent") == d.get("assigned_to"):
                changes["presales_agent"] = owner_name
            if changes:
                plan["mislabeled"].append({"_id": d["_id"], "id": d.get("id"), "before": {f: d.get(f) for f in changes}, "after": changes})
    return plan


async def apply_plan(db: Any, plan: Dict[str, Any], *, backup_dir: Path = BACKUP_DIR) -> Dict[str, Any]:
    total = sum(len(plan[k]) for k in ("leads", "tasks", "mislabeled"))
    result: Dict[str, Any] = {"backup_file": None, "updated": {"leads": 0, "tasks": 0, "mislabeled": 0}}
    if not total:
        return result
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"owner_label_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    payload = {k: [{"id": p["id"], "before": p["before"]} for p in plan[k]] for k in ("leads", "tasks", "mislabeled")}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    saved = json.loads(path.read_text(encoding="utf-8"))
    if sum(len(saved[k]) for k in saved) != total:
        raise RelabelError("Backup verification failed - nothing updated")
    result["backup_file"] = str(path)

    for key, coll in (("leads", db.leads), ("tasks", db.tasks), ("mislabeled", db.leads)):
        for p in plan[key]:
            # $set on the label fields only: updated_at / history stay exactly as they were
            res = await coll.update_one({"_id": p["_id"]}, {"$set": p["after"]})
            result["updated"][key] += res.modified_count
    return result


def _print_plan(plan: Dict[str, Any], from_name: str, to_name: str, include_mislabeled: bool = False) -> None:
    print(f"Target account: {plan['target']['full_name']} <{plan['target'].get('email')}> id={plan['target']['id']}")
    print(f"  leads to relabel {from_name!r} -> {to_name!r}: {len(plan['leads'])}")
    print(f"  tasks to relabel {from_name!r} -> {to_name!r}: {len(plan['tasks'])}")
    if include_mislabeled:
        from collections import Counter

        c = Counter((p["before"].get("assigned_to_name") or p["before"].get("assigned_to"), p["after"].get("assigned_to_name") or p["after"].get("assigned_to")) for p in plan["mislabeled"])
        print(f"  leads whose label disagrees with the real owner: {len(plan['mislabeled'])}")
        for (old, new), n in c.most_common(12):
            print(f"      {n:4d}  {old!r} -> {new!r}")


async def run(*, apply: bool, from_name: str, to_name: str, include_mislabeled: bool) -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT_DIR / ".env")
    sys.path.insert(0, str(ROOT_DIR))
    from crm.core.state import db

    print(f"Database: {db.name}")
    plan = await build_plan(db, from_name=from_name, to_name=to_name, include_mislabeled=include_mislabeled)
    _print_plan(plan, from_name, to_name, include_mislabeled)
    if not apply:
        print("Dry run only - pass --apply to back up and update.")
        return 0
    res = await apply_plan(db, plan)
    print(f"Backup: {res['backup_file']}")
    print(f"Updated: {res['updated']}")
    again = await build_plan(db, from_name=from_name, to_name=to_name, include_mislabeled=include_mislabeled)
    left = sum(len(again[k]) for k in ("leads", "tasks", "mislabeled"))
    print(f"Remaining to relabel after apply: {left}")
    return 0 if left == 0 else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Relabel stored owner names (Roshini -> Admin)")
    ap.add_argument("--from-name", default="Roshini")
    ap.add_argument("--to-name", default="Admin")
    ap.add_argument("--include-mislabeled", action="store_true", help="Also fix labels that disagree with the real owner.")
    ap.add_argument("--apply", action="store_true", help="Back up and update (default is preview).")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(apply=args.apply, from_name=args.from_name, to_name=args.to_name, include_mislabeled=args.include_mislabeled)))


if __name__ == "__main__":
    main()
