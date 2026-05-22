"""One-time MongoDB cleanup: deduplicate context_updates on all leads.

Usage (from backend/):
  python scripts/dedupe_lead_context_updates.py
  python scripts/dedupe_lead_context_updates.py --dry-run

Requires MONGO_URL and DB_NAME in environment (or backend/.env).
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env")

from crm.services.context_updates import dedupe_context_updates  # noqa: E402


def _env(name: str, default: Optional[str] = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


async def run_dedupe(*, dry_run: bool = False):
    mongo_url = _env("MONGO_URL")
    db_name = _env("DB_NAME")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    leads_scanned = 0
    leads_with_timeline = 0
    leads_updated = 0
    entries_removed = 0
    sample_lead_ids: list[str] = []
    max_samples = 10

    cursor = db.leads.find({}, {"_id": 0, "id": 1, "context_updates": 1})
    async for lead in cursor:
        leads_scanned += 1
        original = lead.get("context_updates") or []
        if not original:
            continue
        leads_with_timeline += 1
        deduped = dedupe_context_updates(original)
        if len(deduped) >= len(original):
            continue
        removed = len(original) - len(deduped)
        if not dry_run:
            await db.leads.update_one({"id": lead["id"]}, {"$set": {"context_updates": deduped}})
        leads_updated += 1
        entries_removed += removed
        if len(sample_lead_ids) < max_samples:
            sample_lead_ids.append(lead["id"])

    status = "no_duplicates_found" if leads_updated == 0 else "duplicates_found"
    print(
        {
            "dry_run": dry_run,
            "db_name": db_name,
            "status": status,
            "leads_scanned": leads_scanned,
            "leads_with_timeline": leads_with_timeline,
            "leads_updated": leads_updated,
            "entries_removed": entries_removed,
            "sample_lead_ids": sample_lead_ids,
        }
    )
    client.close()


def main():
    parser = argparse.ArgumentParser(description="Deduplicate context_updates on all leads.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts only; do not write to MongoDB.",
    )
    args = parser.parse_args()
    asyncio.run(run_dedupe(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
