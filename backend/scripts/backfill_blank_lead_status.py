"""Backfill empty lead_status -> New (create form used to send "")."""
from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from crm.core.state import db, iso_utc_now, utc_now  # noqa: E402


async def main() -> None:
    now_dt = utc_now()
    now_iso = iso_utc_now()
    q = {
        "$or": [
            {"lead_status": ""},
            {"lead_status": None},
            {"lead_status": {"$exists": False}},
        ]
    }
    total = await db.leads.count_documents(q)
    print(f"blank_status_leads={total}")
    result = await db.leads.update_many(
        q,
        {"$set": {"lead_status": "New", "updated_at": now_iso, "updated_at_dt": now_dt}},
    )
    print(f"updated={result.modified_count}")


if __name__ == "__main__":
    asyncio.run(main())
