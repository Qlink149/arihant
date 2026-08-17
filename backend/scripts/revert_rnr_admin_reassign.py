#!/usr/bin/env python3
"""
revert_rnr_admin_reassign.py
============================
Restore lead ownership after RNR 48h/15d SLA wrongly (or by old policy) reassigned
to Admin.

Inclusion is event-based only:

  lead_events.event_type = sla_action
  payload.action         = reassign_admin
  payload.reason         in (rnr_escalate_48h, rnr_escalate_15d)

Leads without that event are never touched (New 1h Admin fallback, import parking,
manual assign, transfers).

Safety
------
  - Dry-run by default; --apply required to write.
  - Only sla_paused != True, non-terminal, still assigned to Admin.
  - Skips if a later human assignee_changed / transfer happened after the SLA event.
  - Backs up matched lead documents before writing.
  - Does not go through lead_service (no extra SLA activation).

Usage:
  python backend/scripts/revert_rnr_admin_reassign.py
  python backend/scripts/revert_rnr_admin_reassign.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from pymongo import MongoClient

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from crm.constants.lead_kpi import fw_status_indicates_rnr  # noqa: E402
from crm.constants.lead_status import is_terminal_lead_status  # noqa: E402

RNR_REASSIGN_REASONS = ("rnr_escalate_48h", "rnr_escalate_15d")
RNR_ESCALATE_THRESHOLDS = {"24h", "48h", "15d"}
OPEN_TASK_STATUSES = ("pending", "in_progress")
SKIP_ACTOR_NAMES = frozenset(
    {"sla engine", "system", "system auto-ack", "admin"}
)
ASSIGNED_CREATOR_RE = re.compile(r"Assigned to (.+?) \(creator\)", re.IGNORECASE)
ASSIGNEE_CHANGED_RE = re.compile(r"Assignee changed:.+→\s*(.+)$")
ROUTED_RE = re.compile(r"Routed to ([^(]+)", re.IGNORECASE)


def _as_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def _norm_name(name: Optional[str]) -> str:
    return (name or "").strip().lower()


def _is_skip_actor(name: Optional[str]) -> bool:
    return _norm_name(name) in SKIP_ACTOR_NAMES or not (name or "").strip()


def owner_from_assigned_description(description: str) -> Optional[str]:
    desc = (description or "").strip()
    m = ASSIGNED_CREATOR_RE.search(desc)
    if m:
        return m.group(1).strip()
    m = ASSIGNEE_CHANGED_RE.search(desc)
    if m:
        return m.group(1).strip()
    m = ROUTED_RE.search(desc)
    if m:
        return m.group(1).strip()
    return None


def infer_previous_owner_name(lead: dict, stolen_at: datetime) -> Optional[str]:
    """Best-effort previous owner from timeline before the RNR reassign event."""
    ctx = list(lead.get("context_updates") or [])

    assigned_before = []
    for entry in ctx:
        if (entry.get("type") or "").strip().lower() != "assigned":
            continue
        ts = _as_utc(entry.get("timestamp_dt") or entry.get("timestamp"))
        if ts is None or ts >= stolen_at:
            continue
        assigned_before.append((ts, entry))
    assigned_before.sort(key=lambda x: x[0])
    if assigned_before:
        entry = assigned_before[-1][1]
        parsed = owner_from_assigned_description(entry.get("description") or "")
        if parsed and not _is_skip_actor(parsed):
            return parsed
        actor = (entry.get("actor_name") or entry.get("agent") or "").strip()
        if actor and not _is_skip_actor(actor):
            return actor

    for entry in ctx:
        if (entry.get("type") or "").strip().lower() != "created":
            continue
        actor = (entry.get("actor_name") or entry.get("agent") or "").strip()
        if actor and not _is_skip_actor(actor):
            return actor

    later_actors = []
    for entry in ctx:
        ts = _as_utc(entry.get("timestamp_dt") or entry.get("timestamp"))
        if ts is None or ts >= stolen_at:
            continue
        actor = (entry.get("actor_name") or entry.get("agent") or "").strip()
        if actor and not _is_skip_actor(actor):
            later_actors.append((ts, actor))
    if later_actors:
        later_actors.sort(key=lambda x: x[0])
        return later_actors[-1][1]
    return None


def later_human_reassignment(events: list[dict], stolen_at: datetime) -> bool:
    for ev in events:
        et = (ev.get("event_type") or "").strip()
        if et not in ("assignee_changed", "transfer_created"):
            continue
        ts = _as_utc(ev.get("created_at_dt") or ev.get("created_at"))
        if ts is not None and ts > stolen_at:
            return True
    return False


def _iso_now(now_dt: datetime) -> str:
    return now_dt.isoformat()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry-run preview)")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL", "")
    db_name = os.environ.get("DB_NAME", "")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env", file=sys.stderr)
        sys.exit(1)

    client = MongoClient(mongo_url)
    db = client[db_name]
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"revert_rnr_admin_reassign  [{mode}]  db={db_name}")

    admin = db.users.find_one(
        {"role": {"$regex": r"^\s*admin\s*$", "$options": "i"}},
        {"_id": 0, "id": 1, "full_name": 1, "role": 1},
        sort=[("id", 1)],
    )
    if not admin or not admin.get("id"):
        print("ERROR: no admin user found", file=sys.stderr)
        sys.exit(1)
    admin_id = admin["id"]
    admin_name = (admin.get("full_name") or "Admin").strip()

    users = list(db.users.find({}, {"_id": 0, "id": 1, "full_name": 1, "role": 1}))
    users_by_id = {u["id"]: u for u in users if u.get("id")}
    users_by_name = {_norm_name(u.get("full_name")): u for u in users if u.get("full_name")}

    sla_events = list(
        db.lead_events.find(
            {
                "event_type": "sla_action",
                "payload.action": "reassign_admin",
                "payload.reason": {"$in": list(RNR_REASSIGN_REASONS)},
            },
            {"_id": 0},
        ).sort("created_at_dt", 1)
    )
    print(f"  RNR reassign_admin events : {len(sla_events)}")

    earliest_by_lead: dict[str, dict] = {}
    for ev in sla_events:
        lid = ev.get("lead_id") or ""
        if not lid:
            continue
        existing = earliest_by_lead.get(lid)
        if existing is None:
            earliest_by_lead[lid] = ev
            continue
        ev_ts = _as_utc(ev.get("created_at_dt") or ev.get("created_at"))
        ex_ts = _as_utc(existing.get("created_at_dt") or existing.get("created_at"))
        if ev_ts and (ex_ts is None or ev_ts < ex_ts):
            earliest_by_lead[lid] = ev

    skipped: list[tuple[str, str, str]] = []
    to_fix: list[dict] = []

    for lid, ev in earliest_by_lead.items():
        lead = db.leads.find_one({"id": lid}, {"_id": 0})
        if not lead:
            skipped.append((lid, "missing_lead", ev.get("payload", {}).get("reason", "")))
            continue
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip() or lid
        status = lead.get("lead_status") or ""
        if lead.get("sla_paused") is True:
            skipped.append((lid, f"sla_paused:{name}", status))
            continue
        if is_terminal_lead_status(status):
            skipped.append((lid, f"terminal:{name}", status))
            continue
        still_admin = (lead.get("assigned_user_id") == admin_id) or (
            _norm_name(lead.get("assigned_to") or lead.get("assigned_to_name")) == _norm_name(admin_name)
        )
        if not still_admin:
            skipped.append((lid, f"not_admin_now:{name}", lead.get("assigned_to") or ""))
            continue
        stolen_at = _as_utc(ev.get("created_at_dt") or ev.get("created_at"))
        if stolen_at is None:
            skipped.append((lid, f"no_event_ts:{name}", status))
            continue
        later_events = list(
            db.lead_events.find(
                {
                    "lead_id": lid,
                    "event_type": {"$in": ["assignee_changed", "transfer_created"]},
                },
                {"_id": 0, "event_type": 1, "created_at": 1, "created_at_dt": 1},
            )
        )
        if later_human_reassignment(later_events, stolen_at):
            skipped.append((lid, f"later_human_assign:{name}", status))
            continue
        prev_name = infer_previous_owner_name(lead, stolen_at)
        if not prev_name:
            skipped.append((lid, f"no_previous_owner:{name}", status))
            continue
        owner = users_by_id.get(prev_name) or users_by_name.get(_norm_name(prev_name))
        if not owner or not owner.get("id"):
            skipped.append((lid, f"unresolved_owner:{name}->{prev_name}", status))
            continue
        if (owner.get("role") or "").strip().lower() == "admin" or _is_skip_actor(owner.get("full_name")):
            skipped.append((lid, f"previous_is_admin:{name}", status))
            continue
        to_fix.append(
            {
                "lead": lead,
                "event": ev,
                "stolen_at": stolen_at,
                "owner": owner,
                "reason": (ev.get("payload") or {}).get("reason") or "",
                "is_current_rnr": fw_status_indicates_rnr(status),
            }
        )

    print(f"  unique leads with event   : {len(earliest_by_lead)}")
    print(f"  skipped                   : {len(skipped)}")
    print(f"  to restore                : {len(to_fix)}")

    if skipped:
        print("\n  Skipped:")
        for lid, why, extra in skipped[:40]:
            print(f"    {lid}  {why}  {extra}")
        if len(skipped) > 40:
            print(f"    ... {len(skipped) - 40} more")

    if to_fix:
        print("\n  Restore list:")
        print(f"    {'lead_id':<38} {'status':<18} {'reason':<18} {'restore_to'}")
        for row in to_fix:
            lead = row["lead"]
            print(
                f"    {lead.get('id', ''):<38} "
                f"{(lead.get('lead_status') or ''):<18} "
                f"{row['reason']:<18} "
                f"{row['owner'].get('full_name')}"
            )

    if not to_fix:
        print("\n  Nothing to do.")
        client.close()
        return

    if not args.apply:
        print("\n  DRY-RUN -- no changes written. Re-run with --apply.")
        client.close()
        return

    now_dt = datetime.now(timezone.utc)
    now_iso = _iso_now(now_dt)
    run_id = now_dt.strftime("%Y%m%dT%H%M%SZ")
    backup_dir = SCRIPT_DIR / "static_data"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"pre_rnr_admin_reassign_revert_{run_id}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump([row["lead"] for row in to_fix], f, indent=2, default=str, ensure_ascii=False)
    print(f"\n  [OK] backed up {len(to_fix)} leads -> {backup_path.name}")

    restored = 0
    for row in to_fix:
        lead = row["lead"]
        lid = lead["id"]
        owner = row["owner"]
        owner_name = owner.get("full_name") or ""
        owner_id = owner["id"]
        stolen_at = row["stolen_at"]
        is_rnr = row["is_current_rnr"]

        db.leads.update_one(
            {"id": lid, "assigned_user_id": admin_id},
            {
                "$set": {
                    "assigned_to": owner_name,
                    "assigned_to_name": owner_name,
                    "assigned_user_id": owner_id,
                    "presales_agent": owner_name,
                    "updated_at": now_iso,
                    "updated_at_dt": now_dt,
                },
                "$unset": {"follow_up_delayed": ""},
                "$push": {
                    "context_updates": {
                        "type": "assigned",
                        "timestamp": now_iso,
                        "timestamp_dt": now_dt,
                        "description": f"Assignee restored: {admin_name} → {owner_name} (revert RNR SLA reassign)",
                        "agent": "System",
                        "actor_name": "SLA Repair",
                    }
                },
            },
        )

        open_q = {
            "lead_id": lid,
            "status": {"$in": list(OPEN_TASK_STATUSES)},
        }
        for task in db.tasks.find(open_q, {"_id": 0}):
            sla_rule = (task.get("sla_rule") or "").strip().lower()
            threshold = (task.get("sla_threshold") or "").strip()
            created = _as_utc(task.get("created_at_dt") or task.get("created_at"))
            is_rnr_escalate = sla_rule == "rnr" and threshold in RNR_ESCALATE_THRESHOLDS
            is_rnr_sla = sla_rule == "rnr"

            if is_rnr_sla and not is_rnr:
                db.tasks.update_one(
                    {"id": task["id"]},
                    {
                        "$set": {
                            "status": "cancelled",
                            "updated_at": now_iso,
                            "updated_at_dt": now_dt,
                        }
                    },
                )
                continue
            if is_rnr_escalate and is_rnr:
                continue
            if created is not None and created < stolen_at:
                db.tasks.update_one(
                    {"id": task["id"]},
                    {
                        "$set": {
                            "assigned_to": owner_name,
                            "assigned_user_id": owner_id,
                            "updated_at": now_iso,
                            "updated_at_dt": now_dt,
                        }
                    },
                )
                continue
            if sla_rule and sla_rule != "rnr":
                db.tasks.update_one(
                    {"id": task["id"]},
                    {
                        "$set": {
                            "assigned_to": owner_name,
                            "assigned_user_id": owner_id,
                            "updated_at": now_iso,
                            "updated_at_dt": now_dt,
                        }
                    },
                )

        db.lead_events.insert_one(
            {
                "id": str(uuid.uuid4()),
                "event_type": "sla_action",
                "lead_id": lid,
                "actor_user_id": "",
                "actor_name": "SLA Repair",
                "payload": {
                    "action": "restore_assignment",
                    "reason": "revert_rnr_escalate_reassign",
                    "from": admin_name,
                    "to": owner_name,
                    "to_user_id": owner_id,
                    "original_reason": row["reason"],
                },
                "created_at": now_iso,
                "created_at_dt": now_dt,
            }
        )
        restored += 1

    print(f"  [OK] restored {restored} leads")
    client.close()


if __name__ == "__main__":
    main()
