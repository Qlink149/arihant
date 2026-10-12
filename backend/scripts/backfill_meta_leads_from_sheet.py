#!/usr/bin/env python3
"""
backfill_meta_leads_from_sheet.py
=================================
Recover Meta Instant Form leads that were rejected (or never reached Clara) while the Zap's
Form ID field was changing, using the raw Meta export ("Arihant - Meta Leads (Raw).xlsx").

Each sheet row is compared with Clara by PHONE (the reliable key - the export stores Meta lead
IDs as numbers, so their last digits are rounded to 0) and classified:

  NEW        phone is not a lead in Clara            -> create it (project from the form name)
  REENQUIRY  lead exists and is OLDER than the form  -> merge + tag Re Enquiry, add the project
             submission (more than --tolerance-min)
  SKIP       the lead was created at/after the form time (it IS this submission, e.g. imported
             from the CSV), or this re-enquiry is already recorded

Rows go through the normal Zapier intake (crm.services.zapier_leads_service.process_zapier_lead),
so assignment, de-duplication, merging and the Re Enquiry tag behave exactly like a live
submission. A row that matches a saved rejected submission (first 15 digits of the Meta lead
ID) reuses that submission's real lead ID, which also closes its "unmapped_form" log entry.

It also LISTS (never changes) leads whose source is WhatsApp although the form was submitted
first, for the source rule to be decided.

Safety: dry run by default; --apply writes a JSON backup of the planned rows first; idempotent
(a row already ingested/merged is skipped on re-run). The default window is the outage:
--since 2026-10-08T15:00 (UTC). NEW rows older than that are listed separately and only
created with --include-old-new.

Usage
-----
  python scripts/backfill_meta_leads_from_sheet.py "<path to xlsx>"            # preview
  python scripts/backfill_meta_leads_from_sheet.py "<path to xlsx>" --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT_DIR / "scripts" / "static_data"
sys.path.insert(0, str(ROOT_DIR))

DEFAULT_SINCE = "2026-10-08T15:00"


# ------------------------------------------------------------------ sheet
def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def lead_id_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v))
    return str(v).strip()


def phone10(v: Any) -> str:
    text = str(int(v)) if isinstance(v, (int, float)) else _s(v)
    return re.sub(r"\D", "", text)[-10:]


def read_sheet(path: str) -> List[Dict[str, Any]]:
    import openpyxl

    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    idx = {h: i for i, h in enumerate(header) if h}
    out: List[Dict[str, Any]] = []
    for r in rows[1:]:
        if not any(c is not None for c in r):
            continue
        g = lambda name: r[idx[name]] if name in idx else None  # noqa: E731
        created = g("Created at")
        if not isinstance(created, datetime):
            continue
        out.append(
            {
                "created_at": created,  # UTC (matches Clara's own timestamps)
                "first_name": _s(g("First Name")),
                "last_name": _s(g("Last Name")),
                "phone": phone10(g("Phone")),
                "email": _s(g("Email")),
                "form_name": _s(g("Project")),
                "lead_id": lead_id_text(g("Lead ID")),
                "form_id": _s(g("Form ID")),
                "site_visit": _s(g("Preferred Site Visit")),
                "campaign_name": _s(g("Campaign Name")),
                "campaign_id": lead_id_text(g("Campaign ID")),
                "adset_name": _s(g("Ad Set Name")),
                "adset_id": lead_id_text(g("Ad Set ID")),
                "ad_name": _s(g("Ad Name")),
                "ad_id": lead_id_text(g("Ad ID")),
            }
        )
    return out


def dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The export repeats some submissions: keep one per (15-digit lead id prefix, phone)."""
    seen, out = set(), []
    for r in sorted(rows, key=lambda x: x["created_at"]):
        key = (r["lead_id"][:15], r["phone"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# ------------------------------------------------------------ classification
def classify(row: Dict[str, Any], lead: Optional[dict], *, tolerance_min: int = 10) -> str:
    if len(row["phone"]) != 10:
        return "SKIP_BAD_PHONE"
    if lead is None:
        return "NEW"
    form_time = row["created_at"]
    lead_created = _naive_utc(lead.get("created_at_dt") or lead.get("created_at"))
    if lead_created is None:
        return "SKIP"
    if lead_created >= form_time - timedelta(minutes=tolerance_min):
        return "SKIP"  # the lead came from this submission (or later)
    already = _naive_utc(lead.get("re_enquired_at"))
    if already and already >= form_time - timedelta(minutes=tolerance_min):
        return "SKIP"  # this re-enquiry is already recorded
    return "REENQUIRY"


def _naive_utc(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    if v.tzinfo is not None:
        v = v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


def whatsapp_first_touch(row: Dict[str, Any], lead: Optional[dict], *, tolerance_min: int = 10) -> bool:
    """Lead's source is WhatsApp although the form was submitted first (or at the same time)."""
    if not lead or "whatsapp" not in _s(lead.get("lead_source")).lower():
        return False
    lead_created = _naive_utc(lead.get("created_at_dt") or lead.get("created_at"))
    return bool(lead_created and row["created_at"] <= lead_created + timedelta(minutes=tolerance_min))


def to_zapier_payload(row: Dict[str, Any], real_lead_id: Optional[str]) -> Dict[str, Any]:
    payload = {
        "Lead ID": real_lead_id or row["lead_id"],
        "Form Name": row["form_name"],
        "First Name": row["first_name"],
        "Last Name": row["last_name"],
        "Email": row["email"],
        "Phone Number": "+91" + row["phone"],
        "Created at": row["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
    }
    optional = {
        "Form ID": row["form_id"],
        "Site Visit Preference": row["site_visit"],
        "Campaign Name": row["campaign_name"],
        "Campaign ID": row["campaign_id"],
        "Ad Set Name": row["adset_name"],
        "Ad Set ID": row["adset_id"],
        "Ad Name": row["ad_name"],
        "Ad ID": row["ad_id"],
    }
    payload.update({k: v for k, v in optional.items() if v})
    return payload


# --------------------------------------------------------------------- run
async def plan(db: Any, zls: Any, rows: List[Dict[str, Any]], *, since: datetime, tolerance_min: int, include_old_new: bool) -> Dict[str, Any]:
    rows = dedupe_rows(rows)
    phones = sorted({r["phone"] for r in rows if len(r["phone"]) == 10})
    leads: Dict[str, dict] = {}
    for i in range(0, len(phones), 500):
        async for l in db.leads.find({"normalized_phone": {"$in": phones[i : i + 500]}}, {"_id": 0}):
            leads[l["normalized_phone"]] = l
    rejected = {
        d["leadgen_id"]: d
        async for d in db.zapier_leads_logs.find({"reason": "unmapped_form"}, {"_id": 0, "leadgen_id": 1})
    }
    by_prefix = {k[:15]: k for k in rejected if k and k.isdigit()}
    logged_ok = {d["leadgen_id"] async for d in db.zapier_leads_logs.find({"success": True}, {"_id": 0, "leadgen_id": 1})}

    items, old_new, wa_first = [], [], []
    for r in rows:
        lead = leads.get(r["phone"])
        kind = classify(r, lead, tolerance_min=tolerance_min)
        in_window = r["created_at"] >= since
        real_id = by_prefix.get(r["lead_id"][:15])
        project = zls.project_from_form_name({"Form Name": r["form_name"]})
        item = {"row": r, "kind": kind, "real_lead_id": real_id, "project": (project or {}).get("id"), "lead_id_in_clara": (lead or {}).get("id")}
        if in_window and whatsapp_first_touch(r, lead, tolerance_min=tolerance_min):
            wa_first.append(item)
        if kind == "NEW" and not in_window:
            old_new.append(item)
            if not include_old_new:
                continue
        elif not in_window:
            continue
        if kind in ("NEW", "REENQUIRY") and (real_id or r["lead_id"]) in logged_ok:
            item["kind"] = "SKIP"  # already ingested earlier
        items.append(item)
    return {"items": items, "old_new": old_new, "wa_first": wa_first, "total_rows": len(rows)}


def summarise(p: Dict[str, Any]) -> None:
    c = Counter(i["kind"] for i in p["items"])
    print(f"Sheet rows (after removing repeats): {p['total_rows']}")
    print(f"In the outage window: {dict(c)}")
    unresolved = [i for i in p["items"] if i["kind"] in ("NEW", "REENQUIRY") and not i["project"]]
    print(f"  rows whose form name gives no project (would be rejected): {len(unresolved)}")
    for i in unresolved:
        print("    ", i["row"]["form_name"], "|", i["row"]["created_at"])
    for kind in ("NEW", "REENQUIRY"):
        print(f"-- {kind}")
        for i in sorted((x for x in p["items"] if x["kind"] == kind), key=lambda x: x["row"]["created_at"]):
            r = i["row"]
            print(f"   {r['created_at']:%d %b %H:%M} UTC | {(r['first_name'] + ' ' + r['last_name']).strip()[:22]:22} | {r['phone']} | {r['form_name'][:34]:34} | -> {i['project']} | rejected-id match: {bool(i['real_lead_id'])}")
    print(f"-- NEW rows OUTSIDE the window (older; not touched unless --include-old-new): {len(p['old_new'])}")
    for i in p["old_new"]:
        r = i["row"]
        print(f"   {r['created_at']:%d %b %Y} | {(r['first_name'] + ' ' + r['last_name']).strip()[:22]:22} | {r['phone']} | {r['form_name'][:34]}")
    print(f"-- Leads with source WhatsApp although the form came first (listed only): {len(p['wa_first'])}")
    for i in p["wa_first"]:
        r = i["row"]
        print(f"   {r['created_at']:%d %b %H:%M} UTC | {(r['first_name'] + ' ' + r['last_name']).strip()[:22]:22} | {r['phone']} | clara lead {i['lead_id_in_clara']}")


async def run(path: str, *, apply: bool, since: str, tolerance_min: int, include_old_new: bool) -> int:
    from dotenv import load_dotenv

    try:  # lead names can hold emoji the Windows console cannot print
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    load_dotenv(ROOT_DIR / ".env")
    from crm.core.state import db
    from crm.services import zapier_leads_service as zls

    print(f"Database: {db.name}")
    p = await plan(db, zls, read_sheet(path), since=datetime.fromisoformat(since), tolerance_min=tolerance_min, include_old_new=include_old_new)
    summarise(p)
    todo = [i for i in p["items"] if i["kind"] in ("NEW", "REENQUIRY") and i["project"]]
    print(f"\nWould process {len(todo)} row(s).")
    if not apply:
        print("Dry run only - pass --apply to back up and process them.")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"meta_sheet_backfill_plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    backup.write_text(json.dumps([{"kind": i["kind"], "payload": to_zapier_payload(i["row"], i["real_lead_id"])} for i in todo], indent=2, default=str), encoding="utf-8")
    print(f"Backup of the planned rows: {backup}")
    ok = bad = 0
    for i in todo:
        res = await zls.process_zapier_lead(to_zapier_payload(i["row"], i["real_lead_id"]), backfill=True)
        if res.get("success"):
            ok += 1
        else:
            bad += 1
            print("  FAILED:", i["row"]["phone"], res)
    print(f"Processed: {ok} ok, {bad} failed")
    return 0 if not bad else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill rejected Meta form leads from the raw Meta export")
    ap.add_argument("xlsx")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--since", default=DEFAULT_SINCE, help="UTC; rows before this are outside the outage window")
    ap.add_argument("--tolerance-min", type=int, default=10)
    ap.add_argument("--include-old-new", action="store_true", help="Also create NEW rows older than --since")
    a = ap.parse_args()
    raise SystemExit(asyncio.run(run(a.xlsx, apply=a.apply, since=a.since, tolerance_min=a.tolerance_min, include_old_new=a.include_old_new)))


if __name__ == "__main__":
    main()
