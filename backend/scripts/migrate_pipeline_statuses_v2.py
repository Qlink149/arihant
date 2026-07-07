"""One-time MongoDB migration for pipeline changes (v2).

Rules implemented:
1) SV Completed – Follow Up -> SV Follow-up 1
   - Sets sv_followup_1_entered_at_dt based on sv_followup_entered_at_dt/updated_at_dt/now
   - Sets next_action_date to +3 days (IST calendar) from the same reference
   - Unsets sv_followup_entered_at_dt and sla_flags.sv_followup.*

2) Reclassify imported (sla_paused=True) leads by original_fw_status:
   - Junk: Closed Lost -> Junk
   - Unqualified: Closed Lost -> Unqualified
   - Interested: Nurturing -> Interested (+ sets interested_entered_at_dt and next_action_date +7d)

This script performs direct Mongo updates and does NOT invoke lead_service (to avoid activating SLA).

Usage (from backend/):
  python scripts/migrate_pipeline_statuses_v2.py --dry-run
  python scripts/migrate_pipeline_statuses_v2.py --apply

Requires MONGO_URL and DB_NAME in backend/.env (or environment).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static_data"
sys.path.insert(0, str(BACKEND_ROOT))

IST = ZoneInfo("Asia/Kolkata")

load_dotenv(BACKEND_ROOT / ".env")

PAUSED_SCOPE = {"sla_paused": True}


def _env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name} (set in backend/.env)")
    return val


def _ist_date_plus_days(from_dt: datetime, days_ahead: int) -> str:
    base = from_dt.astimezone(IST).date()
    return (base + timedelta(days=days_ahead)).isoformat()


def _status_regex_exact(label: str) -> dict:
    import re

    escaped = re.escape(label.strip())
    return {"$regex": rf"^\s*{escaped}\s*$", "$options": "i"}


async def _count(leads, query: dict) -> int:
    return int(await leads.count_documents(query))


async def run_migration(*, dry_run: bool) -> Dict[str, Any]:
    mongo_url = _env("MONGO_URL")
    db_name = _env("DB_NAME")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    leads = db.leads

    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "db_name": db_name,
        "rules": [],
        "total_modified": 0,
        "total_would_update": 0,
    }

    # Rule 1: SV Completed – Follow Up -> SV Follow-up 1 (all leads, regardless of sla_paused)
    rule1_query = {"lead_status": _status_regex_exact("SV Completed – Follow Up")}
    rule1_matches = await _count(leads, rule1_query)
    report["rules"].append(
        {
            "rule": "sv_completed_to_sv_followup_1",
            "match_count": rule1_matches,
            "modified_count": 0,
        }
    )
    report["total_would_update"] += rule1_matches

    if not dry_run and rule1_matches:
        cursor = leads.find(rule1_query, {"_id": 1, "sv_followup_entered_at_dt": 1, "updated_at_dt": 1})
        modified = 0
        async for doc in cursor:
            ref = doc.get("sv_followup_entered_at_dt") or doc.get("updated_at_dt") or datetime.now(timezone.utc)
            if isinstance(ref, str):
                # best-effort; fallback to now
                ref = datetime.now(timezone.utc)
            if getattr(ref, "tzinfo", None) is None:
                ref = ref.replace(tzinfo=timezone.utc)
            patch = {
                "lead_status": "SV Follow-up 1",
                "sv_followup_1_entered_at_dt": ref,
                "next_action_date": _ist_date_plus_days(ref, 3),
            }
            unset = {
                "sv_followup_entered_at_dt": "",
                "sla_flags.sv_followup": "",
            }
            result = await leads.update_one({"_id": doc["_id"]}, {"$set": patch, "$unset": unset})
            if result.modified_count:
                modified += 1
        report["rules"][-1]["modified_count"] = modified
        report["total_modified"] += modified

    # Rule 2: reclassify imported leads by original_fw_status (sla_paused=True only)
    async def _reclassify(
        *,
        label: str,
        from_status: str,
        to_status: str,
        extra_set: Optional[dict] = None,
    ) -> None:
        nonlocal report
        q = {
            **PAUSED_SCOPE,
            "original_fw_status": _status_regex_exact(label),
            "lead_status": _status_regex_exact(from_status),
        }
        matches = await _count(leads, q)
        entry = {
            "rule": f"reclassify_fw_{label.lower()}",
            "match_count": matches,
            "from_status": from_status,
            "to_status": to_status,
            "modified_count": 0,
        }
        report["rules"].append(entry)
        report["total_would_update"] += matches
        if dry_run or not matches:
            return
        patch = {"lead_status": to_status, "sla_paused": True}
        if extra_set:
            patch.update(extra_set)
        result = await leads.update_many(q, {"$set": patch})
        entry["modified_count"] = int(result.modified_count)
        report["total_modified"] += int(result.modified_count)

    await _reclassify(label="Junk", from_status="Closed Lost", to_status="Junk")
    await _reclassify(label="Unqualified", from_status="Closed Lost", to_status="Unqualified")

    # Interested: also set interested_entered_at_dt and next_action_date (+7d) for a stable follow-up surface
    now_dt = datetime.now(timezone.utc)
    await _reclassify(
        label="Interested",
        from_status="Nurturing",
        to_status="Interested",
        extra_set={"interested_entered_at_dt": now_dt, "next_action_date": _ist_date_plus_days(now_dt, 7)},
    )

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = STATIC_DIR / f"pipeline_migration_report_{ts}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Report written to {report_path}")
    print(f"[{'dry-run' if dry_run else 'apply'}] would_update={report['total_would_update']:,} modified={report['total_modified']:,}")

    client.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate pipeline statuses (v2).")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Count only; do not write.")
    group.add_argument("--apply", action="store_true", help="Apply updates to MongoDB.")
    args = parser.parse_args()
    try:
        asyncio.run(run_migration(dry_run=bool(args.dry_run)))
    except RuntimeError as e:
        print(f"Error: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

