"""
Idempotent upsert for the internal platform operator account.
Safe to run multiple times on production.

Usage (from backend/):
  python scripts/provision_platform_operator.py

Requires MONGO_URL, DB_NAME in environment (or .env).
Optional: PLATFORM_OPERATOR_EMAIL, SEED_DEFAULT_PASSWORD
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env")

from crm.core.state import hash_password, iso_utc_now, utc_now  # noqa: E402

DEFAULT_EMAIL = "yogansh@claraai.tech"
DEFAULT_FULL_NAME = "Clara Ops"
DEFAULT_PASSWORD = os.getenv("SEED_DEFAULT_PASSWORD", "Arihant@2026")


async def main() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: Set MONGO_URL and DB_NAME")
        sys.exit(1)

    email = (os.getenv("PLATFORM_OPERATOR_EMAIL") or DEFAULT_EMAIL).strip().lower()
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    existing = await db.users.find_one({"email": {"$regex": f"^{email}$", "$options": "i"}}, {"_id": 0})
    now_dt = utc_now()
    now_iso = iso_utc_now()

    if existing:
        user_id = existing["id"]
        await db.users.update_one(
            {"id": user_id},
            {
                "$set": {
                    "email": email,
                    "full_name": existing.get("full_name") or DEFAULT_FULL_NAME,
                    "role": "admin",
                    "is_active": True,
                    "updated_at": now_iso,
                    "updated_at_dt": now_dt,
                }
            },
        )
        print(f"Updated platform operator: {email} (id={user_id})")
    else:
        user_id = str(uuid.uuid4())
        await db.users.insert_one(
            {
                "id": user_id,
                "email": email,
                "full_name": DEFAULT_FULL_NAME,
                "phone": None,
                "role": "admin",
                "hashed_password": hash_password(DEFAULT_PASSWORD),
                "is_active": True,
                "current_session_id": None,
                "notification_dismissals": [],
                "created_at": now_iso,
                "created_at_dt": now_dt,
                "updated_at": now_iso,
                "updated_at_dt": now_dt,
            }
        )
        print(f"Created platform operator: {email} (id={user_id})")
        print(f"Default password: {DEFAULT_PASSWORD}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
