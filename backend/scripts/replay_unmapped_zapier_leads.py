#!/usr/bin/env python3
"""
replay_unmapped_zapier_leads.py
===============================
Meta form submissions that could not be matched to a project are rejected and their
payload is saved on the `zapier_leads_logs` row (`rejected_payload`) so nothing is
lost. After the form is added to the project map (META_LEAD_FORM_PROJECT_MAP) - or
the Zap starts sending a recognisable name - this replays them through the normal
intake, so they become leads (or are merged into the existing lead and tagged Re
Enquiry, exactly as a live submission would be).

Dry run by default: lists each saved submission and whether it can be matched now.
--apply replays only the ones that can; the rest stay saved for later. Idempotent:
a replayed submission's log row becomes "ingested" and is not replayed again.

Submissions rejected BEFORE payloads were saved have no payload here; replay those
from Zapier's task history (the log row still has their leadgen_id).

Usage
-----
  python scripts/replay_unmapped_zapier_leads.py            # preview
  python scripts/replay_unmapped_zapier_leads.py --apply    # replay what can be matched
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))


async def plan_replay(db: Any, zls: Any) -> List[Dict[str, Any]]:
    rows = await db.zapier_leads_logs.find(
        {"reason": "unmapped_form", "rejected_payload": {"$exists": True}}, {"_id": 0}
    ).to_list(None)
    plan = []
    for r in rows:
        fields = r.get("rejected_payload") or {}
        form_id = r.get("form_id")
        project = zls.project_from_form_id(form_id) or zls.project_from_names(fields, form_id)
        plan.append({"leadgen_id": r.get("leadgen_id"), "form_id": form_id, "project": (project or {}).get("id"), "payload": fields})
    return plan


async def replay(zls: Any, plan: List[Dict[str, Any]]) -> Dict[str, int]:
    done = failed = 0
    for item in plan:
        if not item["project"]:
            continue
        result = await zls.process_zapier_lead(item["payload"])
        if result.get("success"):
            done += 1
        else:
            failed += 1
    return {"replayed": done, "failed": failed, "still_unmatched": sum(1 for i in plan if not i["project"])}


async def run(*, apply: bool) -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT_DIR / ".env")
    from crm.core.state import db
    from crm.services import zapier_leads_service as zls

    print(f"Database: {db.name}")
    plan = await plan_replay(db, zls)
    print(f"Saved rejected submissions: {len(plan)}")
    for i in plan:
        print(f"  {i['leadgen_id']} | form {i['form_id']!r} -> {i['project'] or 'STILL UNMATCHED'}")
    if not apply:
        print("Dry run only - pass --apply to replay the ones that can be matched.")
        return 0
    res = await replay(zls, plan)
    print(res)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay saved, previously unmapped Zapier Meta submissions")
    ap.add_argument("--apply", action="store_true", help="Replay (default is preview).")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(apply=args.apply)))


if __name__ == "__main__":
    main()
