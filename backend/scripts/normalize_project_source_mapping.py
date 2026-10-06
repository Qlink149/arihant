#!/usr/bin/env python3
"""
normalize_project_source_mapping.py
====================================
Client-approved cleanup of the free-text `project` and `lead_source` /
`original_source` / `most_recent_source` / `channel_partner` fields on `leads`.

Source of truth: "Projects & Source list - Arihant (1).xlsx" (3 sheets):
  - Projects: 44 raw project-name variants (case/spacing/spelling drift, short
    forms, a few outright renames) -> one canonical project name.
  - Source: 104 raw lead_source strings -> one canonical source name. Channel
    Partner leads additionally carry a sub-source (the specific partner).
  - Subsource - ChannelPartner list: the authoritative ~39-name whitelist for
    that sub-source.

Why a separate script, not a hand-edit: the `project` field is often a
`; `-joined (and sometimes, buggily, `, `-joined) multi-value string, and the
`channel_partner` field is currently 100% unpopulated across all leads even
though ~3,270 leads have a specific channel-partner name sitting directly in
`lead_source` (e.g. "propmart", "Home Konnect") instead. Both need careful,
token-level remapping, not a blind string replace.

Safety
------
  - Dry-run by default; --apply required to write.
  - Backs up every matched document in full before writing.
  - Only touches project/projects/lead_source/original_source/
    most_recent_source/channel_partner. Never touches lead_status,
    sla_paused, assignment, context_updates, tasks or timestamps.
  - project_id/project_ids are left untouched (they're resolved separately by
    crm.core.state token-matching, which already tolerates these name forms).
  - Any raw value with no entry in the mapping tables is left unchanged and
    reported under "unmapped" for manual follow-up -- never guessed.

Usage:
  python backend/scripts/normalize_project_source_mapping.py
  python backend/scripts/normalize_project_source_mapping.py --apply
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
for p in (str(BACKEND_DIR), str(SCRIPT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)
load_dotenv(BACKEND_DIR / ".env")

# Mapping tables + normalization logic live in crm/services/lead_field_normalize.py
# (single source of truth), shared with the live lead-creation paths that also
# canonicalize these fields as new leads come in.
from crm.services.lead_field_normalize import (  # noqa: E402
    CP_SUBSOURCE_MAP,
    PROJECT_MAP,
    SOURCE_MAP,
    _norm_key,
    remap_projects_from_values,
    remap_source_field as _remap_source_field,
    resolve_channel_partner,
    split_project_tokens,
)


def remap_projects(doc: dict) -> Tuple[Optional[str], Optional[List[str]], List[str]]:
    """Returns (new_project_str, new_projects_list, unmapped_raw_tokens)."""
    raw_tokens: List[str] = []
    raw_tokens += split_project_tokens(doc.get("project"))
    for item in doc.get("projects") or []:
        raw_tokens += split_project_tokens(item)

    unmapped = [t for t in raw_tokens if _norm_key(t) not in PROJECT_MAP]
    new_project, new_projects = remap_projects_from_values(doc.get("project"), doc.get("projects"))
    return new_project, new_projects, unmapped


def build_update(doc: dict) -> Tuple[Dict, Dict, List[str]]:
    """Returns (setter_dict, before_dict_for_display, unmapped_values)."""
    setter: Dict = {}
    before: Dict = {}
    unmapped: List[str] = []

    new_project, new_projects, unmapped_projects = remap_projects(doc)
    unmapped += [f"project:{t}" for t in unmapped_projects]
    if new_project is not None and new_project != (doc.get("project") or ""):
        before["project"] = doc.get("project")
        setter["project"] = new_project
    if new_projects is not None and new_projects != (doc.get("projects") or []):
        before["projects"] = doc.get("projects")
        setter["projects"] = new_projects

    raw_lead_source = doc.get("lead_source")
    for field in ("lead_source", "original_source", "most_recent_source"):
        raw = doc.get(field)
        new_val = _remap_source_field(raw)
        if raw and new_val == raw and _norm_key(raw) not in SOURCE_MAP:
            unmapped.append(f"{field}:{raw}")
        if new_val != raw:
            before[field] = raw
            setter[field] = new_val

    # Guard: never re-derive once channel_partner is already set. Needed for
    # idempotency -- after a first pass, lead_source becomes the literal string
    # "Channel Partner", which casefolds to the same key as the sheet's own
    # generic "channel partner" raw bucket (-> "Others"). Re-deriving from the
    # now-canonical lead_source on a second run would silently downgrade a
    # specific partner name (e.g. "PropLeaf") back to the generic "Others".
    if not doc.get("channel_partner"):
        new_cp = resolve_channel_partner(raw_lead_source)
        if new_cp:
            before["channel_partner"] = doc.get("channel_partner")
            setter["channel_partner"] = new_cp

    return setter, before, unmapped


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry-run preview)")
    ap.add_argument("--limit-report", type=int, default=25, help="Max distinct correction rows to print per field")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL", "")
    db_name = os.environ.get("DB_NAME", "")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env", file=sys.stderr)
        sys.exit(1)

    client = MongoClient(mongo_url)
    db = client[db_name]
    leads = db.leads

    mode = "APPLY" if args.apply else "DRY-RUN"
    print("=" * 72)
    print(f"  normalize_project_source_mapping.py  [{mode}]  DB={db_name}")
    print("=" * 72)

    cursor = leads.find(
        {},
        {
            "id": 1,
            "project": 1,
            "projects": 1,
            "lead_source": 1,
            "original_source": 1,
            "most_recent_source": 1,
            "channel_partner": 1,
        },
    )

    total = 0
    to_fix: List[Tuple[dict, Dict]] = []
    field_diffs: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    unmapped_counter: collections.Counter = collections.Counter()

    for doc in cursor:
        total += 1
        setter, before, unmapped = build_update(doc)
        for u in unmapped:
            unmapped_counter[u] += 1
        if setter:
            to_fix.append((doc, setter))
            for field, old_val in before.items():
                field_diffs[field][(str(old_val), str(setter.get(field)))] += 1

    print(f"\n  Leads scanned            : {total}")
    print(f"  Leads needing a fix      : {len(to_fix)}")

    for field in ("project", "projects", "lead_source", "original_source", "most_recent_source", "channel_partner"):
        counter = field_diffs.get(field)
        if not counter:
            continue
        print(f"\n  --- {field} ({sum(counter.values())} leads, {len(counter)} distinct changes) ---")
        for (old, new), n in counter.most_common(args.limit_report):
            print(f"    {n:>5}  {old!r}  ->  {new!r}")
        if len(counter) > args.limit_report:
            print(f"    ... ({len(counter) - args.limit_report} more distinct changes not shown)")

    if unmapped_counter:
        print(f"\n  --- UNMAPPED raw values (left unchanged, {sum(unmapped_counter.values())} occurrences) ---")
        for val, n in unmapped_counter.most_common(40):
            print(f"    {n:>5}  {val!r}")

    if not to_fix:
        print("\n  Nothing to do.")
        client.close()
        return

    if not args.apply:
        print("\n  DRY-RUN -- no changes written. Re-run with --apply.")
        client.close()
        return

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = SCRIPT_DIR / "static_data"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"pre_project_source_normalize_backup_{run_id}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump([d for d, _ in to_fix], f, indent=2, default=str, ensure_ascii=False)
    print(f"\n  [OK] backed up {len(to_fix)} full documents -> {backup_path.name}")

    ops = [UpdateOne({"id": d["id"]}, {"$set": setter}) for d, setter in to_fix]
    result = leads.bulk_write(ops, ordered=False)
    print(f"  [OK] matched {result.matched_count}, modified {result.modified_count}")
    print("\n  Only project/source/channel_partner fields were changed. lead_status,")
    print("  sla_paused, assignment, context_updates and tasks were NOT touched.")
    client.close()


if __name__ == "__main__":
    main()
