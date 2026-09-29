"""Backfill lead.escalation from legacy escalation notifications (stage + threshold).

Dry-run by default. Maps pre-T10 notifications that stored sla stage in `stage`
instead of `sla_rule`, including legacy RNR 24h/48h -> rnr/escalate_d7.

Usage (from backend/):
  python scripts/backfill_escalation_queue_legacy.py
  python scripts/backfill_escalation_queue_legacy.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env", override=True)

from crm.core.state import utc_now
from crm.services.escalation_legacy_backfill import (
    legacy_skip_reason,
    resolve_legacy_escalation_pair,
)
from crm.services.escalation_queue import build_raise_state
from crm.utils.helpers import coerce_datetime

EXPECTED_DBS = {"arihant_crm", "arihant_crm_test", "arihant_crm_e2e"}


def _lead_has_pair(lead: dict, sla_rule: str, sla_threshold: str) -> bool:
    esc = lead.get("escalation") if isinstance(lead.get("escalation"), dict) else {}
    if not esc.get("active"):
        return False
    for reason in esc.get("reasons") or []:
        if not isinstance(reason, dict):
            continue
        if reason.get("sla_rule") == sla_rule and reason.get("sla_threshold") == sla_threshold:
            return True
    return False


async def run(*, apply: bool, include_read: bool) -> None:
    from crm.core.state import db

    db_name = os.getenv("DB_NAME") or ""
    print(f"DB_NAME={db_name}")
    if apply and db_name not in EXPECTED_DBS:
        print(f"REFUSING --apply on unexpected DB_NAME={db_name!r}")
        return
    if apply and db_name == "arihant_crm":
        print("WARNING: applying against production database arihant_crm")

    query: dict = {"notification_type": "escalation"}
    if not include_read:
        query["is_read"] = False

    notifs = await db.notifications.find(
        query,
        {
            "_id": 0,
            "lead_id": 1,
            "sla_rule": 1,
            "sla_threshold": 1,
            "stage": 1,
            "title": 1,
            "fired_at_dt": 1,
            "created_at_dt": 1,
            "is_read": 1,
        },
    ).to_list(10000)

    mapped_pairs: dict[str, set[tuple[str, str]]] = defaultdict(set)
    pair_source_count: Counter[tuple[str, str]] = Counter()
    skip_reasons: Counter[str] = Counter()
    missing_leads = 0

    for notif in notifs:
        lead_id = notif.get("lead_id")
        if not lead_id:
            skip_reasons["missing lead_id"] += 1
            continue
        pair = resolve_legacy_escalation_pair(notif)
        if not pair:
            skip_reasons[legacy_skip_reason(notif) or "unmapped"] += 1
            continue
        mapped_pairs[lead_id].add(pair)
        pair_source_count[pair] += 1

    lead_ids = sorted(mapped_pairs.keys())
    already_active = 0
    to_raise: dict[str, list[tuple[str, str]]] = {}
    for lead_id in lead_ids:
        lead = await db.leads.find_one({"id": lead_id}, {"_id": 0, "id": 1, "escalation": 1})
        if not lead:
            missing_leads += 1
            continue
        pending_pairs = [
            pair
            for pair in sorted(mapped_pairs[lead_id])
            if not _lead_has_pair(lead, pair[0], pair[1])
        ]
        if not pending_pairs:
            esc = lead.get("escalation") if isinstance(lead.get("escalation"), dict) else {}
            if esc.get("active"):
                already_active += 1
            continue
        to_raise[lead_id] = pending_pairs

    total_pairs = sum(len(v) for v in to_raise.values())
    print("=== LEGACY ESCALATION QUEUE BACKFILL ===")
    print(f"notifications scanned: {len(notifs)} (include_read={include_read})")
    print(f"mappable notifications: {sum(pair_source_count.values())}")
    print(f"distinct leads with mappable notifications: {len(lead_ids)}")
    print(f"leads to update: {len(to_raise)} ({total_pairs} raise ops)")
    print(f"leads already active with mapped pairs: {already_active}")
    print(f"missing leads: {missing_leads}")
    print("mapped pairs:")
    for pair, cnt in pair_source_count.most_common():
        print(f"  {pair[0]}/{pair[1]}: {cnt}")
    if skip_reasons:
        print("skipped notifications:")
        for reason, cnt in skip_reasons.most_common(10):
            print(f"  {reason}: {cnt}")

    if not apply:
        print("dry-run; pass --apply after confirmation")
        return

    now = utc_now()
    updated = 0
    for lead_id, pairs in to_raise.items():
        lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
        if not lead:
            continue
        for sla_rule, sla_threshold in pairs:
            notif_dt = None
            for notif in notifs:
                if notif.get("lead_id") != lead_id:
                    continue
                resolved = resolve_legacy_escalation_pair(notif)
                if resolved != (sla_rule, sla_threshold):
                    continue
                candidate = coerce_datetime(notif.get("fired_at_dt")) or coerce_datetime(
                    notif.get("created_at_dt")
                )
                if candidate and (notif_dt is None or candidate < notif_dt):
                    notif_dt = candidate
            notif_dt = notif_dt or now
            set_fields, entry = build_raise_state(lead, sla_rule, sla_threshold, notif_dt)
            entry["description"] = (
                f"Escalation backfilled from legacy notification: "
                f"{entry['description'].replace('Escalation raised: ', '')}"
            )
            entry["agent"] = "Legacy backfill"
            entry["actor_name"] = "Legacy backfill"
            await db.leads.update_one(
                {"id": lead_id},
                {"$set": set_fields, "$push": {"context_updates": entry}},
            )
            lead = await db.leads.find_one({"id": lead_id}, {"_id": 0}) or lead
        updated += 1

    active_after = await db.leads.count_documents({"escalation.active": True})
    print(f"updated {updated} leads")
    print(f"escalation.active=true after apply: {active_after}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--include-read",
        action="store_true",
        help="Also consider read escalation notifications (default: unread only)",
    )
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply, include_read=args.include_read))


if __name__ == "__main__":
    main()
