#!/usr/bin/env python3
"""
backfill_wa_unknown_leads.py
============================
Create CRM leads for WhatsApp peers that have no matching lead (unknown threads).

Assigns each new lead to Admin (full_name == "Admin"). Project left empty.
Idempotent — safe to re-run. Dry-run by default.

Usage (from backend/):
  python scripts/backfill_wa_unknown_leads.py
  python scripts/backfill_wa_unknown_leads.py --apply
  python scripts/backfill_wa_unknown_leads.py --apply --limit 50
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="Write leads (default: dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="Max leads to create (0 = no limit)")
    ap.add_argument("--wati-names", action="store_true", help="Call WATI getMessages when local sender_name missing")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL", "")
    db_name = os.environ.get("DB_NAME", "")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME not set", file=sys.stderr)
        sys.exit(1)

    from crm.core.state import db  # noqa: E402 — after dotenv
    from crm.services.whatsapp_service import (  # noqa: E402
        _inbox_aggregate_peers,
        _wati_get_history,
        create_whatsapp_unknown_lead,
        resolve_admin_wa_assignee,
    )
    from crm.utils.helpers import normalize_phone

    admin = await resolve_admin_wa_assignee()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print("=" * 72)
    print(f"  backfill_wa_unknown_leads.py  [{mode}]  DB={db_name}")
    print(f"  Admin: {admin}")
    print("=" * 72)

    peers = await _inbox_aggregate_peers(5000)
    created = 0
    skipped = 0
    would_create = 0

    for peer, last in peers:
        normalized = normalize_phone(peer)
        if not normalized or len(normalized) != 10:
            skipped += 1
            continue
        existing = await db.leads.find_one({"normalized_phone": normalized}, {"_id": 0, "id": 1})
        if existing:
            skipped += 1
            continue

        sender_name = ""
        cursor = (
            db.whatsapp_messages.find(
                {
                    "$or": [
                        {"source": peer, "direction": "inbound"},
                        {"destination": peer, "direction": "outbound"},
                    ]
                },
                {"_id": 0, "sender_name": 1, "created_at_dt": 1},
            )
            .sort("created_at_dt", -1)
            .limit(20)
        )
        async for m in cursor:
            sn = (m.get("sender_name") or "").strip()
            if sn:
                sender_name = sn
                break

        if not sender_name and args.wati_names:
            history = await _wati_get_history(peer, page_size=20, max_pages=1)
            for m in history:
                sn = (m.get("sender_name") or "").strip()
                if sn:
                    sender_name = sn
                    break

        would_create += 1
        label = sender_name or f"WhatsApp {normalized[-4:]}"
        print(f"  + {normalized}  name={label!r}")

        if not args.apply:
            if args.limit and would_create >= args.limit:
                break
            continue

        lead = await create_whatsapp_unknown_lead(
            peer,
            sender_name,
            backfill=True,
            notify=False,
        )
        if lead:
            created += 1
        if args.limit and created >= args.limit:
            break

    print("-" * 72)
    print(f"  would_create={would_create}  created={created}  skipped={skipped}")
    if not args.apply:
        print("  (dry-run — pass --apply to write)")


if __name__ == "__main__":
    asyncio.run(main())
