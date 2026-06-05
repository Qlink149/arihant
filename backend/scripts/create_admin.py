"""
Create the first admin user from environment variables.
Run once from backend/: python scripts/create_admin.py

Requires: MONGO_URL, DB_NAME, ADMIN_EMAIL, ADMIN_PASSWORD
Optional: ADMIN_NAME (defaults to "Admin")
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env")

from scripts._user_provision import upsert_user  # noqa: E402


async def main() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD") or ""
    full_name = (os.getenv("ADMIN_NAME") or "Admin").strip()

    if not mongo_url or not db_name:
        print("ERROR: Set MONGO_URL and DB_NAME")
        sys.exit(1)
    if not email or not password:
        print("ERROR: Set ADMIN_EMAIL and ADMIN_PASSWORD")
        sys.exit(1)

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    try:
        user_id, created = await upsert_user(
            db,
            email=email,
            password=password,
            full_name=full_name,
            role="admin",
        )
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        client.close()

    verb = "Created" if created else "Updated"
    print(f"{verb} admin user: {email} (id={user_id})")


if __name__ == "__main__":
    asyncio.run(main())
