#!/usr/bin/env python3
"""Read-only: compare MCUBE empemail values in calls/events vs CRM users.email."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _norm_email(value: str) -> str:
    return (value or "").strip().lower()


async def run() -> int:
    mongo_url = os.environ.get("MONGO_URL", "")
    db_name = os.environ.get("DB_NAME", "")
    if not mongo_url or not db_name:
        print("MONGO_URL and DB_NAME required", file=sys.stderr)
        return 1

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    emails: set[str] = set()
    async for doc in db.calls.find({"empemail": {"$exists": True, "$ne": ""}}, {"_id": 0, "empemail": 1}):
        e = _norm_email(doc.get("empemail") or "")
        if e:
            emails.add(e)

    async for doc in db.mcube_events.find({}, {"_id": 0, "raw_payload": 1}).limit(500):
        payload = doc.get("raw_payload") or {}
        if isinstance(payload, dict):
            e = _norm_email(str(payload.get("empemail") or payload.get("empEmail") or ""))
            if e:
                emails.add(e)

    users = await db.users.find({}, {"_id": 0, "email": 1, "full_name": 1, "is_active": 1}).to_list(500)
    user_by_email = {_norm_email(u.get("email") or ""): u for u in users if u.get("email")}

    matched = []
    missing = []
    for email in sorted(emails):
        user = user_by_email.get(email)
        if user:
            matched.append({"empemail": email, "user": user.get("full_name"), "active": user.get("is_active")})
        else:
            missing.append(email)

    report = {
        "db": db_name,
        "distinct_mcube_emails": len(emails),
        "matched_users": matched,
        "missing_in_crm": missing,
    }
    print(json.dumps(report, indent=2, default=str))
    client.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit MCUBE empemail vs CRM users")
    parser.parse_args()
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
