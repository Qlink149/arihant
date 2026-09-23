"""
Disposable e2e proof: RNR SLA legacy (Phase 2) and Phase 3 ladder.

Loads backend/.env.e2e only. Never touches arihant_crm.

Usage (from backend/):
  python scripts/e2e_verify_rnr_sla.py
  python scripts/e2e_verify_rnr_sla.py --legacy-only
  python scripts/e2e_verify_rnr_sla.py --phase3-only
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

os.environ["E2E_ENV_FILE"] = str(BACKEND_ROOT / ".env.e2e")
from scripts.e2e_cleanup import assert_safe_e2e_target, cleanup_run, load_e2e_env  # noqa: E402

load_e2e_env()
assert_safe_e2e_target()
if os.environ.get("DB_NAME") != "arihant_crm_e2e":
    raise SystemExit(f"REFUSE: DB_NAME={os.environ.get('DB_NAME')!r}")

os.environ.setdefault("PYTHONPATH", str(BACKEND_ROOT))
from crm.core.state import db  # noqa: E402
from crm.services.sla_engine import SLAEngineService  # noqa: E402


def _phone() -> str:
    return f"91{uuid.uuid4().int % 10**10:010d}"


async def _seed_rnr_lead(
    *,
    run_id: str,
    rep: dict,
    entered: datetime,
    extra: Optional[dict] = None,
) -> tuple[str, str]:
    lead_id = str(uuid.uuid4())
    phone = _phone()
    doc = {
        "id": lead_id,
        "first_name": f"E2E_RNR_{run_id[:8]}",
        "last_name": "Verify",
        "phone": phone,
        "normalized_phone": phone,
        "lead_status": "RNR",
        "project": "E2E Bold Project",
        "pool_key": "reserve-16",
        "assigned_user_id": rep["id"],
        "assigned_to": rep.get("full_name") or "E2E Rep",
        "assigned_to_name": rep.get("full_name") or "E2E Rep",
        "rnr_entered_at_dt": entered,
        "updated_at_dt": entered,
        "created_at_dt": entered,
        "sla_paused": False,
        "sla_flags": {},
        "e2e_run_id": run_id,
        "meta": {"e2e_run_id": run_id},
    }
    if extra:
        doc.update(extra)
    await db.leads.insert_one(doc)
    return lead_id, phone


async def _run_slas() -> dict:
    await db.cron_locks.delete_many({"job": "process_slas"})
    engine = SLAEngineService()
    with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
        result = await engine.process_all_slas()
    if result.get("skipped"):
        raise SystemExit(f"REFUSE: process_all_slas skipped: {result}")
    return result


async def verify_legacy(run_id: str, rep: dict) -> tuple[bool, str, str]:
    """Phase 2 path: 4-business-hour buckets + 24h/48h escalate flags."""
    os.environ.pop("SLA_PHASE3_RULES_ENABLED", None)
    now = datetime.now(timezone.utc)
    lead_id, phone = await _seed_rnr_lead(
        run_id=run_id,
        rep=rep,
        entered=now - timedelta(days=3),
    )
    result = await _run_slas()
    print("legacy process_all_slas=", result)

    task = await db.tasks.find_one(
        {
            "lead_id": lead_id,
            "source": "sla",
            "sla_rule": "rnr",
            "description": "RNR Reminder",
        },
        {"_id": 0, "id": 1, "sla_threshold": 1, "status": 1, "dedupe_key": 1},
    )
    refreshed = await db.leads.find_one({"id": lead_id}, {"_id": 0, "sla_flags.rnr": 1})
    flags = ((refreshed or {}).get("sla_flags") or {}).get("rnr") or {}
    ok = bool(task) and any(k.startswith("reminder_") for k in flags)
    print("legacy task=", task)
    print("legacy rnr_flags=", flags)
    print("LEGACY_VERIFY_OK=" + str(ok))
    return ok, lead_id, phone


async def verify_phase3(run_id: str, rep: dict) -> tuple[bool, List[str]]:
    """Phase 3 path: calendar reminders + D7 admin escalation (no legacy 24h/48h)."""
    os.environ["SLA_PHASE3_RULES_ENABLED"] = "true"
    now = datetime.now(timezone.utc)
    phones: List[str] = []
    failures: List[str] = []

    # Day-2 reminder (a2)
    lead_a2, phone_a2 = await _seed_rnr_lead(
        run_id=run_id,
        rep=rep,
        entered=now - timedelta(hours=30),
        extra={"first_name": f"E2E_RNR_A2_{run_id[:6]}"},
    )
    phones.append(phone_a2)

    # D7 escalation
    lead_d7, phone_d7 = await _seed_rnr_lead(
        run_id=run_id,
        rep=rep,
        entered=now - timedelta(hours=150),
        extra={"first_name": f"E2E_RNR_D7_{run_id[:6]}"},
    )
    phones.append(phone_d7)

    result = await _run_slas()
    print("phase3 process_all_slas=", result)

    task_a2 = await db.tasks.find_one(
        {
            "lead_id": lead_a2,
            "source": "sla",
            "sla_rule": "rnr",
            "sla_threshold": "reminder_a2",
        },
        {"_id": 0, "sla_threshold": 1, "description": 1},
    )
    flags_a2 = (
        ((await db.leads.find_one({"id": lead_a2}, {"sla_flags.rnr": 1})) or {})
        .get("sla_flags", {})
        .get("rnr", {})
    )
    if not task_a2 or not flags_a2.get("reminder_a2_at_dt"):
        failures.append("phase3_reminder_a2")
    print("phase3 a2 task=", task_a2, "flags=", flags_a2)

    task_d7 = await db.tasks.find_one(
        {
            "lead_id": lead_d7,
            "source": "sla",
            "sla_rule": "rnr",
            "sla_threshold": "escalate_d7",
        },
        {"_id": 0, "sla_threshold": 1},
    )
    lead_d7_doc = await db.leads.find_one(
        {"id": lead_d7},
        {"_id": 0, "sla_flags.rnr": 1, "escalation": 1},
    )
    flags_d7 = ((lead_d7_doc or {}).get("sla_flags") or {}).get("rnr") or {}
    escalation = (lead_d7_doc or {}).get("escalation") or {}
    if not task_d7 or not flags_d7.get("escalate_d7_at_dt"):
        failures.append("phase3_escalate_d7_task")
    if not escalation.get("active"):
        failures.append("phase3_escalation_queue_raise")
    print("phase3 d7 task=", task_d7, "flags=", flags_d7, "escalation=", escalation)

    # Legacy thresholds must not fire on phase3 leads
    legacy_24 = await db.tasks.find_one(
        {"lead_id": {"$in": [lead_a2, lead_d7]}, "sla_threshold": "24h"},
        {"_id": 0, "sla_threshold": 1},
    )
    if legacy_24:
        failures.append("legacy_24h_leaked_under_phase3")

    ok = not failures
    print("PHASE3_VERIFY_OK=" + str(ok), "failures=", failures)
    return ok, phones


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-only", action="store_true")
    parser.add_argument("--phase3-only", action="store_true")
    args = parser.parse_args()
    run_legacy = not args.phase3_only
    run_phase3 = not args.legacy_only

    run_id = os.environ.get("E2E_RUN_ID") or str(uuid.uuid4())
    os.environ["E2E_RUN_ID"] = run_id
    phones: List[str] = []
    failures: List[str] = []

    rep = await db.users.find_one(
        {"email": os.environ.get("E2E_REP_EMAIL", "e2e-rep@arihant.local")},
        {"_id": 0, "id": 1, "full_name": 1},
    )
    if not rep:
        raise SystemExit("E2E refuse: seed e2e users first (scripts/seed_e2e_users.py)")

    if run_legacy:
        ok, _lid, phone = await verify_legacy(run_id, rep)
        phones.append(phone)
        if not ok:
            failures.append("legacy")

    if run_phase3:
        ok_p3, p3_phones = await verify_phase3(run_id, rep)
        phones.extend(p3_phones)
        if not ok_p3:
            failures.append("phase3")

    # Fresh acquire after clear must succeed with owner token (not ms equality)
    await db.cron_locks.delete_many({"job": "process_slas"})
    lock_engine = SLAEngineService()
    acquired = await lock_engine._acquire_cron_lock(datetime.now(timezone.utc))
    lock_doc = await db.cron_locks.find_one({"job": "process_slas"}, {"_id": 0})
    print("fresh_lock_acquire=", acquired, "lock_doc=", lock_doc)
    if not acquired:
        failures.append("fresh_lock_acquire")

    try:
        from pymongo import MongoClient

        client = MongoClient(os.environ["MONGO_URL"])
        cleanup_run(client[os.environ["DB_NAME"]], phones=phones, run_id=run_id)
        client.close()
        print("cleanup_ok run_id=", run_id)
    except Exception as e:
        print("cleanup_warning=", e)

    if failures:
        raise SystemExit(f"VERIFY_FAILED: {failures}")


if __name__ == "__main__":
    asyncio.run(main())
