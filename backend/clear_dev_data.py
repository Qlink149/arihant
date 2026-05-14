#!/usr/bin/env python3
"""
Delete transactional CRM data for local/dev resets.
Removes all documents from: leads, tasks, marketing_spends.
Preserves users, alert_configs, assignment_rules, notifications, campaigns, etc.

Requires ENVIRONMENT=development unless --i-know-what-im-doing is passed.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")

COLLECTIONS_TO_CLEAR = ("leads", "tasks", "marketing_spends")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear leads/tasks/marketing_spends (dev-safe guard).")
    parser.add_argument("--dry-run", action="store_true", help="Only print counts, do not delete.")
    parser.add_argument(
        "--i-know-what-im-doing",
        action="store_true",
        help="Allow running when ENVIRONMENT is not development.",
    )
    args = parser.parse_args()

    env = (os.environ.get("ENVIRONMENT") or "").strip().lower()
    if env != "development" and not args.i_know_what_im_doing:
        print(
            "Refusing to run: set ENVIRONMENT=development or pass --i-know-what-im-doing.",
            file=sys.stderr,
        )
        sys.exit(1)

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("MONGO_URL and DB_NAME must be set in backend/.env", file=sys.stderr)
        sys.exit(1)

    client = MongoClient(mongo_url)
    db = client[db_name]

    for name in COLLECTIONS_TO_CLEAR:
        coll = db[name]
        n = coll.count_documents({})
        if args.dry_run:
            print(f"[dry-run] would delete {n} documents from {name}")
        else:
            result = coll.delete_many({})
            print(f"deleted {result.deleted_count} documents from {name}")

    client.close()


if __name__ == "__main__":
    main()
