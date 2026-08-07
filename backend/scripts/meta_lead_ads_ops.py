"""
Meta Lead Ads ops: token health, page leadgen subscribe, form backfill.

Run inside prod container or from backend/ with prod .env:

  python scripts/meta_lead_ads_ops.py health
  python scripts/meta_lead_ads_ops.py subscribe
  python scripts/meta_lead_ads_ops.py backfill --hours 72
  python scripts/meta_lead_ads_ops.py backfill --match-phone 8754025211 --match-phone 9790942415
  python scripts/meta_lead_ads_ops.py manual-contacts   # Manish + Latha known-contact ingest

Does NOT print token values. Safe to run read-only with `health`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env", override=False)

from crm.core.state import (  # noqa: E402
    META_API_VERSION,
    META_LEAD_FORM_PROJECT_MAP,
    META_PAGE_ACCESS_TOKEN,
    META_PAGE_ID,
    db,
)
from crm.services.meta_lead_ads_service import process_leadgen_event  # noqa: E402
from crm.services.lead_intake_service import ingest_lead  # noqa: E402

# Known missed contacts (client report Aug 2026) — used only by manual-contacts.
MANUAL_CONTACTS = [
    {
        "first_name": "Manish",
        "last_name": "Thakkar",
        "email": "ruling.piping-5n@icloud.com",
        "phone": "+918754025211",
        "project_id": "reserve-16",
        "project_name": "Reserve 16",
        "note": "Fresh Meta lead — missed Clara webhook path",
    },
    {
        "first_name": "Latha",
        "last_name": "Ramalingam",
        "email": "latharam1964@gmail.com",
        "phone": "+919790942415",
        "project_id": "melange",
        "project_name": "Mélange",
        "note": "Fresh Meta lead — missed Clara webhook path",
    },
]


def _version() -> str:
    return (META_API_VERSION or "v21.0").strip().lstrip("/")


def _token() -> str:
    return (META_PAGE_ACCESS_TOKEN or "").strip()


def _page_id() -> str:
    return (META_PAGE_ID or "").strip()


def _auth_headers(token: str) -> Dict[str, str]:
    # Prefer Authorization header so access_token never appears in httpx URL logs.
    return {"Authorization": f"Bearer {token}"}


async def cmd_health() -> int:
    token = _token()
    page_id = _page_id()
    version = _version()
    print(f"PAGE_ID={page_id or '(missing)'} token_set={bool(token)} token_len={len(token)}")
    print(f"FORM_MAP_KEYS={list(META_LEAD_FORM_PROJECT_MAP.keys())}")
    if not token:
        print("FAIL: META_PAGE_ACCESS_TOKEN empty")
        return 1

    headers = _auth_headers(token)
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"https://graph.facebook.com/{version}/me",
            params={"fields": "id,name"},
            headers=headers,
        )
        print(f"/me HTTP {r.status_code}: {r.text[:300]}")
        if r.status_code != 200:
            print("FAIL: Page token invalid — generate a new long-lived Page token with leads_retrieval")
            return 2

        if page_id:
            r2 = await client.get(
                f"https://graph.facebook.com/{version}/{page_id}/subscribed_apps",
                headers=headers,
            )
            print(f"subscribed_apps HTTP {r2.status_code}: {r2.text[:600]}")

        ok_forms = 0
        for form_id, project in META_LEAD_FORM_PROJECT_MAP.items():
            r3 = await client.get(
                f"https://graph.facebook.com/{version}/{form_id}/leads",
                params={"limit": 1, "fields": "id,created_time"},
                headers=headers,
            )
            print(f"form {form_id} ({project}) leads HTTP {r3.status_code}")
            if r3.status_code == 200:
                ok_forms += 1
            else:
                print(f"  err: {r3.text[:200]}")
        print(f"forms_readable={ok_forms}/{len(META_LEAD_FORM_PROJECT_MAP)}")
        return 0 if ok_forms else 3


async def cmd_subscribe() -> int:
    token = _token()
    page_id = _page_id()
    version = _version()
    if not token or not page_id:
        print("FAIL: need META_PAGE_ACCESS_TOKEN and META_PAGE_ID")
        return 1
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"https://graph.facebook.com/{version}/{page_id}/subscribed_apps",
            params={"subscribed_fields": "leadgen"},
            headers=_auth_headers(token),
        )
        print(f"subscribe HTTP {r.status_code}: {r.text[:500]}")
        return 0 if r.status_code == 200 else 1


def _field_blob(field_data: Any) -> str:
    parts: List[str] = []
    if not isinstance(field_data, list):
        return ""
    for item in field_data:
        if not isinstance(item, dict):
            continue
        vals = item.get("values") or []
        if isinstance(vals, list):
            parts.extend(str(v) for v in vals)
        else:
            parts.append(str(vals))
    return " ".join(parts).lower()


async def cmd_backfill(hours: int, match_phones: List[str], match_emails: List[str], dry_run: bool) -> int:
    health = await cmd_health()
    if health != 0:
        return health

    token = _token()
    version = _version()
    needles = [p[-10:] for p in match_phones if p] + [e.lower() for e in match_emails if e]
    processed = 0
    matched = 0

    headers = _auth_headers(token)
    async with httpx.AsyncClient(timeout=60.0) as client:
        for form_id, project in META_LEAD_FORM_PROJECT_MAP.items():
            url = f"https://graph.facebook.com/{version}/{form_id}/leads"
            params: Dict[str, Any] = {
                "limit": 50,
                "fields": "id,created_time,ad_id,form_id,field_data",
            }
            # paging through recent leads
            pages = 0
            while url and pages < 10:
                pages += 1
                r = await client.get(
                    url,
                    params=params if pages == 1 else None,
                    headers=headers if pages == 1 else None,
                )
                if r.status_code != 200:
                    print(f"skip form {form_id}: {r.status_code} {r.text[:160]}")
                    break
                body = r.json()
                for item in body.get("data") or []:
                    leadgen_id = str(item.get("id") or "")
                    blob = _field_blob(item.get("field_data"))
                    if needles and not any(n.lower() in blob for n in needles):
                        # when matching, also allow time window without match filter if no needles
                        continue
                    if not needles and hours > 0:
                        # created_time filter best-effort (ISO)
                        # If Meta returns older than window we still process first pages only.
                        pass
                    matched += 1
                    print(f"MATCH form={form_id} project={project} leadgen_id={leadgen_id}")
                    if dry_run:
                        continue
                    value = {
                        "leadgen_id": leadgen_id,
                        "form_id": str(item.get("form_id") or form_id),
                        "page_id": _page_id() or None,
                        "ad_id": str(item.get("ad_id") or "") or None,
                    }
                    result = await process_leadgen_event(value)
                    processed += 1
                    print(f"  -> {json.dumps(result)}")
                paging = body.get("paging") or {}
                url = paging.get("next")
                params = None

    print(f"done matched={matched} processed={processed} dry_run={dry_run}")
    return 0


async def cmd_manual_contacts(dry_run: bool) -> int:
    """Ingest known Fresh→Clara misses by email/phone when Graph leadgen_id is unavailable."""
    created = []
    for c in MANUAL_CONTACTS:
        existing = await db.leads.find_one(
            {
                "$or": [
                    {"email": {"$regex": f"^{c['email']}$", "$options": "i"}},
                    {"phone": {"$regex": c["phone"][-10:]}},
                    {"normalized_phone": {"$regex": c["phone"][-10:]}},
                ]
            },
            {"_id": 0, "id": 1, "first_name": 1, "lead_source": 1, "project": 1},
        )
        if existing:
            print(f"SKIP exists {c['first_name']}: {existing}")
            if not dry_run:
                from crm.services.whatsapp_service import send_lead_ack

                lead = await db.leads.find_one({"id": existing["id"]}, {"_id": 0})
                if lead:
                    has_ack = any(
                        (u.get("type") == "whatsapp" and u.get("agent") == "System Auto-Ack")
                        for u in (lead.get("context_updates") or [])
                    )
                    if not has_ack:
                        ack = await send_lead_ack(existing["id"], lead)
                        print(f"  missing-ack repaired: {json.dumps(ack)}")
            continue
        body = {
            "first_name": c["first_name"],
            "last_name": c["last_name"],
            "email": c["email"],
            "phone": c["phone"],
            "consent": True,
            "source": "Facebook Lead Form",
            "meta": {
                "backfill": "manual_contacts",
                "note": c["note"],
                "fresh_missed_clara": True,
            },
        }
        api_key = {
            "id": f"meta-lead-ads:{c['project_id']}",
            "project_id": c["project_id"],
            "project_name": c["project_name"],
            "rate_limit_per_min": 120,
        }
        print(f"INGEST {c['first_name']} {c['last_name']} -> {c['project_id']} dry_run={dry_run}")
        if dry_run:
            continue
        result, status = await ingest_lead(body=body, api_key=api_key, ip="meta-ops-manual")
        print(f"  status={status} result={json.dumps(result)}")
        lead_id = result.get("lead_id")
        created.append(lead_id)
        # Belt-and-suspenders: if intake ever fire-and-forgets again, still ack here.
        if lead_id and not result.get("deduped"):
            from crm.services.whatsapp_service import send_lead_ack

            lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
            if lead:
                # Skip if timeline already has System Auto-Ack
                has_ack = any(
                    (u.get("type") == "whatsapp" and u.get("agent") == "System Auto-Ack")
                    for u in (lead.get("context_updates") or [])
                )
                if not has_ack:
                    ack = await send_lead_ack(lead_id, lead)
                    print(f"  ack={json.dumps(ack)}")
    print(f"manual_contacts created={created}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Meta Lead Ads ops")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health", help="Validate Page token + form lead read access")
    sub.add_parser("subscribe", help="POST page subscribed_apps leadgen")

    bf = sub.add_parser("backfill", help="Pull Instant Form leads from Graph and ingest")
    bf.add_argument("--hours", type=int, default=72, help="Hint window (pages limited)")
    bf.add_argument("--match-phone", action="append", default=[], help="Only leads containing this phone")
    bf.add_argument("--match-email", action="append", default=[], help="Only leads containing this email")
    bf.add_argument("--dry-run", action="store_true")

    mc = sub.add_parser("manual-contacts", help="Ingest Manish/Latha from known contact fields")
    mc.add_argument("--dry-run", action="store_true")

    args = p.parse_args()

    if args.cmd == "health":
        raise SystemExit(asyncio.run(cmd_health()))
    if args.cmd == "subscribe":
        raise SystemExit(asyncio.run(cmd_subscribe()))
    if args.cmd == "backfill":
        raise SystemExit(
            asyncio.run(
                cmd_backfill(args.hours, args.match_phone, args.match_email, args.dry_run)
            )
        )
    if args.cmd == "manual-contacts":
        raise SystemExit(asyncio.run(cmd_manual_contacts(args.dry_run)))


if __name__ == "__main__":
    main()
