"""
Seed disposable Admin + rep users into arihant_crm_e2e only.

Usage (from backend/):
  set E2E_ENV_FILE=.env.e2e
  python scripts/seed_e2e_users.py

Creates:
  Admin  — full_name "Admin" (required for WA #27 assignment lookup)
  Rep    — assignee for nudge / bulk tests
  Manager — ops manager (Escalations E2E)
  GM     — general_manager / Shariff-like (Escalations + rep surfaces)
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.e2e_cleanup import assert_safe_e2e_target, load_e2e_env  # noqa: E402

load_e2e_env()
assert_safe_e2e_target()

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from scripts._user_provision import upsert_user  # noqa: E402


async def main() -> None:
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    admin_email = (os.getenv("E2E_ADMIN_EMAIL") or "e2e-admin@arihant.local").strip().lower()
    admin_password = os.getenv("E2E_ADMIN_PASSWORD") or "E2eAdmin!Pass123"
    rep_email = (os.getenv("E2E_REP_EMAIL") or "e2e-rep@arihant.local").strip().lower()
    rep_password = os.getenv("E2E_REP_PASSWORD") or "E2eRep!Pass123"
    manager_email = (os.getenv("E2E_MANAGER_EMAIL") or "e2e-manager@arihant.local").strip().lower()
    manager_password = os.getenv("E2E_MANAGER_PASSWORD") or "E2eManager!Pass123"
    gm_email = (os.getenv("E2E_GM_EMAIL") or "shariff@arihants.co.in").strip().lower()
    gm_password = os.getenv("E2E_GM_PASSWORD") or "E2eGm!Pass123"

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    try:
        admin_id, admin_created = await upsert_user(
            db,
            email=admin_email,
            password=admin_password,
            full_name="Admin",
            role="admin",
        )
        rep_id, rep_created = await upsert_user(
            db,
            email=rep_email,
            password=rep_password,
            full_name="E2E Rep",
            role="rep",
        )
        manager_id, manager_created = await upsert_user(
            db,
            email=manager_email,
            password=manager_password,
            full_name="E2E Manager",
            role="manager",
        )
        gm_id, gm_created = await upsert_user(
            db,
            email=gm_email,
            password=gm_password,
            full_name="shariff",
            role="general_manager",
        )
    finally:
        client.close()

    print(f"DB={db_name}")
    print(f"{'Created' if admin_created else 'Updated'} Admin: {admin_email} id={admin_id}")
    print(f"{'Created' if rep_created else 'Updated'} Rep: {rep_email} id={rep_id}")
    print(f"{'Created' if manager_created else 'Updated'} Manager: {manager_email} id={manager_id}")
    print(f"{'Created' if gm_created else 'Updated'} GM: {gm_email} id={gm_id}")


if __name__ == "__main__":
    asyncio.run(main())
