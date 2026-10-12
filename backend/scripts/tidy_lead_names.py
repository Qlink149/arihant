#!/usr/bin/env python3
"""
tidy_lead_names.py
==================
Fix lead names where the FULL name was stored in both First and Last name, which shows as
"Thiru Thiru" or "Anju Bagri Damani Damani". Uses crm.utils.person_names.tidy_person_name,
the same rule new leads now get at intake. Only exact repeats are removed; no name is ever
invented or shortened beyond that.

Scope (the data is cosmetic but it is people's names, so it is opt-in):
  --scope meta     leads that arrived through the Meta form Zap (default)
  --scope intake   Meta form + website + channel-partner intake (anything with intake_meta)
  --scope all      every lead, including old imports

Changes ONLY first_name / last_name. updated_at / history / counts are not touched.
Safety: dry run by default (prints before -> after); --apply writes a JSON backup of the
original names first; idempotent (a tidied name is not changed again).

Usage
-----
  python scripts/tidy_lead_names.py                    # preview, Meta-form leads
  python scripts/tidy_lead_names.py --scope all        # preview, every lead
  python scripts/tidy_lead_names.py --scope meta --apply
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
sys.path.insert(0, str(ROOT_DIR))

from crm.utils.person_names import tidy_person_name  # noqa: E402

SCOPE_FILTERS: Dict[str, Dict[str, Any]] = {
    "meta": {"intake_meta.via": "zapier"},
    "intake": {"intake_meta": {"$exists": True, "$ne": None}},
    "all": {},
}


def plan_changes(leads: List[dict]) -> List[Dict[str, Any]]:
    out = []
    for l in leads:
        first, last = l.get("first_name") or "", l.get("last_name") or ""
        new_first, new_last = tidy_person_name(first, last)
        if (new_first, new_last) != (first.strip(), last.strip()) and new_first:
            out.append({"_id": l["_id"], "id": l.get("id"), "before": {"first_name": first, "last_name": last}, "after": {"first_name": new_first, "last_name": new_last}})
    return out


async def build_plan(db: Any, scope: str) -> List[Dict[str, Any]]:
    leads = await db.leads.find(SCOPE_FILTERS[scope], {"id": 1, "first_name": 1, "last_name": 1}).to_list(None)
    return plan_changes(leads)


async def apply_plan(db: Any, plan: List[Dict[str, Any]], *, backup_dir: Path = BACKUP_DIR) -> Dict[str, Any]:
    res: Dict[str, Any] = {"updated": 0, "backup_file": None}
    if not plan:
        return res
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"lead_names_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps([{"id": p["id"], "before": p["before"]} for p in plan], indent=2, ensure_ascii=False), encoding="utf-8")
    if len(json.loads(path.read_text(encoding="utf-8"))) != len(plan):
        raise RuntimeError("Backup verification failed - nothing updated")
    res["backup_file"] = str(path)
    for p in plan:
        r = await db.leads.update_one({"_id": p["_id"]}, {"$set": p["after"]})  # names only
        res["updated"] += r.modified_count
    return res


async def run(*, scope: str, apply: bool) -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT_DIR / ".env")
    from crm.core.state import db

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    print(f"Database: {db.name} | scope: {scope}")
    plan = await build_plan(db, scope)
    print(f"Names to tidy: {len(plan)}")
    for p in plan[:25]:
        b, a = p["before"], p["after"]
        print(f"  {b['first_name']!r} + {b['last_name']!r}  ->  {a['first_name']!r} + {a['last_name']!r}")
    if len(plan) > 25:
        print(f"  ... and {len(plan) - 25} more")
    if not apply:
        print("Dry run only - pass --apply to back up and update.")
        return 0
    r = await apply_plan(db, plan)
    print(f"Backup: {r['backup_file']}\nUpdated: {r['updated']}")
    again = await build_plan(db, scope)
    print(f"Remaining after apply: {len(again)}")
    return 0 if not again else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Tidy doubled lead names")
    ap.add_argument("--scope", choices=sorted(SCOPE_FILTERS), default="meta")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    raise SystemExit(asyncio.run(run(scope=a.scope, apply=a.apply)))


if __name__ == "__main__":
    main()
