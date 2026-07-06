#!/usr/bin/env python3
"""
validate_staged_data.py
========================
Full-coverage (100%, not sampled) correctness audit of backend/scripts/static_data/
leads_import.json before it ever reaches import_leads_to_db.py.

Unlike extract_csv_data.py's Phase 3 (a random spot-check), this re-derives and
cross-checks EVERY staged lead against the source CSVs, validates every document
against the live Pydantic LeadResponse schema, checks uniqueness invariants across
the whole file, reconciles join/linkage counts against the *_targetables CSVs, and
scans for encoding artifacts. Exit code is non-zero if anything fails.

Never opens a database connection.

Usage:
  python backend/scripts/validate_staged_data.py
  python backend/scripts/validate_staged_data.py --input backend/scripts/static_data/leads_import.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import seed_db_v2 as sv2  # noqa: E402
from import_leads_to_db import restore_datetimes  # noqa: E402  (pure function, no DB import-time side effects)
from crm.models.schemas.lead_schemas import LeadResponse  # noqa: E402  (pure pydantic model)
from crm.services.context_updates import dedupe_context_updates  # noqa: E402

DEFAULT_INPUT = SCRIPT_DIR / "static_data" / "leads_import.json"
DEFAULT_CSV_DIR = str(BACKEND_DIR / "csv")

MOJIBAKE_MARKERS = ("�", "Ã", "â€", "Â")


class Findings:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def load_staged(path: Path) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ─── 1. Uniqueness invariants ────────────────────────────────────────────────

def check_uniqueness(leads: List[Dict[str, Any]], f: Findings) -> None:
    ids = Counter(l.get("id") for l in leads)
    ext_ids = Counter(l.get("external_id") for l in leads if l.get("external_id"))
    phones = Counter(l.get("normalized_phone") for l in leads if l.get("normalized_phone"))

    for val, count in ids.items():
        if count > 1:
            f.error(f"duplicate id in staged file: {val!r} appears {count} times")
    for val, count in ext_ids.items():
        if count > 1:
            f.error(f"duplicate external_id in staged file: {val!r} appears {count} times")
    for val, count in phones.items():
        if count > 1:
            f.error(f"duplicate normalized_phone in staged file: {val!r} appears {count} times")

    missing_id = sum(1 for l in leads if not l.get("id"))
    if missing_id:
        f.error(f"{missing_id} lead(s) missing 'id'")


# ─── 2. Field-level re-derivation against fresh Contacts.csv (100% coverage) ──

def check_field_derivation(leads: List[Dict[str, Any]], csv_dir: str, f: Findings) -> None:
    contacts_path = sv2.find_csv(csv_dir, "Contacts.csv")
    fresh_rows = sv2.read_csv_file(contacts_path)
    fresh_by_id = {r.get("Id", ""): r for r in fresh_rows if r.get("Id")}

    checked = 0
    for lead in leads:
        cid = lead.get("external_id")
        if not cid:
            f.error(f"lead {lead.get('id')} has no external_id -- cannot trace back to source CSV")
            continue
        raw = fresh_by_id.get(cid)
        if raw is None:
            f.error(f"lead {lead.get('id')} external_id={cid!r} not found in Contacts.csv")
            continue
        checked += 1

        expected_first = (raw.get("First name") or "").strip() or "Unknown"
        expected_last = (raw.get("Last name") or "").strip() or ""
        if lead.get("first_name") != expected_first:
            f.error(f"external_id={cid}: first_name mismatch staged={lead.get('first_name')!r} csv={expected_first!r}")
        if lead.get("last_name") != expected_last:
            f.error(f"external_id={cid}: last_name mismatch staged={lead.get('last_name')!r} csv={expected_last!r}")

        raw_phone = (raw.get("Mobile") or "").strip() or (raw.get("Work") or "").strip()
        expected_norm = sv2.normalize_phone(raw_phone)
        if lead.get("normalized_phone") != expected_norm:
            f.error(
                f"external_id={cid}: normalized_phone mismatch staged={lead.get('normalized_phone')!r} "
                f"csv={expected_norm!r}"
            )
        if lead.get("normalized_phone") and (
            len(lead["normalized_phone"]) != 10 or not lead["normalized_phone"].isdigit()
        ):
            f.error(f"external_id={cid}: normalized_phone not exactly 10 digits: {lead['normalized_phone']!r}")

        expected_status = (raw.get("Status") or "").strip() or None
        if lead.get("original_fw_status") != expected_status:
            f.error(
                f"external_id={cid}: original_fw_status mismatch staged={lead.get('original_fw_status')!r} "
                f"csv={expected_status!r}"
            )

        # sla_paused contract
        if lead.get("sla_paused") is not True:
            f.error(f"external_id={cid}: sla_paused is not True ({lead.get('sla_paused')!r})")
        if lead.get("import_provenance") != "freshworks":
            f.error(f"external_id={cid}: import_provenance != 'freshworks' ({lead.get('import_provenance')!r})")

        from crm.constants.import_status_map import fw_status_to_canonical

        expected_status, _ = fw_status_to_canonical(lead.get("original_fw_status") or "")
        if lead.get("lead_status") != expected_status:
            f.error(
                f"external_id={cid}: lead_status={lead.get('lead_status')!r} != expected canonical "
                f"{expected_status!r}"
            )

        # original_source / most_recent_source fallback contract
        if not lead.get("original_source") and lead.get("lead_source"):
            f.error(f"external_id={cid}: original_source still empty despite lead_source present")
        if not lead.get("most_recent_source") and lead.get("lead_source"):
            f.error(f"external_id={cid}: most_recent_source still empty despite lead_source present")

        # email sanity
        email = lead.get("email")
        if email and ("@" not in email or " " in email):
            f.error(f"external_id={cid}: malformed email {email!r}")

    print(f"  Field re-derivation: checked {checked}/{len(leads)} leads against Contacts.csv")


# ─── 3. Pydantic schema validation (every lead) ──────────────────────────────

def check_schema(leads: List[Dict[str, Any]], f: Findings) -> None:
    bad = 0
    for lead in leads:
        doc = restore_datetimes(dict(lead))
        try:
            LeadResponse(**doc)
        except Exception as e:  # noqa: BLE001
            bad += 1
            f.error(f"lead {lead.get('id')} (external_id={lead.get('external_id')}) fails LeadResponse validation: {e}")
    print(f"  Pydantic LeadResponse validation: {len(leads) - bad}/{len(leads)} passed")


# ─── 4. context_updates structural + dedupe integrity ───────────────────────

def check_context_updates(leads: List[Dict[str, Any]], f: Findings) -> None:
    over_cap = 0
    bad_entries = 0
    not_fully_deduped = 0
    unsorted = 0

    for lead in leads:
        cu = lead.get("context_updates") or []
        if len(cu) > 50:
            over_cap += 1
            f.error(f"lead {lead.get('id')}: context_updates has {len(cu)} entries (cap is 50)")

        for entry in cu:
            if not entry.get("type") or not entry.get("timestamp") or "description" not in entry:
                bad_entries += 1
                f.error(f"lead {lead.get('id')}: malformed context_updates entry: {entry}")
                continue
            try:
                datetime.fromisoformat(str(entry["timestamp"]).replace("Z", "+00:00"))
            except ValueError:
                bad_entries += 1
                f.error(f"lead {lead.get('id')}: unparseable timestamp {entry.get('timestamp')!r}")

        restored = restore_datetimes({"cu": cu})["cu"]
        deduped = dedupe_context_updates(restored)
        if len(deduped) != len(restored):
            not_fully_deduped += 1
            f.error(
                f"lead {lead.get('id')}: context_updates has {len(restored) - len(deduped)} residual "
                "duplicate(s) after re-running dedupe_context_updates"
            )

        timestamps = [e.get("timestamp") for e in cu]
        if timestamps != sorted(timestamps, reverse=True):
            unsorted += 1
            f.warn(f"lead {lead.get('id')}: context_updates not strictly sorted newest-first")

    print(
        f"  context_updates: {over_cap} over cap, {bad_entries} malformed entries, "
        f"{not_fully_deduped} with residual duplicates, {unsorted} not strictly sorted"
    )


# ─── 5. Join/linkage reconciliation against *_targetables CSVs ─────────────

def check_linkage_coverage(leads: List[Dict[str, Any]], csv_dir: str, f: Findings) -> None:
    by_external_id = {l["external_id"]: l for l in leads if l.get("external_id")}

    def _contacts_with_type(entry_type: str) -> set:
        return {
            l["external_id"]
            for l in leads
            if any(cu.get("type") == entry_type for cu in l.get("context_updates", []))
        }

    # Notes
    note_tgt_path = sv2.find_csv(csv_dir, "Note_targetables.csv")
    notes_path = sv2.find_csv(csv_dir, "Notes.csv")
    if note_tgt_path and notes_path:
        note_ids = {r["Id"] for r in sv2.read_csv_file(notes_path) if r.get("Id")}
        expect_notes = defaultdict(int)
        for r in sv2.read_csv_file(note_tgt_path):
            if (r.get("Related to Type") or "").strip().lower() != "contact":
                continue
            cid = r.get("Related to Id", "")
            nid = r.get("Note Id", "")
            if cid and nid and nid in note_ids and cid in by_external_id:
                expect_notes[cid] += 1
        have_notes = _contacts_with_type("note")
        missing = [cid for cid, cnt in expect_notes.items() if cnt > 0 and cid not in have_notes]
        if missing:
            f.warn(
                f"{len(missing)} contact(s) have linked Notes.csv rows but zero 'note' context_updates "
                f"entries after dedupe (all their notes may have had empty description -- expected in "
                f"some cases, but worth a spot check). Sample: {missing[:5]}"
            )
        print(f"  Notes linkage: {len(expect_notes)} contacts expected to have notes, {len(have_notes)} do")
    else:
        f.warn("Note_targetables.csv or Notes.csv missing -- notes linkage not checked")

    # Sales activities
    sa_path = sv2.find_csv(csv_dir, "Sales_activities.csv")
    sa_tgt_path = sv2.find_csv(csv_dir, "Salesactivity_targetables.csv")
    if sa_path and sa_tgt_path:
        sa_ids = {r["Id"] for r in sv2.read_csv_file(sa_path) if r.get("Id")}
        expect_sa = defaultdict(int)
        for r in sv2.read_csv_file(sa_tgt_path):
            if (r.get("Related to Type") or "").strip().lower() != "contact":
                continue
            cid = r.get("Related to Id", "")
            aid = r.get("SalesActivity Id", "")
            if cid and aid and aid in sa_ids and cid in by_external_id:
                expect_sa[cid] += 1
        have_sa = _contacts_with_type("sales_activity")
        missing = [cid for cid, cnt in expect_sa.items() if cnt > 0 and cid not in have_sa]
        if missing:
            f.warn(
                f"{len(missing)} contact(s) have linked Sales_activities.csv rows but zero "
                f"'sales_activity' context_updates entries (likely all had empty Title). "
                f"Sample: {missing[:5]}"
            )
        print(f"  Sales activity linkage: {len(expect_sa)} contacts expected, {len(have_sa)} have entries")
    else:
        f.warn("Sales_activities.csv or Salesactivity_targetables.csv missing -- not checked")


# ─── 6. Encoding / mojibake scan ─────────────────────────────────────────────

def check_encoding(leads: List[Dict[str, Any]], f: Findings) -> None:
    hits = 0
    text_fields = ("first_name", "last_name", "email", "project", "campaign_name", "presales_description")
    for lead in leads:
        for field in text_fields:
            val = lead.get(field)
            if isinstance(val, str) and any(m in val for m in MOJIBAKE_MARKERS):
                hits += 1
                f.warn(f"lead {lead.get('id')}: possible encoding artifact in {field}: {val!r}")
        for cu in lead.get("context_updates", []):
            desc = cu.get("description")
            if isinstance(desc, str) and any(m in desc for m in MOJIBAKE_MARKERS):
                hits += 1
                f.warn(f"lead {lead.get('id')}: possible encoding artifact in context_updates.description: {desc[:80]!r}")
    print(f"  Encoding scan: {hits} possible mojibake hit(s)")


# ─── 7. Arithmetic reconciliation against extraction_report.json ────────────

def check_arithmetic(leads: List[Dict[str, Any]], report_path: Path, f: Findings) -> None:
    if not report_path.exists():
        f.warn(f"{report_path.name} not found -- skipping arithmetic reconciliation")
        return
    with open(report_path, "r", encoding="utf-8") as fh:
        report = json.load(fh)
    expected = report["contacts_total"] - report["skipped_no_valid_phone"] - report["duplicates_deduped_in_batch"]
    if expected != len(leads):
        f.error(
            f"arithmetic mismatch: contacts_total({report['contacts_total']}) - "
            f"skipped({report['skipped_no_valid_phone']}) - dupes({report['duplicates_deduped_in_batch']}) "
            f"= {expected}, but leads_import.json has {len(leads)}"
        )
    else:
        print(f"  Arithmetic check OK: {report['contacts_total']} contacts - skipped - dupes = {len(leads)}")


# ─── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    # Error/warning messages may echo raw customer names/notes containing non-ASCII text;
    # Windows consoles default to cp1252, which would crash mid-report. Force UTF-8 output.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=str(DEFAULT_INPUT))
    ap.add_argument("--csv-dir", default=DEFAULT_CSV_DIR)
    args = ap.parse_args()

    input_path = Path(args.input)
    print("\n" + "=" * 72)
    print("  validate_staged_data.py -- 100% coverage audit (no DB access)")
    print("=" * 72)
    print(f"  Input: {input_path}\n")

    leads = load_staged(input_path)
    print(f"  Loaded {len(leads):,} staged leads\n")

    f = Findings()

    print("--- Uniqueness invariants ---")
    check_uniqueness(leads, f)

    print("\n--- Field-level re-derivation (100% of leads, not sampled) ---")
    check_field_derivation(leads, args.csv_dir, f)

    print("\n--- Pydantic schema validation ---")
    check_schema(leads, f)

    print("\n--- context_updates structural checks ---")
    check_context_updates(leads, f)

    print("\n--- Join/linkage coverage vs *_targetables CSVs ---")
    check_linkage_coverage(leads, args.csv_dir, f)

    print("\n--- Encoding scan ---")
    check_encoding(leads, f)

    print("\n--- Arithmetic reconciliation ---")
    check_arithmetic(leads, input_path.parent / "extraction_report.json", f)

    print("\n" + "=" * 72)
    print(f"  RESULT: {len(f.errors)} error(s), {len(f.warnings)} warning(s)")
    print("=" * 72)

    if f.warnings:
        print("\nWarnings:")
        for w in f.warnings[:50]:
            print(f"  [WARN] {w}")
        if len(f.warnings) > 50:
            print(f"  ... and {len(f.warnings) - 50} more")

    if f.errors:
        print("\nErrors:")
        for e in f.errors[:50]:
            print(f"  [ERROR] {e}")
        if len(f.errors) > 50:
            print(f"  ... and {len(f.errors) - 50} more")
        sys.exit(1)

    print("\n  [OK] Zero errors across full dataset.\n")


if __name__ == "__main__":
    main()
