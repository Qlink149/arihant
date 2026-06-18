#!/usr/bin/env python3
"""
backfill_lead_overview_fields.py
================================
One-time migration for new lead overview fields:
- original_source / most_recent_source from lead_source when empty
- site_visit_count = 1 when visit_completed_at_dt exists and count is missing/zero

Usage
-----
  python scripts/backfill_lead_overview_fields.py
  python scripts/backfill_lead_overview_fields.py --apply
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


async def run(*, apply: bool) -> int:
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL and DB_NAME must be set in environment or .env", file=sys.stderr)
        return 1

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    leads = db.leads

    total = await leads.count_documents({})

    orig_missing = await leads.count_documents(
        {
            "$or": [
                {"original_source": {"$exists": False}},
                {"original_source": None},
                {"original_source": ""},
            ],
            "lead_source": {"$exists": True, "$nin": [None, ""]},
        }
    )
    recent_missing = await leads.count_documents(
        {
            "$or": [
                {"most_recent_source": {"$exists": False}},
                {"most_recent_source": None},
                {"most_recent_source": ""},
            ],
            "lead_source": {"$exists": True, "$nin": [None, ""]},
        }
    )
    sv_backfill = await leads.count_documents(
        {
            "visit_completed_at_dt": {"$exists": True, "$ne": None},
            "$or": [
                {"site_visit_count": {"$exists": False}},
                {"site_visit_count": None},
                {"site_visit_count": 0},
            ],
        }
    )

    print(f"Database: {DB_NAME}")
    print(f"Total leads: {total}")
    print(f"original_source backfill candidates: {orig_missing}")
    print(f"most_recent_source backfill candidates: {recent_missing}")
    print(f"site_visit_count backfill candidates: {sv_backfill}")

    if not apply:
        print("\nDry run only — pass --apply to write changes.")
        client.close()
        return 0

    orig_result = await leads.update_many(
        {
            "$or": [
                {"original_source": {"$exists": False}},
                {"original_source": None},
                {"original_source": ""},
            ],
            "lead_source": {"$exists": True, "$nin": [None, ""]},
        },
        [{"$set": {"original_source": "$lead_source"}}],
    )
    recent_result = await leads.update_many(
        {
            "$or": [
                {"most_recent_source": {"$exists": False}},
                {"most_recent_source": None},
                {"most_recent_source": ""},
            ],
            "lead_source": {"$exists": True, "$nin": [None, ""]},
        },
        [{"$set": {"most_recent_source": "$lead_source"}}],
    )
    sv_result = await leads.update_many(
        {
            "visit_completed_at_dt": {"$exists": True, "$ne": None},
            "$or": [
                {"site_visit_count": {"$exists": False}},
                {"site_visit_count": None},
                {"site_visit_count": 0},
            ],
        },
        {"$set": {"site_visit_count": 1}},
    )

    print(f"\nUpdated original_source: {orig_result.modified_count}")
    print(f"Updated most_recent_source: {recent_result.modified_count}")
    print(f"Updated site_visit_count: {sv_result.modified_count}")

    client.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill lead overview fields")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry run)")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(apply=args.apply)))


if __name__ == "__main__":
    main()
