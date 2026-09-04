"""
Read-only audit of leads with future created_at / created_at_dt.

- Reads DB_NAME from backend/.env (expects arihant_crm for prod audit)
- NEVER writes to Mongo
- Prints counts, May-22-2026 ObjectId cluster sample, and repair recommendations

Usage (from backend/):
  python scripts/audit_future_created_at.py
  python scripts/audit_future_created_at.py --limit 50
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pymongo import MongoClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env", override=True)


def _mask_phone(phone: Any) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) >= 4:
        return "***" + digits[-4:]
    return "n/a"


def _as_utc(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _display_name(doc: Dict[str, Any]) -> str:
    name = (doc.get("name") or "").strip()
    if name:
        return name
    return f"{(doc.get('first_name') or '').strip()} {(doc.get('last_name') or '').strip()}".strip() or "(no name)"


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only future created_at audit")
    parser.add_argument("--limit", type=int, default=50, help="Max sample rows to print")
    args = parser.parse_args()

    db_name = os.getenv("DB_NAME")
    url = os.getenv("MONGO_URL")
    if not url or not db_name:
        print("REFUSE: MONGO_URL / DB_NAME missing")
        return 2
    if db_name != "arihant_crm":
        print(f"REFUSE: unexpected DB_NAME={db_name!r} (expected arihant_crm for this audit)")
        return 2

    now = datetime.now(timezone.utc)
    client = MongoClient(url, serverSelectionTimeoutMS=20000)
    col = client[db_name]["leads"]

    # Future via BSON datetime field
    future_dt_q = {"created_at_dt": {"$gt": now}}
    # String-only fallback where created_at_dt missing and ISO string > now
    future_str_q = {
        "created_at_dt": {"$exists": False},
        "created_at": {"$gt": now.isoformat()},
    }
    union_q = {"$or": [future_dt_q, future_str_q]}

    n_dt = col.count_documents(future_dt_q)
    n_str = col.count_documents(future_str_q)
    n_all = col.count_documents(union_q)

    print("=== FUTURE CREATED_AT AUDIT (read-only) ===")
    print(f"db={db_name} now_utc={now.isoformat()}")
    print(f"future_created_at_dt={n_dt}")
    print(f"future_created_at_string_only={n_str}")
    print(f"future_total={n_all}")
    print()

    proj = {
        "_id": 1,
        "name": 1,
        "first_name": 1,
        "last_name": 1,
        "lead_status": 1,
        "lead_source": 1,
        "source": 1,
        "most_recent_source": 1,
        "project": 1,
        "project_interested": 1,
        "created_at": 1,
        "created_at_dt": 1,
        "updated_at": 1,
        "updated_at_dt": 1,
        "normalized_phone": 1,
        "phone": 1,
        "assigned_to_name": 1,
        "import_batch_id": 1,
    }

    docs: List[Dict[str, Any]] = list(
        col.find(union_q, proj).sort("created_at_dt", -1).limit(max(args.limit, 1))
    )

    by_status = Counter()
    by_source = Counter()
    by_oid_day = Counter()
    by_created_month = Counter()
    updated_before_created = 0

    for d in docs:
        by_status[d.get("lead_status") or "(none)"] += 1
        src = d.get("most_recent_source") or d.get("lead_source") or d.get("source") or "(none)"
        by_source[src] += 1
        oid_day = d["_id"].generation_time.strftime("%Y-%m-%d")
        by_oid_day[oid_day] += 1
        cdt = _as_utc(d.get("created_at_dt")) or _as_utc(d.get("created_at"))
        if cdt:
            by_created_month[cdt.strftime("%Y-%m")] += 1
        udt = _as_utc(d.get("updated_at_dt")) or _as_utc(d.get("updated_at"))
        if cdt and udt and udt < cdt:
            updated_before_created += 1

    # Full-set aggregations (not just sample) for oid day / status
    print("=== FULL-SET BREAKDOWNS ===")
    pipeline_status = [
        {"$match": future_dt_q},
        {"$group": {"_id": "$lead_status", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]
    status_full = {r["_id"] or "(none)": r["n"] for r in col.aggregate(pipeline_status)}
    print("by_status:", status_full)

    pipeline_src = [
        {"$match": future_dt_q},
        {
            "$group": {
                "_id": {
                    "$ifNull": [
                        "$most_recent_source",
                        {"$ifNull": ["$lead_source", {"$ifNull": ["$source", "(none)"]}]},
                    ]
                },
                "n": {"$sum": 1},
            }
        },
        {"$sort": {"n": -1}},
        {"$limit": 20},
    ]
    print("by_source:", {r["_id"]: r["n"] for r in col.aggregate(pipeline_src)})

    # ObjectId day via $toDate on _id
    pipeline_oid = [
        {"$match": future_dt_q},
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": {"$toDate": "$_id"},
                        "timezone": "UTC",
                    }
                },
                "n": {"$sum": 1},
            }
        },
        {"$sort": {"n": -1}},
        {"$limit": 15},
    ]
    print("by_objectid_utc_day:", {r["_id"]: r["n"] for r in col.aggregate(pipeline_oid)})

    pipeline_month = [
        {"$match": future_dt_q},
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": "%Y-%m",
                        "date": "$created_at_dt",
                        "timezone": "UTC",
                    }
                },
                "n": {"$sum": 1},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    print("by_created_at_dt_month:", {r["_id"]: r["n"] for r in col.aggregate(pipeline_month)})
    print()

    print(f"=== SAMPLE (limit={args.limit}, sample_size={len(docs)}) ===")
    print(f"sample_updated_before_created={updated_before_created}")
    for i, d in enumerate(docs, 1):
        oid_t = d["_id"].generation_time
        cdt = _as_utc(d.get("created_at_dt")) or _as_utc(d.get("created_at"))
        days_ahead = (cdt - now).days if cdt else "?"
        print(
            f"{i:02d}. {_display_name(d)!r} | status={d.get('lead_status')!r} | "
            f"src={d.get('most_recent_source') or d.get('lead_source') or d.get('source')} | "
            f"proj={d.get('project') or d.get('project_interested')} | "
            f"created_at={d.get('created_at')!r} | created_at_dt={d.get('created_at_dt')!r} | "
            f"updated={d.get('updated_at_dt') or d.get('updated_at')!r} | "
            f"oid={oid_t.date()} | days_ahead={days_ahead} | phone={_mask_phone(d.get('normalized_phone') or d.get('phone'))}"
        )

    print()
    print("=== REPAIR PLAN (no writes performed) ===")
    print("1. Prefer fixing created_at/created_at_dt from a trusted source export if available.")
    print("2. Fallback: set created_at_dt to ObjectId generation time (import day) and mirror ISO created_at.")
    print("3. Do NOT bump created_at to 'now' — that would pollute Today's New Leads again.")
    print("4. Metric clamp (created_at_dt <= now) already excludes these from todays_leads until repaired.")
    print("5. Require explicit prod-write approval before any updateMany / repair script.")
    print()
    print("DONE read-only")
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
