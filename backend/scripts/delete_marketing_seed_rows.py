#!/usr/bin/env python3
"""
delete_marketing_seed_rows.py
=============================
One-time cleanup: remove the placeholder rows (source == "seed") that were
inserted into marketing_spends before real Meta Ads data existed. They show up
in the dashboard's manual-entry table as if they were real spend.

Safety
------
  * Dry run by default - prints exactly which rows would be removed.
  * --apply first writes the matched documents to a timestamped JSON file under
    scripts/static_data/ (git-ignored), re-reads it, and only then deletes by
    the _id values it just backed up - never by a broad filter.
  * Matches ONLY {"source": "seed"}. Rows entered by people are untouched.

Usage
-----
  python scripts/delete_marketing_seed_rows.py            # preview
  python scripts/delete_marketing_seed_rows.py --apply    # backup + delete
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT_DIR / "scripts" / "static_data"
SEED_FILTER = {"source": "seed"}


def _json_default(o: Any) -> str:
    return str(o)


async def delete_seed_rows(db: Any, *, apply: bool, backup_dir: Path = BACKUP_DIR) -> Dict[str, Any]:
    """Returns {matched, deleted, backup_file}. Pure of env/IO setup so tests
    can pass a fake db."""
    docs: List[dict] = await db.marketing_spends.find(SEED_FILTER).to_list(1000)
    result: Dict[str, Any] = {"matched": len(docs), "deleted": 0, "backup_file": None, "rows": docs}
    if not apply or not docs:
        return result

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = backup_dir / f"marketing_spends_seed_backup_{stamp}.json"
    path.write_text(json.dumps(docs, indent=2, default=_json_default), encoding="utf-8")
    restored = json.loads(path.read_text(encoding="utf-8"))
    if len(restored) != len(docs):
        raise RuntimeError("Backup verification failed - nothing deleted")

    ids = [d["_id"] for d in docs]
    res = await db.marketing_spends.delete_many({"_id": {"$in": ids}, **SEED_FILTER})
    result["deleted"] = res.deleted_count
    result["backup_file"] = str(path)
    return result


async def run(*, apply: bool) -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT_DIR / ".env")
    sys.path.insert(0, str(ROOT_DIR))
    from crm.core.state import db

    print(f"Database: {db.name}")
    result = await delete_seed_rows(db, apply=apply)
    for d in result["rows"]:
        print(f"  - {d.get('date')} | {d.get('project')} | {d.get('channel')} | {d.get('amount')} | id={d.get('id')}")
    print(f"Matched {{source: 'seed'}}: {result['matched']}")
    if not apply:
        print("Dry run only - pass --apply to back up and delete.")
        return 0
    print(f"Backup: {result['backup_file']}")
    print(f"Deleted: {result['deleted']}")
    remaining: Optional[int] = await db.marketing_spends.count_documents(SEED_FILTER)
    print(f"Seed rows remaining: {remaining}")
    return 0 if remaining == 0 else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Delete source=seed rows from marketing_spends")
    ap.add_argument("--apply", action="store_true", help="Back up and delete (default is preview).")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(apply=args.apply)))


if __name__ == "__main__":
    main()
