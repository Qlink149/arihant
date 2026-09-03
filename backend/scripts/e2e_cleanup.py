"""
E2E safety + cascade cleanup for disposable DB only.

Refuse production DB_NAME / ENVIRONMENT / known live API hosts.
Deletes only leads tagged with e2e_run_id (and related docs).

Usage (from backend/):
  python scripts/e2e_cleanup.py --run-id <uuid> [--dry-run]
  python scripts/e2e_cleanup.py --run-id <uuid> --phone 919876543210

Requires MONGO_URL + DB_NAME pointing at an allowlisted disposable database.
Prefer: set E2E_ENV_FILE=../backend/.env.e2e or load .env.e2e explicitly.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pymongo import MongoClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]

ALLOWED_DB_NAMES = frozenset({"arihant_crm_e2e", "arihant_crm_test"})
ALLOWED_ENVIRONMENTS = frozenset({"development", "test", "e2e"})
BLOCKED_DB_NAMES = frozenset({"arihant_crm"})
BLOCKED_API_HOST_FRAGMENTS = (
    "arihant-api.claraai.tech",
    "crm-sales-next.preview.emergentagent.com",
)


def load_e2e_env() -> None:
    override = (os.environ.get("E2E_ENV_FILE") or "").strip()
    if override:
        load_dotenv(override, override=True)
        return
    e2e_path = BACKEND_ROOT / ".env.e2e"
    if e2e_path.is_file():
        load_dotenv(e2e_path, override=True)
        return
    load_dotenv(BACKEND_ROOT / ".env", override=False)


def assert_safe_e2e_target(*, api_base: str | None = None) -> dict[str, str]:
    """Fail closed if this process would touch live CRM data."""
    env = (os.environ.get("ENVIRONMENT") or "").strip().lower()
    db_name = (os.environ.get("DB_NAME") or "").strip()
    mongo_url = (os.environ.get("MONGO_URL") or "").strip()

    if not mongo_url or not db_name:
        raise SystemExit("E2E refuse: MONGO_URL and DB_NAME must be set (use backend/.env.e2e)")

    if env == "production" or env not in ALLOWED_ENVIRONMENTS:
        raise SystemExit(
            f"E2E refuse: ENVIRONMENT={env!r} must be one of {sorted(ALLOWED_ENVIRONMENTS)}"
        )

    if db_name in BLOCKED_DB_NAMES or db_name not in ALLOWED_DB_NAMES:
        raise SystemExit(
            f"E2E refuse: DB_NAME={db_name!r} not allowlisted "
            f"(allowed: {sorted(ALLOWED_DB_NAMES)}; blocked: {sorted(BLOCKED_DB_NAMES)})"
        )

    base = (api_base or os.environ.get("E2E_API_URL") or os.environ.get("VITE_BACKEND_URL") or "").strip().lower()
    for frag in BLOCKED_API_HOST_FRAGMENTS:
        if frag in base:
            raise SystemExit(f"E2E refuse: API base points at live host containing {frag!r}")

    if "atlas" in mongo_url.lower() and "e2e" not in db_name.lower():
        raise SystemExit("E2E refuse: Atlas URL with non-e2e DB_NAME")

    return {"ENVIRONMENT": env, "DB_NAME": db_name, "MONGO_URL": mongo_url}


def _normalize_phone(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) >= 10:
        return digits[-10:]
    return digits


def _delete_lead_cascade(db, lead: dict) -> dict[str, int]:
    lead_id = lead["id"]
    phone = lead.get("phone") or lead.get("normalized_phone") or ""
    norm = _normalize_phone(str(phone))

    task_ids = [t["id"] for t in db.tasks.find({"lead_id": lead_id}, {"_id": 0, "id": 1}) if t.get("id")]
    notif_clauses: list[dict] = [{"lead_id": lead_id}]
    if task_ids:
        notif_clauses.append({"task_id": {"$in": task_ids}})
    notif_filter = {"$or": notif_clauses}

    counts = {
        "tasks": db.tasks.count_documents({"lead_id": lead_id}),
        "notifications": db.notifications.count_documents(notif_filter),
        "lead_events": db.lead_events.count_documents({"lead_id": lead_id}) if "lead_events" in db.list_collection_names() else 0,
        "reminders": db.reminders.count_documents({"lead_id": lead_id}) if "reminders" in db.list_collection_names() else 0,
        "lead_transfers": db.lead_transfers.count_documents({"lead_id": lead_id}),
        "site_visit_events": (
            db.site_visit_events.count_documents({"lead_id": lead_id})
            if "site_visit_events" in db.list_collection_names()
            else 0
        ),
        "whatsapp_messages": 0,
        "leads": 1,
    }

    wa_filter = None
    if norm:
        wa_filter = {
            "$or": [
                {"source": {"$regex": norm}},
                {"destination": {"$regex": norm}},
                {"normalized_phone": norm},
                {"phone": {"$regex": norm}},
            ]
        }
        counts["whatsapp_messages"] = db.whatsapp_messages.count_documents(wa_filter)

    if counts["tasks"]:
        db.tasks.delete_many({"lead_id": lead_id})
    if counts["notifications"]:
        db.notifications.delete_many(notif_filter)
    if counts["lead_events"]:
        db.lead_events.delete_many({"lead_id": lead_id})
    if counts["reminders"]:
        db.reminders.delete_many({"lead_id": lead_id})
    if counts["lead_transfers"]:
        db.lead_transfers.delete_many({"lead_id": lead_id})
    if counts["site_visit_events"]:
        db.site_visit_events.delete_many({"lead_id": lead_id})
    if wa_filter and counts["whatsapp_messages"]:
        db.whatsapp_messages.delete_many(wa_filter)
    db.leads.delete_one({"id": lead_id})
    return counts


def cleanup_run(
    db,
    *,
    run_id: str,
    phones: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    query: dict[str, Any] = {
        "$or": [
            {"e2e_run_id": run_id},
            {"meta.e2e_run_id": run_id},
            {"first_name": {"$regex": f"^E2E_{run_id[:8]}"}},
        ]
    }
    leads = list(db.leads.find(query, {"_id": 0}))
    seen = {l["id"] for l in leads if l.get("id")}

    for phone in phones or []:
        norm = _normalize_phone(phone)
        if not norm:
            continue
        for lead in db.leads.find(
            {
                "$and": [
                    {
                        "$or": [
                            {"normalized_phone": norm},
                            {"phone": {"$regex": norm}},
                        ]
                    },
                    {
                        "$or": [
                            {"e2e_run_id": run_id},
                            {"meta.e2e_run_id": run_id},
                            {"first_name": {"$regex": "^E2E_"}},
                        ]
                    },
                ],
            },
            {"_id": 0},
        ):
            if lead.get("id") and lead["id"] not in seen:
                leads.append(lead)
                seen.add(lead["id"])

    report = {"run_id": run_id, "matched": len(leads), "deleted": [], "dry_run": dry_run}
    for lead in leads:
        fn = lead.get("first_name") or ""
        if not (lead.get("e2e_run_id") == run_id or (lead.get("meta") or {}).get("e2e_run_id") == run_id or str(fn).startswith("E2E_")):
            continue
        if dry_run:
            report["deleted"].append({"id": lead.get("id"), "first_name": fn, "dry_run": True})
            continue
        counts = _delete_lead_cascade(db, lead)
        report["deleted"].append({"id": lead.get("id"), "first_name": fn, **counts})

    # Orphan notifications for this run marker
    if not dry_run:
        db.notifications.delete_many({"e2e_run_id": run_id})
        db.whatsapp_messages.delete_many({"e2e_run_id": run_id})

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Cascade-delete E2E-tagged leads only")
    parser.add_argument("--run-id", required=True, help="e2e_run_id UUID from the Playwright run")
    parser.add_argument("--phone", action="append", default=[], help="Extra phone digits to match (E2E_ leads only)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_e2e_env()
    meta = assert_safe_e2e_target()
    client = MongoClient(meta["MONGO_URL"])
    db = client[meta["DB_NAME"]]
    try:
        report = cleanup_run(db, run_id=args.run_id, phones=args.phone, dry_run=args.dry_run)
    finally:
        client.close()

    print(f"DB={meta['DB_NAME']} env={meta['ENVIRONMENT']} run_id={args.run_id}")
    print(f"matched={report['matched']} deleted={len(report['deleted'])} dry_run={args.dry_run}")
    for row in report["deleted"]:
        print(f"  - {row}")


if __name__ == "__main__":
    main()
