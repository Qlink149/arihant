#!/usr/bin/env python3
"""
restore_wati_contact_names.py
=============================
Repair WATI contacts whose name was overwritten with the sending agent's / system
name by the old `_wati_send` (it posted addContact with current_user.full_name).

Source of truth: the LIVE WATI contact list vs the CRM lead. A contact is only
touched when ALL of these hold:
  1. it was created/tagged by the CRM (customParams source == ArihantCRM)
  2. its current WATI name is a known sender name (a CRM user, "Admin",
     "System Auto-Ack", "Arihant Spaces") OR just the first token of the lead's name
  3. exactly one CRM lead matches the number and has a real name
  4. if WATI still holds the name the CRM template sent (attribute "1") and it is a
     plain Latin name unrelated to the lead's name, the pairing is suspicious and
     is skipped for manual review (reason attr1_conflict)
  5. for non-+91 numbers the lead's stored phone must equal the WhatsApp number
     exactly (the CRM only matches on the last 10 digits, which can collide across
     countries); otherwise it needs --include-international after manual review
Anything else (hand-edited names, placeholders, unknown contacts) is left alone and
reported as skipped.

Safety:
  * Dry-run by default. --apply is required to write.
  * Every change is logged to a JSON backup (old name -> new name) for rollback.
  * Each write is re-read from WATI and verified; the run ABORTS on the first
    write that did not stick.
  * Throttled (--delay) and retried on 429/5xx.
  * --only-phone / --limit for a small canary before the full run.

Usage (from backend/):
  python scripts/restore_wati_contact_names.py                       # dry-run, writes report csv
  python scripts/restore_wati_contact_names.py --apply --only-phone 447584020324
  python scripts/restore_wati_contact_names.py --apply --limit 10
  python scripts/restore_wati_contact_names.py --apply
  python scripts/restore_wati_contact_names.py --rollback backups/wati_names_<ts>.json --apply
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

SYSTEM_NAMES = {"admin", "system auto-ack", "arihant spaces"}
PLACEHOLDER_RE = re.compile(r"^whatsapp\s*\d{2,}$", re.I)
PAGE_SIZE = 100


def _n(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _crm_name(lead: dict) -> str:
    first = (lead.get("first_name") or "").strip()
    last = (lead.get("last_name") or "").strip()
    return f"{first} {last}".strip() or (lead.get("name") or "").strip()


def _is_crm_tagged(contact: dict) -> bool:
    return any(
        p.get("name") == "source" and p.get("value") == "ArihantCRM"
        for p in (contact.get("customParams") or [])
    )


def _attr1_conflicts(contact: dict, crm: str) -> bool:
    """True when template attr "1" is a plain Latin name that is unrelated to the CRM name."""
    cp = {p.get("name"): p.get("value") for p in (contact.get("customParams") or [])}
    a1 = _n(cp.get("1"))
    if not a1 or not a1.isascii():
        return False  # absent, or non-Latin transliteration: cannot compare, don't block
    c = _n(crm)
    return not (a1 in c or c in a1 or a1 == (c.split(" ")[0] if c else ""))


def classify(contact: dict, lead: dict | None, known_senders: set[str], include_intl: bool) -> tuple[str, str]:
    """Return (action, reason). action is 'fix' or 'skip'."""
    phone = str(contact.get("wAid") or contact.get("phone") or "")
    wati_name = (contact.get("fullName") or contact.get("firstName") or "").strip()
    if not _is_crm_tagged(contact):
        return "skip", "not_tagged_by_crm"
    if lead is None:
        return "skip", "no_matching_lead"
    crm = _crm_name(lead)
    if not crm or PLACEHOLDER_RE.match(crm):
        return "skip", "crm_name_missing_or_placeholder"
    if _n(wati_name) == _n(crm):
        return "skip", "already_correct"
    if _attr1_conflicts(contact, crm):
        return "skip", "attr1_conflict"
    if not phone.startswith("91") and not include_intl:
        if re.sub(r"\D", "", lead.get("phone") or "") != phone:
            return "skip", "international_needs_review"
    if _n(wati_name) in known_senders:
        return "fix", "sender_name_overwrote_customer"
    first_tok = _n(crm).split(" ")[0] if crm else ""
    if _n(wati_name) == first_tok and " " in crm.strip():
        return "fix", "first_name_only"
    return "skip", "different_name_leave_alone"


async def fetch_all_contacts(client: httpx.AsyncClient, ep: str, headers: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    page = 1
    while True:
        r = await client.get(
            f"{ep}/api/v1/getContacts",
            params={"pageSize": PAGE_SIZE, "pageNumber": page},
            headers=headers,
            timeout=60,
        )
        r.raise_for_status()
        rows = r.json().get("contact_list") or []
        for c in rows:
            out[str(c.get("wAid") or c.get("phone"))] = c
        if len(rows) < PAGE_SIZE:
            return out
        page += 1


async def get_contact(client: httpx.AsyncClient, ep: str, headers: dict, phone: str) -> dict | None:
    r = await client.get(
        f"{ep}/api/v1/getContacts",
        params={"pageSize": 5, "pageNumber": 1, "name": phone},
        headers=headers,
        timeout=30,
    )
    if r.status_code != 200:
        return None
    for c in r.json().get("contact_list") or []:
        if str(c.get("wAid") or c.get("phone")) == phone:
            return c
    return None


async def set_name(client: httpx.AsyncClient, ep: str, headers: dict, phone: str, name: str) -> bool:
    """addContact (create/update). Returns True only if WATI reports success. Retries 429/5xx."""
    for attempt in range(4):
        r = await client.post(
            f"{ep}/api/v1/addContact/{phone}",
            headers={**headers, "Content-Type": "application/json"},
            json={"name": name, "customParams": [{"name": "source", "value": "ArihantCRM"}]},
            timeout=30,
        )
        if r.status_code in (429, 500, 502, 503, 504):
            await asyncio.sleep(2 * (attempt + 1))
            continue
        if r.status_code != 200:
            print(f"    HTTP {r.status_code}: {r.text[:160]}")
            return False
        try:
            body = r.json()
        except Exception:
            return False
        res = body.get("result")
        return res is True or str(res).lower() in ("success", "true")
    return False


async def rollback(path: Path, apply: bool, delay: float) -> None:
    items = json.loads(path.read_text(encoding="utf-8"))
    ep = os.environ["WATI_API_ENDPOINT"].rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['WATI_API_TOKEN']}"}
    print(f"rollback {'APPLY' if apply else 'DRY-RUN'}: {len(items)} contacts from {path.name}")
    async with httpx.AsyncClient() as client:
        for it in items:
            print(f"  {it['phone']}: {it['new']!r} -> {it['old']!r}")
            if apply:
                await set_name(client, ep, headers, it["phone"], it["old"])
                await asyncio.sleep(delay)


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="Write to WATI (default: dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="Max contacts to fix (0 = no limit)")
    ap.add_argument("--only-phone", help="Restrict to one WhatsApp number, e.g. 447584020324")
    ap.add_argument("--include-international", action="store_true", help="Also fix non +91 numbers (review first)")
    ap.add_argument("--delay", type=float, default=0.6, help="Seconds between writes")
    ap.add_argument("--report", default="", help="CSV report path (default backups/wati_names_report_<ts>.csv)")
    ap.add_argument("--rollback", help="JSON backup file to restore old names from")
    args = ap.parse_args()

    for k in ("MONGO_URL", "DB_NAME", "WATI_API_ENDPOINT", "WATI_API_TOKEN"):
        if not os.environ.get(k):
            print(f"ERROR: {k} not set", file=sys.stderr)
            sys.exit(1)

    if args.rollback:
        await rollback(Path(args.rollback), args.apply, args.delay)
        return

    from crm.core.state import db  # noqa: E402 — after dotenv
    from crm.utils.helpers import normalize_phone  # noqa: E402

    ep = os.environ["WATI_API_ENDPOINT"].rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['WATI_API_TOKEN']}"}
    mode = "APPLY" if args.apply else "DRY-RUN"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = BACKEND_DIR / "scripts" / "backups"
    out_dir.mkdir(exist_ok=True)

    known_senders = set(SYSTEM_NAMES)
    async for u in db.users.find({}, {"_id": 0, "full_name": 1}):
        if u.get("full_name"):
            known_senders.add(_n(u["full_name"]))

    leads: dict[str, dict] = {}
    async for l in db.leads.find(
        {"normalized_phone": {"$nin": [None, ""]}},
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "name": 1, "phone": 1, "normalized_phone": 1},
    ):
        leads[l["normalized_phone"]] = l

    print(f"restore_wati_contact_names.py [{mode}] DB={os.environ['DB_NAME']}")
    async with httpx.AsyncClient() as client:
        contacts = await fetch_all_contacts(client, ep, headers)
        print(f"WATI contacts fetched: {len(contacts)} | CRM leads with phone: {len(leads)}")

        plan, reasons, rows = [], Counter(), []
        for phone, c in contacts.items():
            if args.only_phone and phone != args.only_phone:
                continue
            n10 = normalize_phone(phone)
            lead = leads.get(n10) if len(n10) == 10 else None
            action, reason = classify(c, lead, known_senders, args.include_international)
            if reason in ("not_tagged_by_crm", "no_matching_lead") and action == "skip":
                reasons[reason] += 1
                continue  # the bulk of WATI contacts: not CRM-sent, not interesting in the report
            reasons[reason] += 1
            wati_name = c.get("fullName") or c.get("firstName") or ""
            new = _crm_name(lead) if lead else ""
            rows.append([phone, wati_name, new, action, reason])
            if action == "fix":
                plan.append({"phone": phone, "old": wati_name, "new": new, "reason": reason})

        report = Path(args.report) if args.report else out_dir / f"wati_names_report_{ts}.csv"
        with report.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["phone", "wati_name_now", "crm_name", "action", "reason"])
            w.writerows(rows)

        print("\nBreakdown:")
        for k, v in reasons.most_common():
            print(f"  {k:36s} {v}")
        print(f"\nPlanned fixes: {len(plan)}   report: {report}")
        for p in plan[:15]:
            print(f"  {p['phone']}: {p['old']!r} -> {p['new']!r}  ({p['reason']})")
        if len(plan) > 15:
            print(f"  ... and {len(plan) - 15} more (see report)")

        if not args.apply:
            print("\nDRY-RUN: nothing written. Re-run with --apply (try --only-phone first).")
            return

        if args.limit:
            plan = plan[: args.limit]
        backup = out_dir / f"wati_names_{ts}.json"
        done: list[dict] = []
        backup.write_text("[]", encoding="utf-8")
        for p in plan:
            ok = await set_name(client, ep, headers, p["phone"], p["new"])
            await asyncio.sleep(args.delay)
            after = await get_contact(client, ep, headers, p["phone"]) if ok else None
            now = ((after or {}).get("fullName") or "").strip()
            if not ok or _n(now) != _n(p["new"]):
                print(f"ABORT: {p['phone']} did not update (wati now {now!r}). {len(done)} done before this.")
                break
            done.append(p)
            backup.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  ok {p['phone']}: {p['old']!r} -> {p['new']!r}")
        print(f"\nUpdated {len(done)}/{len(plan)}. Rollback file: {backup}")


if __name__ == "__main__":
    asyncio.run(main())
