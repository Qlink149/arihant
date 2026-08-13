"""
Live smoke: form intake + Meta CAPI + Zapier Meta lead webhook against production,
then delete only leads/logs/keys created by this run.

Run from backend/:
  python scripts/live_meta_form_smoke.py

Uses MONGO_URL / META_* / ZAPIER_WEBHOOK_SECRET from backend/.env.
Hits https://arihant-api.claraai.tech for HTTP surfaces.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env", override=True)

PROD_API = os.environ.get("LIVE_SMOKE_API_BASE", "https://arihant-api.claraai.tech").rstrip("/")
TEST_PHONE = "+919116914178"
TEST_PREFIX = "TESTLIVE_Clara"
MARKER = f"clara-live-smoke-{int(time.time())}"


def _normalize_digits(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())


async def _existing_phone_leads(db) -> List[dict]:
    digits = _normalize_digits(TEST_PHONE)
    cursor = db.leads.find(
        {
            "$or": [
                {"phone": {"$regex": digits[-10:]}},
                {"normalized_phone": {"$regex": digits[-10:]}},
                {"work_phone": {"$regex": digits[-10:]}},
            ]
        },
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "lead_source": 1, "project": 1},
    )
    return await cursor.to_list(length=50)


async def main() -> None:
    from crm.core.state import (
        META_LEAD_FORM_PROJECT_MAP,
        ZAPIER_WEBHOOK_SECRET,
        db,
    )
    from crm.services.api_key_service import create_api_key
    from crm.services.meta_capi_service import send_qualified_lead_event
    from crm.services.zapier_leads_service import map_zap_payload_to_intake
    from crm.services.lead_intake_service import ingest_lead

    report: Dict[str, Any] = {"steps": [], "created_lead_ids": [], "api_key_id": None}
    snapshots: Dict[str, dict] = {}

    print(f"=== Live smoke against {PROD_API} ===")
    print(f"Marker: {MARKER}")

    preexisting = await _existing_phone_leads(db)
    print(f"\n[0] Existing leads matching {TEST_PHONE}: {len(preexisting)}")
    for row in preexisting:
        print(f"    - {row.get('id')} | {row.get('first_name')} | {row.get('lead_source')} | {row.get('project')}")
        snapshots[row["id"]] = row

    # --- API key (temp) ---
    key = await create_api_key(
        project_name="Mélange",
        client_name=f"Clara Live Smoke {MARKER}",
        rate_limit_per_min=30,
    )
    report["api_key_id"] = key["id"]
    plaintext = key["plaintext_key"]
    print(f"\n[1] Temp intake key created id={key['id']} prefix={key['key_prefix']}...")

    # Prefer unique email so we don't clobber a real lead if phone collides — still send user phone.
    # If a non-TESTLIVE lead owns this phone on Mélange, intake will soft-dedupe and rewrite names;
    # we snapshot and restore those fields after.
    email = f"{MARKER}@example.com"
    intake_body = {
        "first_name": TEST_PREFIX,
        "last_name": "SmokeTest",
        "email": email,
        "phone": TEST_PHONE,
        "budget": "Live smoke only - delete",
        "schedule_visit": MARKER,
        "consent": True,
        "source": "Clara Live Smoke Form",
        "meta": {"smoke": MARKER, "do_not_keep": True},
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        # --- Form intake via live URL ---
        r = await client.post(
            f"{PROD_API}/api/v1/leads/intake",
            headers={"Content-Type": "application/json", "X-API-Key": plaintext},
            json=intake_body,
        )
        intake_json = r.json() if r.content else {}
        report["steps"].append(
            {"name": "form_intake", "status": r.status_code, "body": intake_json}
        )
        print(f"\n[2] Form intake HTTP {r.status_code}: {intake_json}")
        if r.status_code not in (200, 201) or not intake_json.get("lead_id"):
            print("FAIL: intake did not create/return lead_id - aborting before CAPI")
            await _cleanup(db, report, snapshots, created_only=True)
            _print_summary(report)
            sys.exit(1)

        intake_lead_id = intake_json["lead_id"]
        if intake_lead_id not in snapshots or str(snapshots.get(intake_lead_id, {}).get("first_name", "")).startswith(
            "TESTLIVE"
        ):
            report["created_lead_ids"].append(intake_lead_id)
        else:
            report["deduped_onto_existing"] = intake_lead_id
            print(
                f"    WARN: soft-deduped onto existing lead {intake_lead_id} - will restore snapshot, not delete"
            )

        try:
            # --- CRM -> Meta CAPI (same tokens as prod) ---
            lead = await db.leads.find_one({"id": intake_lead_id}, {"_id": 0})
            if not lead:
                print("FAIL: lead not found in Mongo after intake")
                sys.exit(1)

            capi = await send_qualified_lead_event(lead)
            report["steps"].append({"name": "meta_capi", "result": capi})
            print(f"\n[3] Meta CAPI: success={capi.get('success')} http={capi.get('response_status')} "
                  f"event_id={capi.get('event_id')} err={capi.get('error_message')}")

            # --- Zapier Meta lead webhook (live) ---
            zap_secret = (ZAPIER_WEBHOOK_SECRET or "").strip()
            form_id = next(iter(META_LEAD_FORM_PROJECT_MAP.keys()), None) or "4309061012643289"
            zap_url = f"{PROD_API}/api/zapier/leads/webhook"

            bad = await client.post(
                zap_url,
                json={"Form ID": form_id},
                headers={"Content-Type": "application/json", "X-Webhook-Secret": "deadbeef"},
            )
            report["steps"].append({"name": "zapier_bad_secret", "status": bad.status_code})
            print(f"\n[4] Zapier bad secret -> HTTP {bad.status_code} (expect 401)")

            synthetic_leadgen = f"smoke_leadgen_{MARKER}"
            zap_payload = {
                "Created At": "",
                "Lead ID": synthetic_leadgen,
                "Form ID": form_id,
                "First Name": f"{TEST_PREFIX}_Zap",
                "Last Name": "SmokeTest",
                "Email": f"zap.{MARKER}@example.com",
                "Phone Number": TEST_PHONE,
                "Budget": "",
                "Site Visit Preference": "",
            }
            if zap_secret:
                good = await client.post(
                    f"{zap_url}?token={zap_secret}",
                    json=zap_payload,
                    headers={"Content-Type": "application/json"},
                )
                report["steps"].append(
                    {
                        "name": "zapier_signed_synthetic",
                        "status": good.status_code,
                        "body": good.text[:200],
                    }
                )
                print(f"[4b] Zapier POST -> HTTP {good.status_code} body={good.text[:120]}")
                zap_log = await db.zapier_leads_logs.find_one(
                    {"leadgen_id": synthetic_leadgen}, {"_id": 0, "lead_id": 1}
                )
                zap_lead_id = (zap_log or {}).get("lead_id")
                if zap_lead_id and (
                    zap_lead_id not in snapshots
                    or str(snapshots.get(zap_lead_id, {}).get("first_name", "")).startswith("TESTLIVE")
                ):
                    if zap_lead_id not in report["created_lead_ids"]:
                        report["created_lead_ids"].append(zap_lead_id)
            else:
                print("[4b] SKIP Zapier POST (ZAPIER_WEBHOOK_SECRET empty)")

            # --- Zap mapper -> intake without hitting live webhook twice ---
            mapped = map_zap_payload_to_intake(
                zap_payload,
                leadgen_id=f"local_path_{MARKER}",
                form_id=form_id,
            )
            mapped["first_name"] = f"{TEST_PREFIX}_Meta"
            mapped["meta"] = {**(mapped.get("meta") or {}), "smoke": MARKER}
            api_key_doc = {
                "id": key["id"],
                "project_name": key["project_name"],
                "project_id": key["project_id"],
                "client_name": key["client_name"],
                "is_active": True,
                "rate_limit_per_min": 30,
            }
            meta_result, meta_status = await ingest_lead(body=mapped, api_key=api_key_doc, ip="live-smoke")
            report["steps"].append(
                {"name": "zapier_mapper_ingest", "status": meta_status, "body": meta_result}
            )
            print(f"\n[5] Zapier mapper->intake HTTP-equiv {meta_status}: {meta_result}")
            meta_lead_id = (meta_result or {}).get("lead_id")
            if meta_lead_id and (
                meta_lead_id not in snapshots
                or str(snapshots.get(meta_lead_id, {}).get("first_name", "")).startswith("TESTLIVE")
            ):
                if meta_lead_id not in report["created_lead_ids"]:
                    report["created_lead_ids"].append(meta_lead_id)
        finally:
            print("\n[7] Cleanup...")
            await _cleanup(db, report, snapshots, created_only=True)
            _print_summary(report)
        return

    # unreachable for success path; kept for early fail after client closed
    print("\n[7] Cleanup...")
    await _cleanup(db, report, snapshots, created_only=True)
    _print_summary(report)


async def _cleanup(db, report: dict, snapshots: Dict[str, dict], *, created_only: bool) -> None:
    # Restore deduped real lead if we overwrote names
    deduped = report.get("deduped_onto_existing")
    if deduped and deduped in snapshots:
        snap = snapshots[deduped]
        await db.leads.update_one(
            {"id": deduped},
            {
                "$set": {
                    "first_name": snap.get("first_name"),
                    "last_name": snap.get("last_name"),
                }
            },
        )
        print(f"    Restored names on existing lead {deduped}")

    for lid in list(report.get("created_lead_ids") or []):
        lead = await db.leads.find_one({"id": lid}, {"_id": 0, "first_name": 1})
        fn = (lead or {}).get("first_name") or ""
        if not str(fn).startswith("TESTLIVE"):
            print(f"    SKIP delete {lid} (not TESTLIVE_*): {fn}")
            continue
        await db.leads.delete_one({"id": lid})
        await db.whatsapp_messages.delete_many({"lead_id": lid})
        await db.tasks.delete_many({"lead_id": lid})
        await db.notifications.delete_many({"lead_id": lid})
        await db.meta_capi_logs.delete_many({"lead_id": lid})
        print(f"    Deleted lead {lid} + related msgs/tasks/notifs/capi logs")

    key_id = report.get("api_key_id")
    if key_id:
        await db.api_keys.delete_one({"id": key_id})
        await db.lead_intake_logs.delete_many({"api_key_id": key_id})
        print(f"    Deleted temp API key {key_id} + its intake logs")

    await db.zapier_leads_logs.delete_many(
        {"leadgen_id": {"$regex": f"^{MARKER}|smoke_leadgen_{MARKER}|local_path_{MARKER}"}}
    )
    await db.zapier_leads_logs.delete_many(
        {"leadgen_id": {"$in": [f"smoke_leadgen_{MARKER}", f"local_path_{MARKER}"]}}
    )
    print("    Cleared smoke zapier_leads_logs")


def _print_summary(report: dict) -> None:
    print("\n=== SUMMARY ===")
    for step in report.get("steps") or []:
        name = step.get("name")
        if name == "meta_capi":
            r = step.get("result") or {}
            print(f"  {name}: success={r.get('success')} http={r.get('response_status')}")
        else:
            print(f"  {name}: status={step.get('status')} ok={step.get('ok')}")
    print(f"  created_lead_ids: {report.get('created_lead_ids')}")
    print(f"  deduped_onto_existing: {report.get('deduped_onto_existing')}")


if __name__ == "__main__":
    asyncio.run(main())
