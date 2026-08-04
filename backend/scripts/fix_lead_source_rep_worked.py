#!/usr/bin/env python3
"""
fix_lead_source_rep_worked.py
==============================
Repair lead_source on leads the normal import deliberately skips because a rep has
already worked them (sla_paused != True).

Why a separate script: import_leads_to_db.py refuses to touch rep-worked leads at all,
which is correct for status/notes/assignment -- overwriting live work would be worse
than stale data. But lead_source is factual provenance from the source system, not rep
work, and it is currently wrong on these leads because seed_db_v2.clean_source()
collapsed distinct sources ("Aurum Analytica" -> "management reference") and defaulted
everything unrecognised to "google".

Safety
------
  - Updates ONLY lead_source / original_source / most_recent_source. Never touches
    lead_status, sla_paused, assignment, context_updates, tasks or timestamps, so a
    rep's in-progress work is untouched.
  - Sources the correct value by re-deriving from the Contacts CSV (same function the
    importer uses), matched on external_id -- never guessed.
  - Only writes where the value actually differs.
  - Backs up every matched document in full before writing.
  - Dry-run by default; --apply required to write.

Usage:
  python backend/scripts/fix_lead_source_rep_worked.py
  python backend/scripts/fix_lead_source_rep_worked.py --apply
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
from pymongo import MongoClient, UpdateOne

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
for p in (str(BACKEND_DIR), str(SCRIPT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)
load_dotenv(BACKEND_DIR / ".env")

import seed_db_v2 as sv2  # noqa: E402
from extract_csv_data import find_csv, resolve_lead_source  # noqa: E402


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
    print(f"  fix_lead_source_rep_worked.py  [{mode}]  DB={db_name}")
    print("=" * 72)

    contacts_path = find_csv(args.csv_dir, "Contacts.csv")
    if not contacts_path:
        print(f"ERROR: Contacts.csv not found under {args.csv_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"  Source CSV: {Path(contacts_path).name}\n")

    rows = sv2.read_csv_file(contacts_path)
    correct_by_ext = {r["Id"]: resolve_lead_source(r) for r in rows if r.get("Id")}

    ext_ids = list(correct_by_ext)
    rep_worked = []
    for i in range(0, len(ext_ids), 1000):
        chunk = ext_ids[i : i + 1000]
        rep_worked += list(
            leads.find(
                {"external_id": {"$in": chunk}, "sla_paused": {"$ne": True}},
                {"_id": 0},
            )
        )

    print(f"  Rep-worked leads present in this export: {len(rep_worked)}")

    to_fix = []
    for d in rep_worked:
        want = correct_by_ext.get(d.get("external_id"))
        if want != d.get("lead_source"):
            to_fix.append((d, want))

    print(f"  Of those, lead_source is wrong on      : {len(to_fix)}")

    if to_fix:
        print("\n  Corrections to apply (current -> correct):")
        pairs = collections.Counter((d.get("lead_source"), want) for d, want in to_fix)
        for (cur, want), n in pairs.most_common(20):
            print(f"    {n:>4}  {cur!r}  ->  {want!r}")

    if not to_fix:
        print("\n  Nothing to do.")
        client.close()
        return

    if not args.apply:
        print("\n  DRY-RUN -- no changes written. Re-run with --apply.")
        client.close()
        return

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = SCRIPT_DIR / "static_data" / f"pre_source_fix_repworked_backup_{run_id}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump([d for d, _ in to_fix], f, indent=2, default=str, ensure_ascii=False)
    print(f"\n  [OK] backed up {len(to_fix)} full documents -> {backup_path.name}")

    ops = []
    for d, want in to_fix:
        setter = {"lead_source": want}
        # Keep the overview fields consistent with the corrected source, but only where
        # they were themselves derived from the old bad value (or were never set).
        if not d.get("original_source") or d.get("original_source") == d.get("lead_source"):
            setter["original_source"] = want
        if not d.get("most_recent_source") or d.get("most_recent_source") == d.get("lead_source"):
            setter["most_recent_source"] = want
        ops.append(UpdateOne({"id": d["id"]}, {"$set": setter}))

    result = leads.bulk_write(ops, ordered=False)
    print(f"  [OK] matched {result.matched_count}, modified {result.modified_count}")
    print("\n  Only source fields were changed. lead_status, sla_paused, assignment,")
    print("  context_updates and tasks were NOT touched -- no rep work disturbed.")
    client.close()


if __name__ == "__main__":
    main()
