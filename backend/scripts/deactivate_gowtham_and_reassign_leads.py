#!/usr/bin/env python3
"""
deactivate_gowtham_and_reassign_leads.py
========================================
Idempotent production data action:
  1. Set is_active=False on gowtham@arihants.co.in (user retained for history).
  2. Reassign non-terminal leads still owned by Gowtham → Anusha (pool primary).

Dry-run by default; pass --apply to write.

Usage:
  python backend/scripts/deactivate_gowtham_and_reassign_leads.py
  python backend/scripts/deactivate_gowtham_and_reassign_leads.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from crm.constants.lead_status import is_terminal_lead_status  # noqa: E402
from crm.services.project_assignment_pools import ANUSHA_EMAIL  # noqa: E402

GOWTHAM_EMAIL = "gowtham@arihants.co.in"


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL", "")
    db_name = os.environ.get("DB_NAME", "")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env", file=sys.stderr)
        sys.exit(1)

    print(f"Database: {db_name}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    if db_name == "arihant_crm" and args.apply:
        print("WARNING: applying against production database arihant_crm")

    client = MongoClient(mongo_url)
    db = client[db_name]

    gowtham = db.users.find_one({"email": GOWTHAM_EMAIL}, {"_id": 0})
    anusha = db.users.find_one({"email": ANUSHA_EMAIL}, {"_id": 0})
    if not gowtham:
        print(f"ERROR: user {GOWTHAM_EMAIL} not found", file=sys.stderr)
        sys.exit(1)
    if not anusha:
        print(f"ERROR: user {ANUSHA_EMAIL} not found", file=sys.stderr)
        sys.exit(1)

    gowtham_id = gowtham["id"]
    anusha_id = anusha["id"]
    anusha_name = anusha.get("full_name") or "Anusha Omprakash"

    already_inactive = gowtham.get("is_active") is False
    print(f"\nUser {GOWTHAM_EMAIL}: is_active={gowtham.get('is_active', True)} → False (skip={already_inactive})")

    leads = list(
        db.leads.find(
            {"assigned_user_id": gowtham_id},
            {"_id": 0, "id": 1, "lead_status": 1, "first_name": 1, "last_name": 1},
        )
    )
    by_status = Counter((lead.get("lead_status") or "unknown") for lead in leads)
    open_leads = [l for l in leads if not is_terminal_lead_status(l.get("lead_status"))]
    terminal_leads = [l for l in leads if is_terminal_lead_status(l.get("lead_status"))]

    print(f"\nLeads assigned to Gowtham: {len(leads)} total")
    for status, count in sorted(by_status.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {status}: {count}")
    print(f"Open (will reassign to Anusha): {len(open_leads)}")
    print(f"Terminal (unchanged): {len(terminal_leads)}")

    backup_dir = BACKEND_DIR / "scripts" / ".backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"gowtham_reassign_{db_name}_{stamp}.json"

    if not args.apply:
        print("\nDry-run complete. Re-run with --apply to write.")
        return

    backup = {
        "gowtham_user": gowtham,
        "open_lead_ids": [l["id"] for l in open_leads],
        "terminal_lead_ids": [l["id"] for l in terminal_leads],
    }
    backup_path.write_text(json.dumps(backup, indent=2, default=str), encoding="utf-8")
    print(f"\nBackup written: {backup_path}")

    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()

    if not already_inactive:
        db.users.update_one({"id": gowtham_id}, {"$set": {"is_active": False, "updated_at": now_iso}})

    for lead in open_leads:
        db.leads.update_one(
            {"id": lead["id"]},
            {
                "$set": {
                    "assigned_user_id": anusha_id,
                    "assigned_to": anusha_name,
                    "assigned_to_name": anusha_name,
                    "presales_agent": anusha_name,
                    "updated_at": now_iso,
                    "updated_at_dt": now_dt,
                }
            },
        )

    print(f"Deactivated user: {not already_inactive}")
    print(f"Reassigned open leads: {len(open_leads)}")
    print("Done.")


if __name__ == "__main__":
    main()
