"""Additive-only backfill of leads.projects / leads.project_ids.

Never rewrites project, project_id, or updated_at.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from pymongo import UpdateOne

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from crm.core.state import db  # noqa: E402
from crm.services.lead_project_fields import (  # noqa: E402
    coalesce_project_ids,
    coalesce_projects,
)

MISSING_ARRAY_QUERY = {
    "$or": [
        {"projects": {"$exists": False}},
        {"projects": None},
        {"projects": []},
    ]
}

UPDATE_GUARD = {
    "$or": [
        {"projects": {"$exists": False}},
        {"projects": None},
        {"projects": []},
    ]
}

BATCH_SIZE = 500


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    mins, secs = divmod(int(seconds), 60)
    if mins < 60:
        return f"{mins}m {secs}s"
    hours, mins = divmod(mins, 60)
    return f"{hours}h {mins}m {secs}s"


def _print_progress(
    *,
    scanned: int,
    total: int,
    skipped_empty: int,
    would_update: int,
    updated: int,
    dry_run: bool,
    started: float,
    final: bool = False,
) -> None:
    elapsed = time.monotonic() - started
    pct = (scanned / total * 100) if total else 100.0
    rate = scanned / elapsed if elapsed > 0 else 0.0
    remaining = total - scanned
    eta = remaining / rate if rate > 0 else 0.0
    mode = "DRY-RUN" if dry_run else "APPLY"
    line = (
        f"[{mode}] {scanned:,}/{total:,} ({pct:5.1f}%) | "
        f"would_update={would_update:,} updated={updated:,} skipped_empty={skipped_empty:,} | "
        f"elapsed={_fmt_duration(elapsed)} eta={_fmt_duration(eta)} rate={rate:,.0f}/s"
    )
    if final:
        print(line, flush=True)
    else:
        print(f"\r{line}", end="", flush=True)


async def migrate(*, dry_run: bool) -> None:
    total = await db.leads.count_documents(MISSING_ARRAY_QUERY)
    mode = "dry-run" if dry_run else "APPLY"
    print(f"=== migrate_lead_projects_to_arrays ({mode}) ===", flush=True)
    print(f"candidates_missing_projects_array={total:,}", flush=True)
    if not dry_run:
        print(f"batch_size={BATCH_SIZE} (only $set projects + project_ids)", flush=True)
    print("", flush=True)

    cursor = db.leads.find(
        MISSING_ARRAY_QUERY,
        {"_id": 0, "id": 1, "project": 1, "project_id": 1, "projects": 1, "project_ids": 1},
    )

    scanned = 0
    skipped_empty = 0
    would_update = 0
    updated = 0
    batch: list[UpdateOne] = []
    started = time.monotonic()

    async for lead in cursor:
        scanned += 1
        names = coalesce_projects(lead)
        if not names:
            skipped_empty += 1
            if scanned % BATCH_SIZE == 0 or scanned == total:
                _print_progress(
                    scanned=scanned,
                    total=total,
                    skipped_empty=skipped_empty,
                    would_update=would_update,
                    updated=updated,
                    dry_run=dry_run,
                    started=started,
                )
            continue

        ids = coalesce_project_ids(lead)
        would_update += 1

        if not dry_run:
            batch.append(
                UpdateOne(
                    {"$and": [{"id": lead["id"]}, UPDATE_GUARD]},
                    {"$set": {"projects": names, "project_ids": ids}},
                )
            )
            if len(batch) >= BATCH_SIZE:
                result = await db.leads.bulk_write(batch, ordered=False)
                updated += result.modified_count
                batch.clear()

        if scanned % BATCH_SIZE == 0 or scanned == total:
            _print_progress(
                scanned=scanned,
                total=total,
                skipped_empty=skipped_empty,
                would_update=would_update,
                updated=updated,
                dry_run=dry_run,
                started=started,
            )

    if batch and not dry_run:
        result = await db.leads.bulk_write(batch, ordered=False)
        updated += result.modified_count
        batch.clear()

    print("", flush=True)
    print("=== done ===", flush=True)
    _print_progress(
        scanned=scanned,
        total=total,
        skipped_empty=skipped_empty,
        would_update=would_update,
        updated=updated,
        dry_run=dry_run,
        started=started,
        final=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill lead projects arrays (additive only)")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    args = parser.parse_args()
    try:
        asyncio.run(migrate(dry_run=not args.apply))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr, flush=True)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
