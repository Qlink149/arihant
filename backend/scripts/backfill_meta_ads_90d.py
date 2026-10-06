#!/usr/bin/env python3
"""
backfill_meta_ads_90d.py
========================
One-time backfill: pull the last ~90 days of Meta Ads Campaign/AdSet/Ad
performance into meta_ads_daily_metrics, once, before the daily cron job
(/v1/cron/sync-meta-ads, trailing 30-day window) takes over.

Not required for the daily sync to work - every reader already treats
coalesce_locations-style "whatever's there" as fine, and the daily job's
30-day window will backfill itself over the following month regardless.
This script only exists to get historical cost-per-lead trend data sooner
rather than waiting a month for it to accumulate.

Usage
-----
  # Preview (no writes) - estimates row count, does not call Meta
  python scripts/backfill_meta_ads_90d.py

  # Apply - makes the real Meta API calls and writes to meta_ads_daily_metrics
  python scripts/backfill_meta_ads_90d.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")
sys.path.insert(0, str(ROOT_DIR))

BACKFILL_WINDOW_DAYS = 90


async def run(*, apply: bool) -> int:
    from crm.core.state import META_ADS_ACCESS_TOKEN, META_ADS_ACCOUNT_IDS, db, utc_now

    if not META_ADS_ACCESS_TOKEN or not META_ADS_ACCOUNT_IDS:
        print("ERROR: META_ADS_ACCESS_TOKEN and META_ADS_ACCOUNT_IDS must be set in .env", file=sys.stderr)
        return 1

    now_dt = utc_now()
    since = (now_dt - timedelta(days=BACKFILL_WINDOW_DAYS)).strftime("%Y-%m-%d")
    until = now_dt.strftime("%Y-%m-%d")

    print(f"Accounts: {META_ADS_ACCOUNT_IDS}")
    print(f"Window: {since} to {until} ({BACKFILL_WINDOW_DAYS} days)")

    if not apply:
        from crm.services.meta_ads_sync_service import _get_paginated
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            total_campaigns = 0
            total_adsets = 0
            total_ads = 0
            for account_id in META_ADS_ACCOUNT_IDS:
                campaigns = await _get_paginated(client, f"{account_id}/campaigns", {"fields": "id", "limit": 500})
                adsets = await _get_paginated(client, f"{account_id}/adsets", {"fields": "id", "limit": 500})
                ads = await _get_paginated(client, f"{account_id}/ads", {"fields": "id", "limit": 500})
                total_campaigns += len(campaigns)
                total_adsets += len(adsets)
                total_ads += len(ads)
                print(f"  {account_id}: {len(campaigns)} campaigns, {len(adsets)} ad sets, {len(ads)} ads")

        entity_count = total_campaigns + total_adsets + total_ads
        estimate = entity_count * BACKFILL_WINDOW_DAYS
        print(f"\nTotal entities across all levels: {entity_count}")
        print(f"Estimated max rows this would write (entities x days, actual will be less - zero-activity days are omitted by Meta): {estimate}")
        print("\nDry run only — pass --apply to pull and write this data.")
        return 0

    before = await db.meta_ads_daily_metrics.count_documents({})
    from crm.services.meta_ads_sync_service import sync_daily_meta_ads

    result = await sync_daily_meta_ads(window_days=BACKFILL_WINDOW_DAYS)
    after = await db.meta_ads_daily_metrics.count_documents({})

    print(f"\nSync result: {result}")
    print(f"meta_ads_daily_metrics doc count: {before} -> {after}")
    return 0 if result.get("ok") else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="One-time 90-day Meta Ads backfill")
    ap.add_argument("--apply", action="store_true", help="Pull and write (default is dry-run preview only).")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(apply=args.apply)))


if __name__ == "__main__":
    main()
