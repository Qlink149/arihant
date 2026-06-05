"""
Provision a CRM user (rep, manager, or admin) from environment variables.
Run from backend/: python scripts/create_user.py

Requires: MONGO_URL, DB_NAME, USER_EMAIL, USER_PASSWORD
Optional: USER_NAME (defaults to local part of email), USER_ROLE (defaults to rep)
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

from scripts._user_provision import normalize_role, upsert_user  # noqa: E402


async def main() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    email = (os.getenv("USER_EMAIL") or "").strip().lower()
    password = os.getenv("USER_PASSWORD") or ""
    full_name = (os.getenv("USER_NAME") or "").strip()
    role_raw = os.getenv("USER_ROLE") or "rep"

    if not mongo_url or not db_name:
        print("ERROR: Set MONGO_URL and DB_NAME")
        sys.exit(1)
    if not email or not password:
        print("ERROR: Set USER_EMAIL and USER_PASSWORD")
        sys.exit(1)

    if not full_name:
        full_name = email.split("@")[0] or "User"

    try:
        role = normalize_role(role_raw)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    try:
        user_id, created = await upsert_user(
            db,
            email=email,
            password=password,
            full_name=full_name,
            role=role,
        )
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        client.close()

    verb = "Created" if created else "Updated"
    print(f"{verb} {role} user: {email} (id={user_id})")


if __name__ == "__main__":
    asyncio.run(main())
