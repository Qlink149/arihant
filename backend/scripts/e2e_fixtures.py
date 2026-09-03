"""
Insert E2E fixtures directly into allowlisted Mongo (notifications, timeline notes).

Usage:
  python scripts/e2e_fixtures.py insert-notification --run-id X --lead-id Y --recipient-id Z
  python scripts/e2e_fixtures.py patch-lead --lead-id Y --run-id X --json '{"projects":["Vivriti","Mélange"]}'
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.e2e_cleanup import assert_safe_e2e_target, load_e2e_env  # noqa: E402


def _now():
    dt = datetime.now(timezone.utc)
    return dt, dt.isoformat().replace("+00:00", "Z")


def cmd_insert_notification(db, args: argparse.Namespace) -> None:
    now_dt, now_iso = _now()
    doc = {
        "id": str(uuid.uuid4()),
        "recipient_user_id": args.recipient_id,
        "recipient_name": args.recipient_name or "E2E",
        "title": args.title or "E2E notification",
        "message": args.message or "E2E test notification",
        "type": args.notification_type or "e2e_test",
        "notification_type": args.notification_type or "e2e_test",
        "lead_id": args.lead_id,
        "lead_name": args.lead_name or "E2E Lead",
        "is_read": bool(getattr(args, "is_read", False)),
        "fired_at_dt": now_dt,
        "severity": "medium",
        "urgency": "info",
        "created_at": now_iso,
        "created_at_dt": now_dt,
        "e2e_run_id": args.run_id,
    }
    db.notifications.insert_one(doc)
    print(json.dumps({"ok": True, "id": doc["id"]}))


def _coerce_patch_dates(patch: dict) -> dict:
    from datetime import datetime

    out = dict(patch)
    for key, val in list(out.items()):
        if not isinstance(val, str):
            continue
        if not (key.endswith("_at") or key.endswith("_dt")):
            continue
        text = val.strip()
        if not text:
            continue
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            continue
        out[key] = parsed
    return out


def cmd_patch_lead(db, args: argparse.Namespace) -> None:
    patch = _coerce_patch_dates(json.loads(args.json_body))
    patch["e2e_run_id"] = args.run_id
    if "meta" in patch and isinstance(patch["meta"], dict):
        patch["meta"]["e2e_run_id"] = args.run_id
    else:
        patch.setdefault("meta", {})["e2e_run_id"] = args.run_id
    db.leads.update_one({"id": args.lead_id}, {"$set": patch})
    print(json.dumps({"ok": True, "lead_id": args.lead_id}))


def cmd_push_note(db, args: argparse.Namespace) -> None:
    now_dt, now_iso = _now()
    entry = {
        "type": "note",
        "timestamp": now_iso,
        "timestamp_dt": now_dt,
        "description": args.text,
        "agent": "E2E",
        "note": args.text,
    }
    db.leads.update_one(
        {"id": args.lead_id},
        {
            "$push": {"context_updates": entry},
            "$set": {"e2e_run_id": args.run_id, "meta.e2e_run_id": args.run_id},
        },
    )
    print(json.dumps({"ok": True}))


def cmd_push_timeline(db, args: argparse.Namespace) -> None:
    now_dt, now_iso = _now()
    entry = {
        "type": args.entry_type,
        "timestamp": now_iso,
        "timestamp_dt": now_dt,
        "description": args.description,
        "agent": args.agent or "Zapier",
    }
    if args.project_name:
        entry["project_name"] = args.project_name
    db.leads.update_one(
        {"id": args.lead_id},
        {
            "$push": {"context_updates": entry},
            "$set": {"e2e_run_id": args.run_id, "meta.e2e_run_id": args.run_id},
        },
    )
    print(json.dumps({"ok": True}))


def main() -> None:
    load_e2e_env()
    meta = assert_safe_e2e_target()
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("insert-notification")
    p1.add_argument("--run-id", required=True)
    p1.add_argument("--lead-id", required=True)
    p1.add_argument("--recipient-id", required=True)
    p1.add_argument("--recipient-name", default="Admin")
    p1.add_argument("--lead-name", default="E2E Lead")
    p1.add_argument("--title", default="E2E notification")
    p1.add_argument("--message", default="Click me")
    p1.add_argument("--notification-type", default="e2e_test")
    p1.add_argument("--is-read", action="store_true")

    p2 = sub.add_parser("patch-lead")
    p2.add_argument("--run-id", required=True)
    p2.add_argument("--lead-id", required=True)
    p2.add_argument("--json", dest="json_body", required=True)

    p3 = sub.add_parser("push-note")
    p3.add_argument("--run-id", required=True)
    p3.add_argument("--lead-id", required=True)
    p3.add_argument("--text", required=True)

    p4 = sub.add_parser("push-timeline")
    p4.add_argument("--run-id", required=True)
    p4.add_argument("--lead-id", required=True)
    p4.add_argument("--type", dest="entry_type", default="created")
    p4.add_argument("--description", required=True)
    p4.add_argument("--agent", default="Zapier")
    p4.add_argument("--project-name", default="")

    args = parser.parse_args()
    client = MongoClient(meta["MONGO_URL"])
    db = client[meta["DB_NAME"]]
    try:
        if args.cmd == "insert-notification":
            cmd_insert_notification(db, args)
        elif args.cmd == "patch-lead":
            cmd_patch_lead(db, args)
        elif args.cmd == "push-note":
            cmd_push_note(db, args)
        elif args.cmd == "push-timeline":
            cmd_push_timeline(db, args)
    finally:
        client.close()


if __name__ == "__main__":
    main()
