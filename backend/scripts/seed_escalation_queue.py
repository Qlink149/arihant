"""Dry-run (default) count of unread whitelist escalation notifications.

Wait for confirmation before --apply. Never writes production unless --apply
and DB_NAME is an expected database.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crm.services.escalation_queue import ESCALATION_QUEUE_RULES, build_raise_state
from crm.core.state import utc_now

EXPECTED_DBS = {"arihant_crm", "arihant_crm_test", "arihant_crm_e2e"}


async def run(*, apply: bool) -> None:
    from crm.core.state import db

    db_name = os.getenv("DB_NAME") or ""
    if apply and db_name not in EXPECTED_DBS:
        print(f"REFUSING --apply on unexpected DB_NAME={db_name!r}")
        return
    pairs = list(ESCALATION_QUEUE_RULES)
    or_clause = [{"sla_rule": r, "sla_threshold": t} for r, t in pairs]
    q = {
        "is_read": {"$ne": True},
        "notification_type": "escalation",
        "$or": or_clause,
    }
    notifs = await db.notifications.find(q, {"_id": 0, "lead_id": 1, "sla_rule": 1, "sla_threshold": 1}).to_list(5000)
    lead_ids = sorted({n.get("lead_id") for n in notifs if n.get("lead_id")})
    print(f"unread whitelist escalations: {len(notifs)} notifications / {len(lead_ids)} leads")
    if not apply:
        print("dry-run; pass --apply after confirmation")
        return
    now = utc_now()
    seeded = 0
    for lid in lead_ids:
        lead = await db.leads.find_one({"id": lid}, {"_id": 0})
        if not lead:
            continue
        reasons_pairs = {
            (n.get("sla_rule"), n.get("sla_threshold"))
            for n in notifs
            if n.get("lead_id") == lid
        }
        for sla_rule, sla_threshold in reasons_pairs:
            if (sla_rule, sla_threshold) not in ESCALATION_QUEUE_RULES:
                continue
            set_fields, entry = build_raise_state(lead, sla_rule, sla_threshold, now)
            await db.leads.update_one(
                {"id": lid},
                {"$set": set_fields, "$push": {"context_updates": entry}},
            )
            lead = await db.leads.find_one({"id": lid}, {"_id": 0}) or lead
        seeded += 1
    print(f"seeded {seeded} leads")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    main()
