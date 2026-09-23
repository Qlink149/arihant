#!/usr/bin/env python3
"""Pre-mark SLA flags for leads already past threshold (Phase 3 T0).

Dry-run by default. --apply writes the flag timestamp so the first cron tick
does not mass-fire the backlog.

Usage (from backend/):
  python scripts/premark_sla_backlog.py
  python scripts/premark_sla_backlog.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from crm.constants.lead_status import is_terminal_lead_status  # noqa: E402

RULES = [
    {
        "name": "rnr_transfer_d4",
        "status": "RNR",
        "field": "rnr_entered_at_dt",
        "delta": timedelta(hours=72),
        "flag": "sla_flags.rnr.transfer_d4_at_dt",
    },
    {
        "name": "rnr_escalate_d7",
        "status": "RNR",
        "field": "rnr_entered_at_dt",
        "delta": timedelta(hours=144),
        "flag": "sla_flags.rnr.escalate_d7_at_dt",
    },
    {
        "name": "interested_followup_7d",
        "status": "Interested",
        "field": "interested_entered_at_dt",
        "delta": timedelta(days=7),
        "flag": "sla_flags.interested.followup_task_7d_at_dt",
    },
    {
        "name": "contacted_reassign_7d",
        "status": "Contacted",
        "field": "contacted_at_dt",
        "delta": timedelta(days=7),
        "flag": "sla_flags.contacted.reassigned_7d_at_dt",
    },
    {
        "name": "visit_completed_feedback_2h",
        "status": "Visit Completed",
        "field": "visit_completed_at_dt",
        "delta": timedelta(hours=2),
        "flag": "sla_flags.visit_completed.feedback_2h_at_dt",
    },
    {
        "name": "visit_completed_escalate_72h",
        "status": "Visit Completed",
        "field": "visit_completed_at_dt",
        "delta": timedelta(hours=72),
        "flag": "sla_flags.visit_completed.escalate_72h_at_dt",
    },
    {
        "name": "sv_followup_1_escalate_72h",
        "status": "SV Follow-up 1",
        "field": "sv_followup_1_entered_at_dt",
        "delta": timedelta(hours=72),
        "flag": "sla_flags.sv_followup_1.escalate_72h_at_dt",
    },
    {
        "name": "sv_followup_2_escalate_72h",
        "status": "SV Follow-up 2",
        "field": "sv_followup_2_entered_at_dt",
        "delta": timedelta(hours=72),
        "flag": "sla_flags.sv_followup_2.escalate_72h_at_dt",
    },
    {
        "name": "nurturing_hot_escalate_14d",
        "status": "Nurturing",
        "field": "nurture_entered_at_dt",
        "delta": timedelta(days=14),
        "flag": "sla_flags.nurturing.hot_escalate_14d_at_dt",
        "extra": {"temperature": {"$regex": r"^\s*hot\s*$", "$options": "i"}},
    },
    {
        "name": "interested_escalate_14d",
        "status": "Interested",
        "field": "interested_entered_at_dt",
        "delta": timedelta(days=14),
        "flag": "sla_flags.interested.escalate_14d_at_dt",
    },
]

RNR_REMINDER_SLOTS = (
    ("reminder_a1", timedelta(hours=0)),
    ("reminder_a2", timedelta(hours=24)),
    ("reminder_a3", timedelta(hours=48)),
    ("reminder_b1", timedelta(hours=72)),
    ("reminder_b2", timedelta(hours=96)),
    ("reminder_b3", timedelta(hours=120)),
)


def _base_match(status: str, extra: dict | None = None) -> dict:
    q: dict = {
        "lead_status": {"$regex": f"^\\s*{status}\\s*$", "$options": "i"},
        "sla_paused": {"$ne": True},
    }
    if extra:
        q.update(extra)
    return q


def _count_and_ops(coll, rule: dict, now: datetime, apply: bool) -> tuple[int, Counter, list]:
    cutoff = now - rule["delta"]
    flag = rule["flag"]
    query = {
        **_base_match(rule["status"], rule.get("extra")),
        rule["field"]: {"$exists": True, "$ne": None, "$lt": cutoff},
        flag: {"$exists": False},
    }
    by_project: Counter = Counter()
    ops: list = []
    n = 0
    cursor = coll.find(
        query,
        {"_id": 0, "id": 1, "project": 1, "lead_status": 1, rule["field"]: 1},
    )
    for lead in cursor:
        if is_terminal_lead_status(lead.get("lead_status")):
            continue
        n += 1
        by_project[lead.get("project") or "(none)"] += 1
        if apply:
            ops.append(
                UpdateOne(
                    {"id": lead["id"], flag: {"$exists": False}},
                    {"$set": {flag: now}},
                )
            )
    return n, by_project, ops


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL", "")
    db_name = os.environ.get("DB_NAME", "")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME not set", file=sys.stderr)
        sys.exit(1)
    if db_name not in ("arihant_crm", "arihant_crm_e2e", "arihant_crm_test"):
        print(f"REFUSE: unexpected DB_NAME={db_name!r}", file=sys.stderr)
        sys.exit(2)

    print(f"Database: {db_name}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    if db_name == "arihant_crm" and args.apply:
        print("WARNING: applying against production database arihant_crm")

    client = MongoClient(mongo_url)
    coll = client[db_name].leads
    now = datetime.now(timezone.utc)

    all_ops: list = []
    for rule in RULES:
        n, by_project, ops = _count_and_ops(coll, rule, now, args.apply)
        print(f"\n{rule['name']}: {n}")
        for proj, c in sorted(by_project.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {proj}: {c}")
        all_ops.extend(ops)

    # RNR daily reminder slots (window A from entered_at; B slots from +72h)
    print("\n--- RNR reminder slots ---")
    for slot, delta in RNR_REMINDER_SLOTS:
        flag = f"sla_flags.rnr.{slot}_at_dt"
        rule = {
            "name": f"rnr_{slot}",
            "status": "RNR",
            "field": "rnr_entered_at_dt",
            "delta": delta,
            "flag": flag,
        }
        n, by_project, ops = _count_and_ops(coll, rule, now, args.apply)
        print(f"{rule['name']}: {n}")
        for proj, c in sorted(by_project.items(), key=lambda x: (-x[1], x[0]))[:8]:
            print(f"  {proj}: {c}")
        all_ops.extend(ops)

    if args.apply and all_ops:
        result = coll.bulk_write(all_ops, ordered=False)
        print(f"\nWrote modified={result.modified_count} matched={result.matched_count}")
    elif not args.apply:
        print("\nDry-run complete. Re-run with --apply to write.")
    else:
        print("\nNothing to write.")


if __name__ == "__main__":
    main()
