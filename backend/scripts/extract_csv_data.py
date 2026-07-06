#!/usr/bin/env python3
"""
extract_csv_data.py
====================
Phase 2/3 of the CSV -> MongoDB import pipeline (see import_leads_to_db.py for Phase 4).

Reads the Freshworks CRM export in backend/csv/, transforms each Contact into the
same `leads` document shape backend/seed_db_v2.py already produces in production
(reusing its field-mapping logic read-only via import instead of re-deriving it),
and stages the result as reviewable JSON under backend/scripts/static_data/.

Every staged lead is explicitly marked:
    sla_paused        = True
    import_provenance = "freshworks"
so the live SLA engine treats it as a historical import on hold until a rep first
touches it (see crm/constants/lead_status.py::sla_paused_exclusion_clause and
crm/services/sla_helpers.py::create_sla_task_for_lead).

This script NEVER opens a database connection -- it only reads backend/csv/*.csv
and writes JSON files under --out-dir. Safe to re-run as many times as you like.

New activity types not handled by seed_db_v2.py:
  - Sales_activities.csv + Salesactivity_targetables.csv: merged into each lead's
    context_updates timeline (type="sales_activity"), same pattern as Notes/Tasks/Calls.
  - Task_collaborators.csv: staged separately (task_collaborators.json) for your own
    records. Not merged into leads_import.json -- nothing in the current tasks schema
    models per-task collaborators, and Freshworks Tasks are folded into lead
    context_updates as historical text rather than live `tasks` documents.

Known gap:
  - Note_targetables.csv (which used to link Notes.csv rows to a contact) is not
    present in this CSV drop. Without it, Notes.csv rows cannot be safely attributed
    to a specific lead, so they are staged separately in unlinked_notes.json instead
    of being merged (silently guessing the wrong lead would be worse than omitting).

Outputs (in --out-dir, default backend/scripts/static_data/):
  leads_import.json        - staged lead documents, ready for import_leads_to_db.py
  unlinked_notes.json      - Notes.csv rows that could not be matched to a contact
  task_collaborators.json  - Task id -> collaborator user reference, for your records
  extraction_report.json   - counts, warnings, and the Phase 3 verification results

Usage:
  python backend/scripts/extract_csv_data.py
  python backend/scripts/extract_csv_data.py --csv-dir backend/csv --out-dir backend/scripts/static_data
  python backend/scripts/extract_csv_data.py --sample-size 40 --seed 7
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import seed_db_v2 as sv2  # noqa: E402  (read-only reuse of the production field mapping)

DEFAULT_CSV_DIR = str(BACKEND_DIR / "csv")
DEFAULT_OUT_DIR = str(SCRIPT_DIR / "static_data")


# ─── JSON-safety helpers ───────────────────────────────────────────────────

def json_safe(obj: Any) -> Any:
    """Recursively convert datetimes to ISO strings so json.dump never chokes."""
    if isinstance(obj, datetime):
        return obj.astimezone(timezone.utc).isoformat()
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    return obj


# ─── New activity types not handled by seed_db_v2.py ───────────────────────

def build_sales_activity_map(csv_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    """Contact id -> Sales_activities.csv rows, linked via Salesactivity_targetables.csv."""
    activities_path = sv2.find_csv(csv_dir, "Sales_activities.csv")
    targetables_path = sv2.find_csv(csv_dir, "Salesactivity_targetables.csv")
    if not activities_path or not targetables_path:
        return {}
    activities_by_id = {r["Id"]: r for r in sv2.read_csv_file(activities_path) if r.get("Id")}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in sv2.read_csv_file(targetables_path):
        if (r.get("Related to Type") or "").strip().lower() != "contact":
            continue
        cid = r.get("Related to Id", "")
        aid = r.get("SalesActivity Id", "")
        if cid and aid and aid in activities_by_id:
            out.setdefault(cid, []).append(activities_by_id[aid])
    return out


def sales_activity_context_entries(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        title = (r.get("Title") or "").strip()
        atype = (r.get("Sales Activity Type") or "").strip()
        outcome = (r.get("Outcome") or "").strip()
        status = (r.get("Status") or "").strip()
        bits = [b for b in (title, f"({atype})" if atype else "", outcome, f"[{status}]" if status else "") if b]
        desc = " ".join(bits).strip()
        if not desc:
            continue
        ts_dt = sv2.parse_dt(r.get("Created at")) or sv2.parse_dt(r.get("Start date")) or sv2.utc_now()
        entry: Dict[str, Any] = {
            "type": "sales_activity",
            "timestamp": ts_dt.isoformat(),
            "timestamp_dt": ts_dt,
            "description": desc[:500],
            "agent": "freshworks",
        }
        if r.get("Id"):
            entry["note_id"] = f"salesactivity:{r['Id']}"
        out.append(entry)
    return out


def build_user_id_to_name(csv_dir: str) -> Dict[str, str]:
    """Best-effort Freshworks numeric user id -> display name, harvested from the
    '<X> id' / '<X>' column pairs already present in Contacts.csv and Sales_activities.csv."""
    mapping: Dict[str, str] = {}
    pairs = [
        ("Sales owner id", "Sales owner"),
        ("Created by id", "Created by"),
        ("Updated by id", "Updated by"),
    ]
    for fname in ("Contacts.csv", "Sales_activities.csv"):
        path = sv2.find_csv(csv_dir, fname)
        if not path:
            continue
        for row in sv2.read_csv_file(path):
            for id_col, name_col in pairs:
                uid = (row.get(id_col) or "").strip()
                name = (row.get(name_col) or "").strip()
                if uid and name:
                    mapping.setdefault(uid, name)
    return mapping


def build_task_collaborators(csv_dir: str, user_id_to_name: Dict[str, str]) -> List[Dict[str, Any]]:
    """Stage Task_collaborators.csv for your own records (see module docstring for why
    this is not merged into leads_import.json)."""
    path = sv2.find_csv(csv_dir, "Task_collaborators.csv")
    if not path:
        return []
    out: List[Dict[str, Any]] = []
    for r in sv2.read_csv_file(path):
        uid = (r.get("User id") or "").strip()
        out.append(
            {
                "id": r.get("Id"),
                "task_id": r.get("Task id"),
                "user_id": uid or None,
                "user_name": user_id_to_name.get(uid),
            }
        )
    return out


# ─── Phase 2: extraction ────────────────────────────────────────────────────

def extract(csv_dir: str, *, limit: int = 0, include_import_marker: bool = False) -> Dict[str, Any]:
    warnings: List[str] = []

    paths = {
        "contacts": sv2.find_csv(csv_dir, "Contacts.csv"),
        "notes": sv2.find_csv(csv_dir, "Notes.csv"),
        "note_tgt": sv2.find_csv(csv_dir, "Note_targetables.csv"),
        "tasks": sv2.find_csv(csv_dir, "Tasks.csv"),
        "task_tgt": sv2.find_csv(csv_dir, "Task_targetables.csv"),
        "calls": sv2.find_csv(csv_dir, "Call_logs.csv"),
        "emails": sv2.find_csv(csv_dir, "Contact_emails.csv"),
    }
    if not paths["contacts"]:
        raise SystemExit(f"Contacts.csv not found under {csv_dir}")
    if paths["notes"] and not paths["note_tgt"]:
        warnings.append(
            "Note_targetables.csv not found -- Notes.csv rows cannot be linked to a "
            "specific contact and will NOT be merged into any lead's timeline. "
            "They are staged separately in unlinked_notes.json instead."
        )

    fw_rows = sv2.read_csv_file(paths["contacts"])
    if limit:
        fw_rows = fw_rows[:limit]
    fw_by_id = {r.get("Id", ""): r for r in fw_rows if r.get("Id")}

    contact_notes, contact_calls, contact_tasks, email_fb = sv2.build_activity_maps(paths)
    contact_sales_activities = build_sales_activity_map(csv_dir)
    user_id_to_name = build_user_id_to_name(csv_dir)
    task_collaborators = build_task_collaborators(csv_dir, user_id_to_name)

    _users, name_to_user_id = sv2.build_users()

    # Lazy import: mirrors the deferred import already used inside seed_db_v2.build_context_updates.
    from crm.services.context_updates import dedupe_context_updates

    merged_contacts = [sv2.merge_contact_rows(cid, row, None) for cid, row in fw_by_id.items()]
    merged_contacts.sort(key=lambda c: c.updated_at_dt, reverse=True)

    leads: List[Dict[str, Any]] = []
    skipped_no_phone = 0
    dupes_in_batch = 0
    seen_phone: Dict[str, str] = {}
    seen_email: Dict[str, str] = {}

    for cm in merged_contacts:
        lead = sv2.transform_to_lead(
            cm,
            name_to_user_id,
            contact_notes,
            contact_calls,
            contact_tasks,
            email_fb,
            include_import_marker=include_import_marker,
        )
        if not lead:
            skipped_no_phone += 1
            continue

        extra_ctx = sales_activity_context_entries(contact_sales_activities.get(cm.contact_id, []))
        if extra_ctx:
            lead["context_updates"] = dedupe_context_updates(lead["context_updates"] + extra_ctx)[:50]

        # Contacts.csv "Lost reason" maps 1:1 to the existing lost_reason schema field
        # (LeadUpdatePatch / LeadResponse) but seed_db_v2.transform_to_lead doesn't capture it.
        lost_reason = (cm.chosen.get("Lost reason") or "").strip()
        if lost_reason:
            lead["lost_reason"] = lost_reason

        # Canonical SLA-aligned lead_status (see crm.constants.import_status_map).
        # Every imported lead remains sla_paused=True until a rep changes status.
        lead["sla_paused"] = True
        lead["import_provenance"] = "freshworks"

        from crm.constants.import_status_map import fw_status_to_canonical

        fw_label = (lead.get("original_fw_status") or "").strip()
        canonical, is_rnr = fw_status_to_canonical(fw_label)
        lead["lead_status"] = canonical
        lead["is_rnr"] = bool(is_rnr or lead.get("is_rnr"))

        # Match backend/scripts/backfill_lead_overview_fields.py's convention: original_source /
        # most_recent_source fall back to lead_source when the CSV didn't provide them (affects
        # ~54%/62% of this dataset -- doing it at import time avoids needing that migration re-run).
        if not lead.get("original_source"):
            lead["original_source"] = lead.get("lead_source")
        if not lead.get("most_recent_source"):
            lead["most_recent_source"] = lead.get("lead_source")

        # seed_db_v2's assigned_user_id is a deterministic placeholder UUID that will NOT
        # match real production user ids. Keep the human-readable name only; the import
        # script resolves this against the live `users` collection at import time.
        lead.pop("assigned_user_id", None)

        nphone = lead.get("normalized_phone") or ""
        email = (lead.get("email") or "").strip().lower()
        if nphone and nphone in seen_phone:
            dupes_in_batch += 1
            continue
        if (not nphone or len(nphone) != 10) and email and email in seen_email:
            dupes_in_batch += 1
            continue
        if nphone:
            seen_phone[nphone] = lead["id"]
        if email:
            seen_email[email] = lead["id"]

        leads.append(lead)

    unlinked_notes: List[Dict[str, Any]] = []
    if paths["notes"] and not paths["note_tgt"]:
        unlinked_notes = sv2.read_csv_file(paths["notes"])

    stats = {
        "generated_at": sv2.utc_now().isoformat(),
        "csv_dir": str(csv_dir),
        "contacts_total": len(fw_by_id),
        "leads_staged": len(leads),
        "skipped_no_valid_phone": skipped_no_phone,
        "duplicates_deduped_in_batch": dupes_in_batch,
        "contacts_with_notes_linked": len(contact_notes),
        "contacts_with_calls_linked": len(contact_calls),
        "contacts_with_tasks_linked": len(contact_tasks),
        "contacts_with_sales_activities_linked": len(contact_sales_activities),
        "unlinked_notes_count": len(unlinked_notes),
        "task_collaborators_staged": len(task_collaborators),
        "warnings": warnings,
    }

    return {
        "leads": leads,
        "unlinked_notes": unlinked_notes,
        "task_collaborators": task_collaborators,
        "stats": stats,
    }


# ─── Phase 3: verification ──────────────────────────────────────────────────

def verify_sample(
    leads: List[Dict[str, Any]], csv_dir: str, *, sample_size: int, seed: Optional[int]
) -> Dict[str, Any]:
    """Independently re-reads Contacts.csv from disk (not the in-memory rows used during
    extraction) and cross-checks a random sample of staged leads against it.

    Only compares fields that are pure, deterministic re-derivations of the CSV. Fields
    with intentional randomness in seed_db_v2.py (budget-bucket fallback for unparsable
    budgets, rep assignment for leads with no CSV owner) are deliberately excluded --
    they are expected to differ across separate runs and are not a correctness signal.
    """
    contacts_path = sv2.find_csv(csv_dir, "Contacts.csv")
    fresh_rows = sv2.read_csv_file(contacts_path)
    fresh_by_id = {r.get("Id", ""): r for r in fresh_rows if r.get("Id")}

    rng = random.Random(seed)
    population = [l for l in leads if l.get("external_id")]
    n = min(sample_size, len(population))
    sample = rng.sample(population, n) if n else []

    results = []
    for lead in sample:
        cid = lead["external_id"]
        raw = fresh_by_id.get(cid)
        mismatches: List[str] = []
        if raw is None:
            mismatches.append("source Contacts.csv row not found for external_id")
        else:
            expected_first = (raw.get("First name") or "").strip() or "Unknown"
            expected_last = (raw.get("Last name") or "").strip() or ""
            if lead.get("first_name") != expected_first:
                mismatches.append(f"first_name: staged={lead.get('first_name')!r} csv={expected_first!r}")
            if lead.get("last_name") != expected_last:
                mismatches.append(f"last_name: staged={lead.get('last_name')!r} csv={expected_last!r}")

            raw_phone = (raw.get("Mobile") or "").strip() or (raw.get("Work") or "").strip()
            expected_norm = sv2.normalize_phone(raw_phone)
            if lead.get("normalized_phone") != expected_norm:
                mismatches.append(
                    f"normalized_phone: staged={lead.get('normalized_phone')!r} csv={expected_norm!r}"
                )

            expected_status = (raw.get("Status") or "").strip() or None
            if lead.get("original_fw_status") != expected_status:
                mismatches.append(
                    f"original_fw_status: staged={lead.get('original_fw_status')!r} csv={expected_status!r}"
                )

        if lead.get("sla_paused") is not True:
            mismatches.append(f"sla_paused: expected True, got {lead.get('sla_paused')!r}")
        if lead.get("import_provenance") != "freshworks":
            mismatches.append(
                f"import_provenance: expected 'freshworks', got {lead.get('import_provenance')!r}"
            )

        from crm.constants.import_status_map import fw_status_to_canonical

        expected_status, _ = fw_status_to_canonical(lead.get("original_fw_status") or "")
        if lead.get("lead_status") != expected_status:
            mismatches.append(
                f"lead_status: staged={lead.get('lead_status')!r}, expected canonical "
                f"{expected_status!r}"
            )

        results.append(
            {"external_id": cid, "lead_id": lead.get("id"), "ok": not mismatches, "mismatches": mismatches}
        )

    passed = sum(1 for r in results if r["ok"])
    return {
        "sample_size_requested": sample_size,
        "sample_size_used": n,
        "population_size": len(population),
        "seed": seed,
        "passed": passed,
        "failed": n - passed,
        "results": results,
    }


# ─── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv-dir", default=DEFAULT_CSV_DIR)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--limit", type=int, default=0, help="Debug: cap number of contacts processed")
    ap.add_argument("--sample-size", type=int, default=25, help="Phase 3 verification sample size")
    ap.add_argument("--seed", type=int, default=None, help="Random seed for reproducible sampling")
    ap.add_argument(
        "--include-seed-marker",
        action="store_true",
        help="Append a synthetic 'Imported via extract_csv_data' timeline entry (off by default)",
    )
    args = ap.parse_args()

    print("\n" + "=" * 72)
    print("  extract_csv_data.py -- Phase 2/3: CSV -> staged JSON (no DB access)")
    print("=" * 72)
    print(f"  CSV dir : {args.csv_dir}")
    print(f"  Out dir : {args.out_dir}\n")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("--- Phase 2: extracting + staging ---\n")
    result = extract(args.csv_dir, limit=args.limit, include_import_marker=args.include_seed_marker)
    leads = result["leads"]

    for w in result["stats"]["warnings"]:
        print(f"  [WARN] {w}")

    leads_path = out_dir / "leads_import.json"
    with open(leads_path, "w", encoding="utf-8") as f:
        json.dump(json_safe(leads), f, indent=2, ensure_ascii=False)
    print(f"  [OK] wrote {leads_path.name}  ({len(leads):,} leads)")

    notes_path = out_dir / "unlinked_notes.json"
    with open(notes_path, "w", encoding="utf-8") as f:
        json.dump(json_safe(result["unlinked_notes"]), f, indent=2, ensure_ascii=False)
    print(f"  [OK] wrote {notes_path.name}  ({len(result['unlinked_notes']):,} rows)")

    collab_path = out_dir / "task_collaborators.json"
    with open(collab_path, "w", encoding="utf-8") as f:
        json.dump(json_safe(result["task_collaborators"]), f, indent=2, ensure_ascii=False)
    print(f"  [OK] wrote {collab_path.name}  ({len(result['task_collaborators']):,} rows)")

    print("\n--- Phase 3: verifying staged JSON against source CSVs ---\n")
    # Reload from disk so verification checks what was actually written, not just what's in memory.
    with open(leads_path, "r", encoding="utf-8") as f:
        reloaded = json.load(f)
    verification = verify_sample(reloaded, args.csv_dir, sample_size=args.sample_size, seed=args.seed)

    for r in verification["results"]:
        status = "PASS" if r["ok"] else "FAIL"
        print(f"  [{status}] external_id={r['external_id']} lead_id={r['lead_id']}")
        for m in r["mismatches"]:
            print(f"          - {m}")

    print(
        f"\n  Sampled {verification['sample_size_used']} / {verification['population_size']} staged leads "
        f"(seed={verification['seed']})"
    )
    if verification["failed"] == 0:
        print(f"  [OK] All {verification['passed']} sampled records match their source CSV rows exactly.")
    else:
        print(
            f"  [FAIL] {verification['failed']} of {verification['sample_size_used']} sampled records "
            "mismatched -- see above."
        )

    result["stats"]["verification"] = verification
    report_path = out_dir / "extraction_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(json_safe(result["stats"]), f, indent=2, ensure_ascii=False)
    print(f"\n  [OK] wrote {report_path.name}")

    print("\n" + "=" * 72)
    print("  Phase 2/3 complete. No database was touched.")
    print("  Next: review the JSON above, then see scripts/import_leads_to_db.py")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
