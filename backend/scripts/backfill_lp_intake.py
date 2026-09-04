#!/usr/bin/env python3
"""
backfill_lp_intake.py
==================
Replay landing-page form submissions through the normal ``ingest_lead`` path
(soft-dedupe, timeline, Re-engaged). Dry-run by default.

Built-in: Submission #342 (Aiswarya Naveen / Reserve 16) from client screenshot.

Usage (from backend/):
  # Dry-run against whatever DB .env points at (prints plan only)
  python scripts/backfill_lp_intake.py

  # Apply on e2e only
  E2E_ENV_FILE=.env.e2e python scripts/backfill_lp_intake.py --env-file .env.e2e --apply

  # Apply on production (requires both flags)
  python scripts/backfill_lp_intake.py --apply --allow-prod --submission-342

  # CSV/JSON export from LP CMS
  python scripts/backfill_lp_intake.py --file failed.csv --apply --allow-prod
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Submission #342 — client screenshot (FB LP / Instagram_Feed)
SUBMISSION_342: Dict[str, Any] = {
    "first_name": "Aiswarya",
    "last_name": "Naveen",
    "email": "aiswaryaanaveen@gmail.com",
    "phone": "+918072565736",
    "budget": "45 - 60 Lacs.",
    "consent": True,
    "source": "fb",
    "meta": {
        "utm_source": "fb",
        "utm_medium": "Instagram_Feed",
        "utm_campaign": "R-16 - Leads",
        "utm_content": "Private slice of paradise",
        "lp_submission_id": "342",
        "project_label": "ECR - Reserve16",
        "via": "backfill_lp_intake",
    },
}


def _load_env(env_file: Optional[str]) -> None:
    if env_file:
        path = Path(env_file)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        load_dotenv(path, override=True)
    else:
        load_dotenv(BACKEND_DIR / ".env")


def _rows_from_file(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        raise SystemExit("JSON file must be an object or array of objects")
    # CSV
    reader = csv.DictReader(text.splitlines())
    return [dict(row) for row in reader]


def _coerce_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    # CSV often stores consent as string
    if "consent" in out and not isinstance(out["consent"], bool):
        from crm.services.lead_intake_service import coerce_consent

        c = coerce_consent(out["consent"])
        if c is not None:
            out["consent"] = c
    if "consent" not in out:
        out["consent"] = True
    return out


async def _resolve_reserve16_api_key() -> dict:
    from crm.core.state import db

    doc = await db.api_keys.find_one(
        {"project_id": "reserve-16", "is_active": True},
        {"_id": 0},
    )
    if not doc:
        raise SystemExit("No active api_keys row for project_id=reserve-16")
    # ingest_lead only needs id/project_*; plaintext not required
    return {
        "id": doc["id"],
        "project_name": doc.get("project_name") or "Reserve 16",
        "project_id": doc.get("project_id") or "reserve-16",
        "rate_limit_per_min": int(doc.get("rate_limit_per_min") or 120),
    }


async def _preview(body: Dict[str, Any]) -> None:
    from crm.core.state import db
    from crm.services.lead_intake_service import normalize_intake_body, validate_intake_payload
    from crm.utils.helpers import normalize_phone

    normalized_body = normalize_intake_body(body)
    data = validate_intake_payload(normalized_body)
    phone_norm = normalize_phone(data["phone"]) if data.get("phone") else None
    existing = None
    if phone_norm:
        existing = await db.leads.find_one({"normalized_phone": phone_norm}, {"_id": 0})
    if not existing and data.get("email"):
        existing = await db.leads.find_one({"email": data["email"]}, {"_id": 0})

    print("--- row ---")
    print(
        f"  incoming: {data.get('first_name')} {data.get('last_name')} | "
        f"{data.get('email')} | phone={data.get('phone')} | budget={data.get('budget')}"
    )
    if existing:
        print(
            f"  match: id={existing.get('id')} name={existing.get('first_name')} "
            f"{existing.get('last_name')} status={existing.get('lead_status')} "
            f"email={existing.get('email')} submission_count={existing.get('submission_count')}"
        )
        print(
            "  planned: soft-dedupe via ingest_lead -> update name/email/budget/meta, "
            "timeline resubmission"
            + (
                ", Unqualified/Closed Lost/Gone Cold -> Re-engaged"
                if str(existing.get("lead_status") or "").strip().lower()
                in {"unqualified", "closed lost", "gone cold"}
                else ""
            )
        )
    else:
        print("  match: none → would CREATE new lead")


async def _apply_row(body: Dict[str, Any], api_key: dict) -> None:
    from crm.services.lead_intake_service import ingest_lead

    result, status = await ingest_lead(body=body, api_key=api_key, ip="backfill-script")
    print(f"  APPLY status={status} result={result}")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", default=None, help="Env file relative to backend/ (default: .env)")
    ap.add_argument("--apply", action="store_true", help="Write via ingest_lead (default: dry-run)")
    ap.add_argument(
        "--allow-prod",
        action="store_true",
        help="Required together with --apply when DB_NAME=arihant_crm",
    )
    ap.add_argument(
        "--no-submission-342",
        action="store_true",
        help="Skip built-in Submission #342 row",
    )
    ap.add_argument("--file", type=str, default=None, help="CSV or JSON of LP submissions")
    args = ap.parse_args()

    _load_env(args.env_file)
    db_name = os.environ.get("DB_NAME", "")
    mongo_url = os.environ.get("MONGO_URL", "")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME not set", file=sys.stderr)
        sys.exit(1)

    if args.apply and db_name == "arihant_crm" and not args.allow_prod:
        print(
            "REFUSE: DB_NAME=arihant_crm requires --allow-prod with --apply",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.apply and db_name not in ("arihant_crm", "arihant_crm_e2e", "arihant_crm_test"):
        print(f"REFUSE: unexpected DB_NAME={db_name!r}", file=sys.stderr)
        sys.exit(1)

    rows: List[Dict[str, Any]] = []
    if not args.no_submission_342:
        rows.append(dict(SUBMISSION_342))
    if args.file:
        rows.extend(_rows_from_file(Path(args.file)))

    if not rows:
        print("No rows to process", file=sys.stderr)
        sys.exit(1)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print("=" * 72)
    print(f"  backfill_lp_intake.py  [{mode}]  DB={db_name}")
    print(f"  rows={len(rows)}")
    print("=" * 72)

    api_key = await _resolve_reserve16_api_key()
    print(f"  api_key_id={api_key['id']} project={api_key['project_name']}")

    for raw in rows:
        body = _coerce_row(raw)
        await _preview(body)
        if args.apply:
            await _apply_row(body, api_key)

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
