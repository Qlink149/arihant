"""Read-only audit: escalation queue data vs notifications (prod-safe)."""
from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env", override=True)


async def run() -> None:
    from crm.core.state import db
    from crm.services.escalation_queue import ESCALATION_QUEUE_RULES

    db_name = os.getenv("DB_NAME") or ""
    print(f"DB_NAME={db_name}")
    print("=== ESCALATION QUEUE (read-only) ===")

    total = await db.leads.count_documents({})
    esc_active = await db.leads.count_documents({"escalation.active": True})
    esc_field_any = await db.leads.count_documents(
        {"escalation": {"$exists": True, "$ne": None}}
    )

    notif_esc_all = await db.notifications.count_documents(
        {"notification_type": "escalation"}
    )
    notif_esc_unread = await db.notifications.count_documents(
        {"notification_type": "escalation", "is_read": False}
    )

    pairs = list(ESCALATION_QUEUE_RULES)
    or_clause = [{"sla_rule": r, "sla_threshold": t} for r, t in pairs]
    whitelist_q = {
        "notification_type": "escalation",
        "is_read": False,
        "$or": or_clause,
    }
    whitelist_notifs = await db.notifications.count_documents(whitelist_q)
    whitelist_leads = [
        x for x in await db.notifications.distinct("lead_id", whitelist_q) if x
    ]

    stacked = await db.leads.count_documents(
        {
            "escalation.active": True,
            "vip": True,
            "re_enquiry": True,
            "nudge_pending": True,
        }
    )
    esc_vip = await db.leads.count_documents({"escalation.active": True, "vip": True})
    esc_nudge = await db.leads.count_documents(
        {"escalation.active": True, "nudge_pending": True}
    )
    esc_re = await db.leads.count_documents(
        {"escalation.active": True, "re_enquiry": True}
    )
    meta_esc = await db.leads.count_documents(
        {"escalation.active": True, "meta_qualified": True}
    )

    print(f"total leads: {total}")
    print(f"leads with escalation.active=true: {esc_active}")
    print(f"leads with any escalation field: {esc_field_any}")
    print(f"escalation notifications (all): {notif_esc_all}")
    print(f"escalation notifications (unread): {notif_esc_unread}")
    print(f"unread whitelist-pair notifications: {whitelist_notifs}")
    print(f"distinct leads from whitelist unread notifs: {len(whitelist_leads)}")
    print("--- filter intersections (escalated +) ---")
    print(f"  + vip: {esc_vip}")
    print(f"  + nudge_pending: {esc_nudge}")
    print(f"  + re_enquiry: {esc_re}")
    print(f"  + meta_qualified: {meta_esc}")
    print(f"  + vip + re_enquiry + nudge (screenshot stack): {stacked}")

    if esc_active:
        sample = await db.leads.find(
            {"escalation.active": True},
            {
                "_id": 0,
                "id": 1,
                "name": 1,
                "lead_status": 1,
                "escalation": 1,
                "vip": 1,
                "re_enquiry": 1,
                "nudge_pending": 1,
            },
        ).limit(5).to_list(5)
        print("sample escalated leads:")
        for s in sample:
            esc = s.get("escalation") or {}
            reasons = esc.get("reasons") or []
            print(
                f"  id={s.get('id')} status={s.get('lead_status')} "
                f"vip={s.get('vip')} reasons={len(reasons)}"
            )
    elif whitelist_leads:
        print("sample lead_ids from unread whitelist notifs (lead.escalation not set):")
        for lid in whitelist_leads[:5]:
            lead = await db.leads.find_one(
                {"id": lid},
                {"_id": 0, "id": 1, "name": 1, "lead_status": 1, "escalation": 1},
            )
            if lead:
                active = (lead.get("escalation") or {}).get("active")
                print(
                    f"  id={lead.get('id')} status={lead.get('lead_status')} "
                    f"escalation.active={active}"
                )

    notifs = await db.notifications.find(
        whitelist_q, {"_id": 0, "sla_rule": 1, "sla_threshold": 1}
    ).to_list(5000)
    c = Counter((n.get("sla_rule"), n.get("sla_threshold")) for n in notifs)
    if c:
        print("whitelist unread notifs by rule:")
        for pair, cnt in c.most_common(15):
            print(f"  {pair[0]}/{pair[1]}: {cnt}")

    print("DONE read-only")


if __name__ == "__main__":
    asyncio.run(run())
