#!/usr/bin/env python3
"""
migrate_location_to_list.py
============================
batch3(item4): #51 Location Interested becomes multi-select. Converts every
lead's existing scalar `location` string into a one-item list, so old and
new leads share one shape. Idempotent - a lead whose location is already a
list (or already empty/missing) is left untouched, so this is safe to
re-run after new leads have started writing list-shaped locations.

Every reader in the codebase (inventory matching, exports, Meta CAPI, the
AI persona sentence, VC filter dropdown - see
crm/services/lead_location_fields.coalesce_locations) already accepts BOTH
shapes, so running this migration is not required for the feature to work.
It only exists to make historical data consistent going forward.

Usage
-----
  # Preview counts (no writes)
  python scripts/migrate_location_to_list.py

  # Apply to production Mongo
  python scripts/migrate_location_to_list.py --apply
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

BATCH_SIZE = 500


async def run(*, apply: bool) -> int:
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL and DB_NAME must be set in environment or .env", file=sys.stderr)
        return 1

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    leads = db.leads

    total = await leads.count_documents({})
    # Already-a-list or empty/missing leads need no change - this is the
    # idempotency guard (re-running after list-shaped leads exist is a no-op
    # for them).
    scalar_nonempty_query = {
        "location": {"$exists": True, "$nin": [None, "", []], "$not": {"$type": "array"}}
    }
    to_migrate = await leads.count_documents(scalar_nonempty_query)
    already_list = await leads.count_documents({"location": {"$type": "array"}})
    missing_or_empty = total - to_migrate - already_list

    print(f"Database: {DB_NAME}")
    print(f"Total leads: {total}")
    print(f"Leads with scalar location (would be converted to a list): {to_migrate}")
    print(f"Leads already list-shaped (no-op): {already_list}")
    print(f"Leads with no location set (no-op): {missing_or_empty}")

    if not apply:
        print("\nDry run only — pass --apply to write changes.")
        client.close()
        return 0

    if to_migrate == 0:
        print("\nNothing to update.")
        client.close()
        return 0

    updated = 0
    cursor = leads.find(scalar_nonempty_query, {"_id": 0, "id": 1, "location": 1}).batch_size(BATCH_SIZE)
    async for doc in cursor:
        await leads.update_one(
            {"id": doc["id"]},
            {"$set": {"location": [doc["location"]]}},
        )
        updated += 1

    print(f"\nUpdated {updated} lead(s).")
    client.close()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert scalar lead.location to a one-item list (#51)")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Write changes (default is dry-run preview only).",
    )
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(apply=args.apply)))


if __name__ == "__main__":
    main()
