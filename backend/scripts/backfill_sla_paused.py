#!/usr/bin/env python3
"""
backfill_sla_paused.py
======================
One-time migration: mark all existing leads as SLA-paused (historical Freshworks import)
so the SLA cron does not process old data on first deploy.

Run AFTER deploying code with sla_paused exclusion, BEFORE enabling the SLA cron.

Usage
-----
  # Preview counts (no writes)
  python scripts/backfill_sla_paused.py

  # Apply to production Mongo
  python scripts/backfill_sla_paused.py --apply

  # Only leads not already paused
  python scripts/backfill_sla_paused.py --apply --skip-already-paused
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ.get("MONGO_URL", "")
DB_NAME = os.environ.get("DB_NAME", "")


async def run(*, apply: bool, skip_already_paused: bool) -> int:
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL and DB_NAME must be set in environment or .env", file=sys.stderr)
        return 1

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    leads = db.leads

    query: dict = {}
    if skip_already_paused:
        query = {"sla_paused": {"$ne": True}}

    total = await leads.count_documents({})
    matched = await leads.count_documents(query)

    print(f"Database: {DB_NAME}")
    print(f"Total leads: {total}")
    print(f"Leads to update: {matched}")
    if skip_already_paused:
        already = total - matched
        print(f"Already sla_paused: {already}")

    if not apply:
        print("\nDry run only — pass --apply to write changes.")
        client.close()
        return 0

    if matched == 0:
        print("\nNothing to update.")
        client.close()
        return 0

    result = await leads.update_many(
        query,
        {
            "$set": {
                "sla_paused": True,
                "import_provenance": "freshworks",
            }
        },
    )
    print(f"\nUpdated {result.modified_count} lead(s).")
    client.close()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill sla_paused on historical imported leads")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Write changes (default is dry-run preview only).",
    )
    ap.add_argument(
        "--skip-already-paused",
        action="store_true",
        help="Only update leads where sla_paused is not already true.",
    )
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(apply=args.apply, skip_already_paused=args.skip_already_paused)))


if __name__ == "__main__":
    main()
