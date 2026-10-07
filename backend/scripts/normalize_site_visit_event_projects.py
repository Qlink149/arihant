#!/usr/bin/env python3
"""
normalize_site_visit_event_projects.py
======================================
One-time backfill: canonicalize the `project` / `projects` fields of the
append-only `site_visit_events` log, using the same client-approved mapping the
leads already went through (crm/services/lead_field_normalize.py). Events
written before that normalization still carry the old spellings
("Reserve 16", "Vivriti", "Saligramam Melange", ...), so the Site Visits report
showed one project as several bars.

The report itself also merges these at read time, so this backfill is not
required for correct numbers - it makes the stored data match.

Safety
------
  * Dry run by default: prints every change grouped by old -> new value.
  * --apply first writes the ORIGINAL docs it is about to change to a
    timestamped JSON file under scripts/static_data/ (git-ignored), then updates
    only `project` and `projects` on those events, by _id.
  * Idempotent: events already canonical are skipped, so re-running is a no-op.
  * Events with no project at all are left untouched.

Usage
-----
  python scripts/normalize_site_visit_event_projects.py            # preview
  python scripts/normalize_site_visit_event_projects.py --apply    # backup + update
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT_DIR / "scripts" / "static_data"
sys.path.insert(0, str(ROOT_DIR))

from crm.services.lead_field_normalize import remap_projects_from_values  # noqa: E402


def plan_changes(events: List[dict]) -> List[Tuple[dict, str, List[str]]]:
    """(event, new_project, new_projects) for events whose stored values differ
    from their canonical form."""
    changes: List[Tuple[dict, str, List[str]]] = []
    for ev in events:
        new_project, new_projects = remap_projects_from_values(ev.get("project"), ev.get("projects"))
        if new_project is None:
            continue  # nothing to normalize (no project)
        if new_project != ev.get("project") or new_projects != ev.get("projects"):
            changes.append((ev, new_project, new_projects))
    return changes


async def normalize_events(db: Any, *, apply: bool, backup_dir: Path = BACKUP_DIR) -> Dict[str, Any]:
    events: List[dict] = await db.site_visit_events.find({}).to_list(None)
    changes = plan_changes(events)
    summary: Dict[str, Any] = {
        "total_events": len(events),
        "to_change": len(changes),
        "transitions": Counter((ev.get("project"), new_project) for ev, new_project, _ in changes),
        "updated": 0,
        "backup_file": None,
    }
    if not apply or not changes:
        return summary

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = backup_dir / f"site_visit_events_project_backup_{stamp}.json"
    path.write_text(json.dumps([ev for ev, _, _ in changes], indent=2, default=str), encoding="utf-8")
    if len(json.loads(path.read_text(encoding="utf-8"))) != len(changes):
        raise RuntimeError("Backup verification failed - nothing updated")
    summary["backup_file"] = str(path)

    for ev, new_project, new_projects in changes:
        res = await db.site_visit_events.update_one(
            {"_id": ev["_id"]}, {"$set": {"project": new_project, "projects": new_projects}}
        )
        summary["updated"] += res.modified_count
    return summary


async def run(*, apply: bool) -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT_DIR / ".env")
    from crm.core.state import db

    print(f"Database: {db.name}")
    s = await normalize_events(db, apply=apply)
    print(f"site_visit_events: {s['total_events']} total, {s['to_change']} need normalizing")
    for (old, new), n in sorted(s["transitions"].items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {old!r}  ->  {new!r}")
    if not apply:
        print("Dry run only - pass --apply to back up and update.")
        return 0
    print(f"Backup: {s['backup_file']}")
    print(f"Updated: {s['updated']}")
    again = await normalize_events(db, apply=False)
    print(f"Remaining to normalize after apply: {again['to_change']}")
    return 0 if again["to_change"] == 0 else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Canonicalize site_visit_events project names")
    ap.add_argument("--apply", action="store_true", help="Back up and update (default is preview).")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(apply=args.apply)))


if __name__ == "__main__":
    main()
