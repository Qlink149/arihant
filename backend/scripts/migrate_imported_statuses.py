"""One-time MongoDB migration: map imported Freshworks statuses to canonical SLA stages.

Only updates leads with sla_paused=True (import hold). Preserves original_fw_status
and keeps sla_paused=True — does not invoke lead_service (which would activate SLA).

Usage (from backend/):
  python scripts/migrate_imported_statuses.py --dry-run
  python scripts/migrate_imported_statuses.py --apply

Requires MONGO_URL and DB_NAME in backend/.env (or environment).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static_data"
sys.path.insert(0, str(BACKEND_ROOT))

from crm.constants.import_status_map import (  # noqa: E402
    MIGRATION_OLD_LABELS,
    is_already_canonical,
    migration_match_regex,
    resolve_imported_lead_status,
)

load_dotenv(BACKEND_ROOT / ".env")

PAUSED_SCOPE = {"sla_paused": True}


def _env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name} (set in backend/.env)")
    return val



async def _count_for_label(leads, old_label: str) -> int:
    regex = migration_match_regex(old_label)
    fw_filter = {**PAUSED_SCOPE, "original_fw_status": regex}
    ls_filter = {
        **PAUSED_SCOPE,
        "$or": [
            {"original_fw_status": {"$in": [None, ""]}},
            {"original_fw_status": {"$exists": False}},
        ],
        "lead_status": regex,
    }
    fw_count = await leads.count_documents(fw_filter)
    ls_count = await leads.count_documents(ls_filter)
    return fw_count + ls_count


async def _apply_label_update(leads, old_label: str, canonical: str, is_rnr: bool) -> int:
    regex = migration_match_regex(old_label)
    patch = {"lead_status": canonical, "is_rnr": is_rnr, "sla_paused": True}
    total_modified = 0

    # Prefer original_fw_status when it matches
    result_fw = await leads.update_many(
        {**PAUSED_SCOPE, "original_fw_status": regex, "lead_status": {"$ne": canonical}},
        {"$set": patch},
    )
    total_modified += result_fw.modified_count

    # Fall back to lead_status when no original_fw_status
    result_ls = await leads.update_many(
        {
            **PAUSED_SCOPE,
            "$or": [
                {"original_fw_status": {"$in": [None, ""]}},
                {"original_fw_status": {"$exists": False}},
            ],
            "lead_status": regex,
        },
        {"$set": {**patch, "lead_status": canonical}},
    )
    total_modified += result_ls.modified_count
    return total_modified


async def _find_unmapped_paused(leads) -> List[Dict[str, Any]]:
    pipeline = [
        {"$match": PAUSED_SCOPE},
        {
            "$group": {
                "_id": {
                    "lead_status": "$lead_status",
                    "original_fw_status": "$original_fw_status",
                },
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"count": -1}},
    ]
    rows = await leads.aggregate(pipeline).to_list(None)
    unmapped: List[Dict[str, Any]] = []
    for row in rows:
        key = row["_id"] or {}
        ls = key.get("lead_status")
        ofs = key.get("original_fw_status")
        canonical, _ = resolve_imported_lead_status(ls, ofs)
        if is_already_canonical(ls) and (not ofs or resolve_imported_lead_status(ls, ofs)[0] == ls):
            continue
        if is_already_canonical(canonical) and canonical == (ls or "").strip():
            continue
        unmapped.append(
            {
                "lead_status": ls,
                "original_fw_status": ofs,
                "resolved_canonical": canonical,
                "count": row["count"],
            }
        )
    return unmapped


async def run_migration(*, dry_run: bool = False) -> None:
    mongo_url = _env("MONGO_URL")
    db_name = _env("DB_NAME")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    leads = db.leads

    paused_total = await leads.count_documents(PAUSED_SCOPE)
    print(f"sla_paused=True leads: {paused_total:,}")
    print(f"db_name={db_name}")

    rule_report: List[Dict[str, Any]] = []
    total_would_update = 0
    total_modified = 0

    seen_targets: set[str] = set()
    for old_label in MIGRATION_OLD_LABELS:
        canonical, is_rnr = resolve_imported_lead_status(old_label, old_label)
        key = f"{old_label}->{canonical}"
        if key in seen_targets:
            continue
        seen_targets.add(key)

        count = await _count_for_label(leads, old_label)
        entry = {
            "old_label": old_label,
            "new_status": canonical,
            "is_rnr": is_rnr,
            "match_count": count,
        }
        rule_report.append(entry)
        total_would_update += count
        print(f"  {old_label!r} -> {canonical!r} (is_rnr={is_rnr}): {count:,}")

        if not dry_run and count > 0:
            modified = await _apply_label_update(leads, old_label, canonical, is_rnr)
            entry["modified_count"] = modified
            total_modified += modified

    # Second pass: bucket leads where original_fw_status drives resolution
    bucket_pass = [
        ("Open", None),
        ("Follow Up", None),
        ("Site Visit", None),
        ("Won", None),
        ("Lost", None),
    ]
    for bucket, _ in bucket_pass:
        cursor = leads.find(
            {**PAUSED_SCOPE, "lead_status": migration_match_regex(bucket)},
            {"lead_status": 1, "original_fw_status": 1},
        )
        bucket_modified = 0
        async for doc in cursor:
            canonical, is_rnr = resolve_imported_lead_status(
                doc.get("lead_status"),
                doc.get("original_fw_status"),
            )
            if doc.get("lead_status") == canonical:
                continue
            if dry_run:
                bucket_modified += 1
            else:
                result = await leads.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"lead_status": canonical, "is_rnr": is_rnr, "sla_paused": True}},
                )
                if result.modified_count:
                    bucket_modified += 1
        if bucket_modified:
            rule_report.append(
                {
                    "old_label": f"bucket:{bucket}",
                    "new_status": "(per original_fw_status)",
                    "modified_count": bucket_modified,
                }
            )
            if dry_run:
                total_would_update += bucket_modified
            else:
                total_modified += bucket_modified
            print(f"  bucket {bucket!r} resolved: {bucket_modified:,}")

    unmapped = await _find_unmapped_paused(leads)
    if unmapped:
        print("\nRemaining non-canonical paused combinations:")
        for row in unmapped[:30]:
            print(
                f"  lead_status={row['lead_status']!r} "
                f"original_fw_status={row['original_fw_status']!r} "
                f"-> {row['resolved_canonical']!r} count={row['count']}"
            )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "db_name": db_name,
        "paused_total": paused_total,
        "rules": rule_report,
        "total_would_update": total_would_update,
        "total_modified": total_modified if not dry_run else 0,
        "unmapped": unmapped,
    }

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = STATIC_DIR / f"status_migration_report_{ts}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nReport written to {report_path}")

    if dry_run:
        print(f"\n[dry-run] Would update approximately {total_would_update:,} lead(s)")
    else:
        print(f"\nModified {total_modified:,} lead(s)")

    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate sla_paused imported leads to canonical lead_status values.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Count only; do not write.")
    group.add_argument("--apply", action="store_true", help="Apply updates to MongoDB.")
    args = parser.parse_args()
    try:
        asyncio.run(run_migration(dry_run=args.dry_run))
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
