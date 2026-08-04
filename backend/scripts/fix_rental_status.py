#!/usr/bin/env python3
"""
fix_rental_status.py
=====================
Targeted reconciliation: legacy leads imported from Freshworks status "Rental" that
still carry lead_status="Closed Lost", left behind when the mapping was changed to
Rental -> Unqualified.

Why this and not migrate_imported_statuses.py: that script re-applies the full mapping
to every sla_paused lead (~29k documents) to correct ~54. This touches only the exact
documents that are actually wrong, so a mistake here cannot affect anything else.

Safety:
  - Scope is triple-constrained: sla_paused=True AND original_fw_status="Rental"
    AND lead_status="Closed Lost". Rep-worked leads (sla_paused != True) are never
    matched, so no in-progress work is disturbed.
  - Writes a full backup of every matched document BEFORE updating.
  - Preserves original_fw_status and sla_paused; sets only lead_status (+ is_rnr=False,
    which Rental always maps to). Does not go through lead_service, so no SLA activation,
    no tasks, and no notifications are triggered.
  - Dry-run by default; --apply required to write.

Usage:
  python backend/scripts/fix_rental_status.py
  python backend/scripts/fix_rental_status.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from crm.constants.import_status_map import fw_status_to_canonical  # noqa: E402

FW_LABEL = "Rental"


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry-run preview)")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL", "")
    db_name = os.environ.get("DB_NAME", "")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env", file=sys.stderr)
        sys.exit(1)

    target_status, target_is_rnr = fw_status_to_canonical(FW_LABEL)

    client = MongoClient(mongo_url)
    db = client[db_name]
    leads = db.leads

    mode = "APPLY" if args.apply else "DRY-RUN"
    print("=" * 72)
    print(f"  fix_rental_status.py  [{mode}]  DB={db_name}")
    print("=" * 72)
    print(f"  Freshworks '{FW_LABEL}' should map to: {target_status!r} (is_rnr={target_is_rnr})\n")

    query = {
        "sla_paused": True,
        "original_fw_status": {"$regex": rf"^\s*{FW_LABEL}\s*$", "$options": "i"},
        "lead_status": {"$ne": target_status},
    }

    docs = list(leads.find(query, {"_id": 0}))
    print(f"  Leads needing correction: {len(docs)}")
    if docs:
        import collections

        for k, v in collections.Counter(d.get("lead_status") for d in docs).most_common():
            print(f"    currently {k!r}: {v}  ->  will become {target_status!r}")

    if not docs:
        print("\n  Nothing to do.")
        client.close()
        return

    if not args.apply:
        print("\n  DRY-RUN -- no changes written. Re-run with --apply.")
        client.close()
        return

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = SCRIPT_DIR / "static_data" / f"pre_rental_fix_backup_{run_id}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(docs, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n  [OK] backed up {len(docs)} full documents -> {backup_path.name}")

    result = leads.update_many(
        query,
        {"$set": {"lead_status": target_status, "is_rnr": bool(target_is_rnr)}},
    )
    print(f"  [OK] matched {result.matched_count}, modified {result.modified_count}")

    remaining = leads.count_documents(query)
    print(f"  Remaining mismatched after update: {remaining}")
    print("\n  Done. sla_paused and original_fw_status were not altered.")
    client.close()


if __name__ == "__main__":
    main()
