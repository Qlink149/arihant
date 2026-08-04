#!/usr/bin/env python3
"""
fix_unowned_lead_assignment.py
===============================
Reassign leads that were given an ARBITRARY rep at import time to the Admin account.

Background
----------
seed_db_v2.transform_to_lead() falls back to `reps[hash(phone) % len(reps)]` when a
Freshworks contact has a blank "Sales owner". That invents an owner for a lead nobody
actually owns, and because Python randomizes string hashing per process, the same lead
lands on a different rep on every run. Contacts with a blank Sales owner in the source
export are identified here from the CSV itself -- not guessed from the database.

Safety
------
  - Only touches leads whose SOURCE CSV row has a blank "Sales owner". Leads with a
    real owner in Freshworks are never matched.
  - Only touches leads with sla_paused=True. If a rep has already started working one
    of these leads, it is reported and left alone -- reassigning live work would be
    worse than the original problem.
  - Backs up every matched document in full before writing.
  - Sets only the assignment fields; does not touch sla_paused, lead_status, or
    context_updates, and does not go through lead_service (no SLA activation, no
    tasks, no notifications).
  - Dry-run by default; --apply required to write.

Usage:
  python backend/scripts/fix_unowned_lead_assignment.py
  python backend/scripts/fix_unowned_lead_assignment.py --apply
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
for p in (str(BACKEND_DIR), str(SCRIPT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)
load_dotenv(BACKEND_DIR / ".env")

import seed_db_v2 as sv2  # noqa: E402
from extract_csv_data import find_csv  # noqa: E402

ADMIN_FULL_NAME = "Admin"


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv-dir", default=str(BACKEND_DIR / "csv"))
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry-run preview)")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL", "")
    db_name = os.environ.get("DB_NAME", "")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env", file=sys.stderr)
        sys.exit(1)

    client = MongoClient(mongo_url)
    db = client[db_name]
    leads = db.leads

    mode = "APPLY" if args.apply else "DRY-RUN"
    print("=" * 72)
    print(f"  fix_unowned_lead_assignment.py  [{mode}]  DB={db_name}")
    print("=" * 72)

    admin = db.users.find_one({"full_name": ADMIN_FULL_NAME}, {"_id": 0, "id": 1, "full_name": 1, "email": 1})
    if not admin:
        print(f"ERROR: no user with full_name={ADMIN_FULL_NAME!r} found.", file=sys.stderr)
        sys.exit(1)
    print(f"  Admin target: {admin['full_name']!r} <{admin.get('email')}> id={admin['id']}\n")

    contacts_path = find_csv(args.csv_dir, "Contacts.csv")
    if not contacts_path:
        print(f"ERROR: Contacts.csv not found under {args.csv_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"  Source: {Path(contacts_path).name}")

    rows = sv2.read_csv_file(contacts_path)
    blank_owner_ids = [r["Id"] for r in rows if r.get("Id") and not (r.get("Sales owner") or "").strip()]
    print(f"  Contacts with BLANK 'Sales owner' in export: {len(blank_owner_ids)}")

    matched = list(
        leads.find(
            {"external_id": {"$in": blank_owner_ids}},
            {"_id": 0},
        )
    )
    paused = [d for d in matched if d.get("sla_paused") is True]
    rep_worked = [d for d in matched if d.get("sla_paused") is not True]
    already_admin = [d for d in paused if d.get("assigned_user_id") == admin["id"]]
    to_fix = [d for d in paused if d.get("assigned_user_id") != admin["id"]]

    print(f"  Present in DB                     : {len(matched)}")
    print(f"    already assigned to Admin        : {len(already_admin)}")
    print(f"    rep already working (LEFT ALONE) : {len(rep_worked)}")
    print(f"    to reassign to Admin             : {len(to_fix)}")

    if rep_worked:
        print("\n  Rep-worked leads left untouched (reassigning live work would be worse):")
        for d in rep_worked[:20]:
            print(f"    ext={d.get('external_id')} {d.get('first_name')!r} -> {d.get('assigned_to')!r}")

    if to_fix:
        print("\n  Current (invented) assignees being cleared:")
        for name, n in collections.Counter(d.get("assigned_to") for d in to_fix).most_common():
            print(f"    {n:>4}  {name!r}")

    if not to_fix:
        print("\n  Nothing to do.")
        client.close()
        return

    if not args.apply:
        print("\n  DRY-RUN -- no changes written. Re-run with --apply.")
        client.close()
        return

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = SCRIPT_DIR / "static_data" / f"pre_unowned_assignment_backup_{run_id}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(to_fix, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n  [OK] backed up {len(to_fix)} full documents -> {backup_path.name}")

    ids = [d["id"] for d in to_fix]
    result = leads.update_many(
        {"id": {"$in": ids}, "sla_paused": True},
        {
            "$set": {
                "assigned_to": admin["full_name"],
                "assigned_to_name": admin["full_name"],
                "assigned_user_id": admin["id"],
                "presales_agent": admin["full_name"],
                "unowned_in_source": True,
            }
        },
    )
    print(f"  [OK] matched {result.matched_count}, modified {result.modified_count}")
    print("\n  Marked with unowned_in_source=True so these stay identifiable for redistribution.")
    print("  sla_paused, lead_status and context_updates were not altered.")
    client.close()


if __name__ == "__main__":
    main()
