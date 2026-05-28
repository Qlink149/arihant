"""One-time MongoDB migration: eradicate legacy lead_status \"Open\".

Phase 1: lead_status Open + original_fw_status set -> lead_status = original_fw_status
Phase 2: remaining Open -> lead_status = New

Usage (from backend/):
  python scripts/fix_legacy_status.py
  python scripts/fix_legacy_status.py --dry-run

Requires MONGO_URL and DB_NAME in backend/.env (or environment).
Do not run in CI without credentials; execute locally against your database.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

_OPEN_STATUS = {"$regex": r"^\s*open\s*$", "$options": "i"}


def _env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name} (set in backend/.env)")
    return val


async def run_migration(*, dry_run: bool = False) -> None:
    mongo_url = _env("MONGO_URL")
    db_name = _env("DB_NAME")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    leads = db.leads

    phase1_filter = {
        "lead_status": _OPEN_STATUS,
        "original_fw_status": {"$exists": True, "$nin": [None, ""]},
    }
    phase2_filter = {"lead_status": _OPEN_STATUS}

    if dry_run:
        phase1_count = await leads.count_documents(phase1_filter)
        phase2_count = await leads.count_documents(phase2_filter)
        print(f"[dry-run] Phase 1 would update: {phase1_count} lead(s)")
        print(f"[dry-run] Phase 2 would update: {phase2_count} lead(s) (includes any still Open after phase 1)")
        print(f"[dry-run] db_name={db_name}")
        client.close()
        return

    result1 = await leads.update_many(
        phase1_filter,
        [{"$set": {"lead_status": "$original_fw_status"}}],
    )
    print(f"Phase 1 modified_count: {result1.modified_count}")

    result2 = await leads.update_many(
        phase2_filter,
        {"$set": {"lead_status": "New"}},
    )
    print(f"Phase 2 modified_count: {result2.modified_count}")

    remaining = await leads.count_documents(phase2_filter)
    print(f"Remaining Open (case-insensitive): {remaining}")
    print(f"db_name={db_name}")

    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate legacy lead_status Open to FW label or New.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count matching documents only; do not write.",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run_migration(dry_run=args.dry_run))
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
