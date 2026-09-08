"""
Disposable e2e proof: RNR 4-business-hour reminder fires on process_all_slas.

Loads backend/.env.e2e only. Never touches arihant_crm.

Usage (from backend/):
  set E2E_ENV_FILE=.env.e2e
  python scripts/e2e_verify_rnr_sla.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

os.environ["E2E_ENV_FILE"] = str(BACKEND_ROOT / ".env.e2e")
from scripts.e2e_cleanup import assert_safe_e2e_target, load_e2e_env, cleanup_run  # noqa: E402

load_e2e_env()
assert_safe_e2e_target()
if os.environ.get("DB_NAME") != "arihant_crm_e2e":
    raise SystemExit(f"REFUSE: DB_NAME={os.environ.get('DB_NAME')!r}")

# Import app DB only after e2e env is loaded
os.environ.setdefault("PYTHONPATH", str(BACKEND_ROOT))
from crm.core.state import db  # noqa: E402
from crm.services.sla_engine import SLAEngineService  # noqa: E402


async def main() -> None:
    run_id = os.environ.get("E2E_RUN_ID") or str(uuid.uuid4())
    os.environ["E2E_RUN_ID"] = run_id
    now = datetime.now(timezone.utc)
    lead_id = str(uuid.uuid4())
    phone = f"91{uuid.uuid4().int % 10**10:010d}"

    rep = await db.users.find_one(
        {"email": os.environ.get("E2E_REP_EMAIL", "e2e-rep@arihant.local")},
        {"_id": 0, "id": 1, "full_name": 1},
    )
    if not rep:
        raise SystemExit("E2E refuse: seed e2e users first (scripts/seed_e2e_users.py)")

    # ~2 IST weekdays ago ⇒ well over 4 business hours
    rnr_entered = now - timedelta(days=3)

    lead = {
        "id": lead_id,
        "first_name": f"E2E_RNR_{run_id[:8]}",
        "last_name": "Verify",
        "phone": phone,
        "normalized_phone": phone,
        "lead_status": "RNR",
        "project": "E2E Bold Project",
        "assigned_user_id": rep["id"],
        "assigned_to": rep.get("full_name") or "E2E Rep",
        "assigned_to_name": rep.get("full_name") or "E2E Rep",
        "rnr_entered_at_dt": rnr_entered,
        "updated_at_dt": rnr_entered,
        "created_at_dt": rnr_entered,
        "sla_paused": False,
        "sla_flags": {},
        "e2e_run_id": run_id,
        "meta": {"e2e_run_id": run_id},
    }
    await db.leads.insert_one(lead)
    await db.cron_locks.delete_many({"job": "process_slas"})

    # Real lock acquire (owner-token fix) + forced business hours
    engine = SLAEngineService()
    with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
        result = await engine.process_all_slas()

    print("process_all_slas=", result)
    if result.get("skipped"):
        raise SystemExit(f"REFUSE: process_all_slas skipped: {result}")

    task = await db.tasks.find_one(
        {
            "lead_id": lead_id,
            "source": "sla",
            "sla_rule": "rnr",
            "description": "RNR Reminder",
        },
        {"_id": 0, "id": 1, "sla_threshold": 1, "status": 1, "dedupe_key": 1},
    )
    refreshed = await db.leads.find_one(
        {"id": lead_id},
        {"_id": 0, "sla_flags.rnr": 1},
    )
    flags = ((refreshed or {}).get("sla_flags") or {}).get("rnr") or {}

    ok = bool(task) and any(k.startswith("reminder_") for k in flags)
    print("task=", task)
    print("rnr_flags=", flags)
    print("VERIFY_OK=" + str(ok))

    # Fresh acquire after clear must succeed with owner token (not ms equality)
    await db.cron_locks.delete_many({"job": "process_slas"})
    lock_engine = SLAEngineService()
    acquired = await lock_engine._acquire_cron_lock(datetime.now(timezone.utc))
    lock_doc = await db.cron_locks.find_one({"job": "process_slas"}, {"_id": 0})
    print("fresh_lock_acquire=", acquired, "lock_doc=", lock_doc)
    if not acquired:
        raise SystemExit("REFUSE: fresh_lock_acquire=False after owner-token fix")

    try:
        from pymongo import MongoClient

        client = MongoClient(os.environ["MONGO_URL"])
        cleanup_run(client[os.environ["DB_NAME"]], phones=[phone], run_id=run_id)
        client.close()
        print("cleanup_ok run_id=", run_id)
    except Exception as e:
        print("cleanup_warning=", e)
        # Best-effort cascade for this lead
        await db.tasks.delete_many({"lead_id": lead_id})
        await db.notifications.delete_many({"lead_id": lead_id})
        await db.leads.delete_many({"id": lead_id, "e2e_run_id": run_id})

    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
