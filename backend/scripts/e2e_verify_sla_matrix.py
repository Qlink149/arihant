"""
Disposable e2e matrix: prove major status SLA timers fire via process_all_slas.

Loads backend/.env.e2e only. Never touches arihant_crm.

Usage (from backend/):
  python scripts/e2e_verify_sla_matrix.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

os.environ["E2E_ENV_FILE"] = str(BACKEND_ROOT / ".env.e2e")
from scripts.e2e_cleanup import assert_safe_e2e_target, cleanup_run, load_e2e_env  # noqa: E402

load_e2e_env()
assert_safe_e2e_target()
if os.environ.get("DB_NAME") != "arihant_crm_e2e":
    raise SystemExit(f"REFUSE: DB_NAME={os.environ.get('DB_NAME')!r}")

from crm.core.state import db  # noqa: E402
from crm.services.sla_engine import SLAEngineService  # noqa: E402

AssertFn = Callable[[Dict[str, Any], Dict[str, Any]], asyncio.Future]


def _phone() -> str:
    return f"91{uuid.uuid4().int % 10**10:010d}"


async def _base_lead(
    *,
    run_id: str,
    rep: dict,
    status: str,
    entered: datetime,
    extra: Optional[dict] = None,
) -> dict:
    lead_id = str(uuid.uuid4())
    phone = _phone()
    doc = {
        "id": lead_id,
        "first_name": f"E2E_SLA_{status[:8].replace(' ', '')}_{run_id[:6]}",
        "last_name": "Matrix",
        "phone": phone,
        "normalized_phone": phone,
        "lead_status": status,
        "project": "E2E Bold Project",
        "assigned_user_id": rep["id"],
        "assigned_to": rep.get("full_name") or "E2E Rep",
        "assigned_to_name": rep.get("full_name") or "E2E Rep",
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
    return doc


async def assert_task(lead: dict, *, sla_rule: str, threshold_prefix: str = "") -> bool:
    q: Dict[str, Any] = {
        "lead_id": lead["id"],
        "source": "sla",
        "sla_rule": sla_rule,
        "status": {"$in": ["pending", "in_progress"]},
    }
    if threshold_prefix:
        q["sla_threshold"] = {"$regex": f"^{threshold_prefix}"}
    task = await db.tasks.find_one(q, {"_id": 0, "sla_threshold": 1, "description": 1})
    return bool(task)


async def assert_flag(lead: dict, path_parts: List[str]) -> bool:
    refreshed = await db.leads.find_one({"id": lead["id"]}, {"_id": 0, "sla_flags": 1, "next_action_date": 1, "temperature": 1, "lead_status": 1})
    cur: Any = refreshed or {}
    for p in path_parts:
        if not isinstance(cur, dict) or p not in cur:
            return False
        cur = cur[p]
    return cur is not None


async def main() -> None:
    run_id = os.environ.get("E2E_RUN_ID") or str(uuid.uuid4())
    os.environ["E2E_RUN_ID"] = run_id
    now = datetime.now(timezone.utc)
    phones: List[str] = []

    rep = await db.users.find_one(
        {"email": os.environ.get("E2E_REP_EMAIL", "e2e-rep@arihant.local")},
        {"_id": 0, "id": 1, "full_name": 1},
    )
    if not rep:
        raise SystemExit("E2E refuse: seed e2e users first")

    cases: List[Tuple[str, dict, Callable]] = []

    # RNR — 4h biz → reminder (use 3d so bucket=3)
    rnr = await _base_lead(
        run_id=run_id,
        rep=rep,
        status="RNR",
        entered=now - timedelta(days=3),
        extra={"rnr_entered_at_dt": now - timedelta(days=3)},
    )
    phones.append(rnr["phone"])
    cases.append(("RNR reminder", rnr, lambda l: assert_task(l, sla_rule="rnr", threshold_prefix="reminder_")))

    # Contacted 48h
    contacted = await _base_lead(
        run_id=run_id,
        rep=rep,
        status="Contacted",
        entered=now - timedelta(hours=50),
        extra={"contacted_at_dt": now - timedelta(hours=50)},
    )
    phones.append(contacted["phone"])
    cases.append(("Contacted 48h", contacted, lambda l: assert_task(l, sla_rule="contacted", threshold_prefix="48h")))

    # Nurturing Hot 2d
    nurturing = await _base_lead(
        run_id=run_id,
        rep=rep,
        status="Nurturing",
        entered=now - timedelta(days=3),
        extra={
            "nurture_entered_at_dt": now - timedelta(days=3),
            "temperature": "Hot",
        },
    )
    phones.append(nurturing["phone"])
    cases.append(("Nurturing Hot 2d", nurturing, lambda l: assert_task(l, sla_rule="nurturing", threshold_prefix="hot_")))

    # Site Visit Scheduled — missing date
    sv = await _base_lead(
        run_id=run_id,
        rep=rep,
        status="Site Visit Scheduled",
        entered=now - timedelta(hours=2),
        extra={"visit_date_dt": None},
    )
    phones.append(sv["phone"])
    cases.append(
        ("SV Scheduled missing date", sv, lambda l: assert_task(l, sla_rule="visit_scheduled", threshold_prefix="missing_date"))
    )

    # Negotiation 48h
    nego = await _base_lead(
        run_id=run_id,
        rep=rep,
        status="Negotiation",
        entered=now - timedelta(hours=50),
        extra={"negotiation_entered_at_dt": now - timedelta(hours=50)},
    )
    phones.append(nego["phone"])
    cases.append(("Negotiation 48h", nego, lambda l: assert_task(l, sla_rule="negotiation", threshold_prefix="48h")))

    # Re-engaged 12h
    reeng = await _base_lead(
        run_id=run_id,
        rep=rep,
        status="Re-engaged",
        entered=now - timedelta(hours=14),
        extra={"reengaged_at_dt": now - timedelta(hours=14)},
    )
    phones.append(reeng["phone"])
    cases.append(("Re-engaged 12h", reeng, lambda l: assert_task(l, sla_rule="reengaged", threshold_prefix="12h")))

    # Gone Cold 30d
    cold = await _base_lead(
        run_id=run_id,
        rep=rep,
        status="Gone Cold",
        entered=now - timedelta(days=35),
        extra={"gone_cold_entered_at_dt": now - timedelta(days=35)},
    )
    phones.append(cold["phone"])
    cases.append(("Gone Cold 30d", cold, lambda l: assert_task(l, sla_rule="gone_cold", threshold_prefix="30d")))

    # Future Prospect 90d
    fp = await _base_lead(
        run_id=run_id,
        rep=rep,
        status="Future Prospect",
        entered=now - timedelta(days=95),
        extra={"future_prospect_entered_at_dt": now - timedelta(days=95)},
    )
    phones.append(fp["phone"])
    cases.append(("Future Prospect 90d", fp, lambda l: assert_task(l, sla_rule="future_prospect", threshold_prefix="90d")))

    # Interested 7d → NAD mutation
    interested = await _base_lead(
        run_id=run_id,
        rep=rep,
        status="Interested",
        entered=now - timedelta(days=8),
        extra={"interested_at_dt": now - timedelta(days=8)},
    )
    phones.append(interested["phone"])

    async def assert_interested(l: dict) -> bool:
        refreshed = await db.leads.find_one({"id": l["id"]}, {"_id": 0, "next_action_date": 1, "sla_flags": 1})
        flags = ((refreshed or {}).get("sla_flags") or {}).get("interested") or {}
        return bool(flags.get("7d_at_dt")) or bool((refreshed or {}).get("next_action_date"))

    cases.append(("Interested 7d", interested, assert_interested))

    # Visit Completed 3d → NAD
    vc = await _base_lead(
        run_id=run_id,
        rep=rep,
        status="Visit Completed",
        entered=now - timedelta(days=4),
        extra={
            "visit_completed_at_dt": now - timedelta(days=4),
            "visit_sla_reference_dt": now - timedelta(days=4),
        },
    )
    phones.append(vc["phone"])

    async def assert_vc(l: dict) -> bool:
        return await assert_flag(l, ["sla_flags", "visit_completed", "3d_at_dt"])

    cases.append(("Visit Completed 3d", vc, assert_vc))

    await db.cron_locks.delete_many({"job": "process_slas"})
    engine = SLAEngineService()
    with patch("crm.services.sla_engine.is_business_hours_ist", return_value=True):
        result = await engine.process_all_slas()
    print("process_all_slas=", result)
    if result.get("skipped"):
        raise SystemExit(f"REFUSE: skipped {result}")

    results: List[Tuple[str, bool]] = []
    for name, lead, checker in cases:
        ok = await checker(lead)
        results.append((name, ok))
        print(f"CASE {name}: {'PASS' if ok else 'FAIL'} lead={lead['id']}")

    # Cleanup
    try:
        from pymongo import MongoClient

        client = MongoClient(os.environ["MONGO_URL"])
        cleanup_run(client[os.environ["DB_NAME"]], phones=phones, run_id=run_id)
        client.close()
        print("cleanup_ok run_id=", run_id)
    except Exception as e:
        print("cleanup_warning=", e)
        await db.leads.delete_many({"e2e_run_id": run_id})
        await db.tasks.delete_many({"lead_id": {"$in": [c[1]["id"] for c in cases]}})

    failed = [n for n, ok in results if not ok]
    print("SUMMARY passed=", sum(1 for _, ok in results if ok), "failed=", len(failed), failed)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
