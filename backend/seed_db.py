#!/usr/bin/env python3
"""
seed_db.py — Freshworks CRM CSV → MongoDB Seed Script
=====================================================
Maps Freshworks CSV exports to the backend schema for the Rustomjee dashboard.

Collections seeded:
  • leads            – Contact records with business classification
  • users            – Sales team with Bcrypt passwords
  • marketing_spends – Channel-wise spend data per project
  • settings         – Reminder rules, API keys, project configs

Usage:
  python seed_db.py                     # full seed (drops existing data)
  python seed_db.py --dry-run           # parse + validate, no DB writes
  python seed_db.py --csv-dir ./data    # custom CSV path

Requirements:
  pip install pymongo bcrypt
"""

import csv
import os
import re
import sys
import uuid
import json
import argparse
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ─── Dependency Check ────────────────────────────────────────────────────────

try:
    from pymongo import MongoClient
    import bcrypt
except ImportError as e:
    print(f"\n  ✗ Missing dependency: {e.name}")
    print("    Install with:  pip install pymongo bcrypt\n")
    sys.exit(1)

# ─── Configuration ───────────────────────────────────────────────────────────

MONGO_URI = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "arihant_crm")
DEFAULT_CSV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "csv")
BATCH_SIZE = 1000
DEFAULT_PASSWORD = "Arihant@2026"

# Deterministic UUID namespace — re-runs produce identical IDs
NS = uuid.UUID("b7e49a1c-3f8d-4e2a-9c1b-0d5f6e7a8b9c")


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 1: CONSTANTS & ENUM MAPPINGS
# ═══════════════════════════════════════════════════════════════════════════════

VALID_PROJECTS = [
    "ECR - Reserve 16", "Saligramam Melange", "OMR - Vivriti",
    "Abhiramapuram - Krishna", "Flowers Road - Kilpauk",
]
VALID_BUDGETS = ["Under 1Cr", "1-2 Cr", "2-5 Cr", "Above 2Cr", "5 Cr+"]
VALID_LOCATIONS = ["ECR", "Abhiramapuram", "OMR", "Saligramam", "Kilpauk"]
VALID_STATUSES = ["Open", "Contacted", "Follow Up", "Site Visit", "Lost", "Won"]
VALID_SOURCES = [
    "Facebook Lead Form", "facebook_ad", "google", "website", "instagram",
    "whatsapp", "newspaper", "direct-walkin", "propmart",
    "management reference", "CREDAI FAIRPRO 2026",
]
VALID_TEMPERATURES = ["Hot", "Warm", "Cold"]
VALID_PIPELINE_CATS = ["Qualified", "VIP Pipeline", "Hot", "Cold", "Dormant"]

PROJECT_TO_LOCATION = {
    "ECR - Reserve 16": "ECR",
    "Saligramam Melange": "Saligramam",
    "OMR - Vivriti": "OMR",
    "Abhiramapuram - Krishna": "Abhiramapuram",
    "Flowers Road - Kilpauk": "Kilpauk",
}

PROJECT_BUDGET_WEIGHTS = {
    "ECR - Reserve 16":        ["1-2 Cr", "2-5 Cr", "2-5 Cr", "1-2 Cr"],
    "Saligramam Melange":      ["Under 1Cr", "1-2 Cr", "1-2 Cr", "Under 1Cr"],
    "OMR - Vivriti":           ["Under 1Cr", "1-2 Cr", "1-2 Cr"],
    "Abhiramapuram - Krishna": ["2-5 Cr", "5 Cr+", "5 Cr+", "2-5 Cr"],
    "Flowers Road - Kilpauk":  ["1-2 Cr", "1-2 Cr", "Under 1Cr"],
}

PROJECT_CLEAN_MAP = {
    "ECR - Reserve 16": "ECR - Reserve 16", "Reserve 16": "ECR - Reserve 16",
    "ECR": "ECR - Reserve 16",
    "Saligramam Melange": "Saligramam Melange", "Melange": "Saligramam Melange",
    "Saligramam": "Saligramam Melange",
    "OMR - Vivriti": "OMR - Vivriti", "Vivriti": "OMR - Vivriti",
    "OMR": "OMR - Vivriti",
    "Abhiramapuram - Krishna": "Abhiramapuram - Krishna",
    "Krishna": "Abhiramapuram - Krishna", "Abhiramapuram": "Abhiramapuram - Krishna",
    "Flowers Road - Kilpauk": "Flowers Road - Kilpauk",
    "Kilpauk": "Flowers Road - Kilpauk",
    # Legacy Freshworks projects → nearest active project
    "Srinagar Colony - Vipassana": "Saligramam Melange",
    "Vipassana": "Saligramam Melange",
    "Bangalore - Vilaya": None, "Vilaya": None,
    "Villa Viviana Plots": "ECR - Reserve 16",
    "Vinyasa": "Saligramam Melange",
    "Hunters Road - Vanya Vilas": "Flowers Road - Kilpauk",
    "Vanya Vilas": "Flowers Road - Kilpauk",
    "vihaana": "OMR - Vivriti",
    "Sri Niketan": "Saligramam Melange",
    "Poes Garden - Chirla": "Abhiramapuram - Krishna",
    "Sri Nivas": "Saligramam Melange",
    "Others": None, "NA": None,
}

STATUS_MAP = {
    "New": "Open", "Contacted": "Contacted",
    "Follow Up 1": "Follow Up", "Follow Up 2": "Follow Up",
    "Interested": "Follow Up", "Negotiation": "Follow Up",
    "Site Visit Scheduled": "Site Visit", "Site Visit Completed": "Site Visit",
    "Office Visit Completed": "Site Visit",
    "Advance Paid": "Won", "Awaiting Completion": "Won",
    "Unqualified": "Lost", "Junk": "Lost", "Gone Cold": "Lost",
    "Dropped": "Lost", "Churned": "Lost", "Rental": "Lost", "Occupied": "Lost",
    "RNR 1": "Open", "RNR 2": "Open",
    "Project Unavailability - Future prospect": "Lost",
    "Future Prospect - Bangalore": "Lost",
}

SOURCE_MAP = {
    "facebook_ad": "facebook_ad", "Facebook Lead Form": "Facebook Lead Form",
    "Facebook Lead Ads": "Facebook Lead Form",
    "google": "google", "Google": "google",
    "website": "website", "Website": "website", "Web Form": "website",
    "whatsapp": "whatsapp", "Chat": "whatsapp", "WATI Campaign": "whatsapp",
    "newspaper": "newspaper",
    "mcube": "direct-walkin", "Direct": "direct-walkin",
    "channel partner": "management reference",
    "Home Konnect": "management reference", "Aurum Analytica": "management reference",
    "propmart": "propmart", "Propmart": "propmart",
    "instagram": "instagram", "Instagram": "instagram",
    "CREDAI FAIRPRO 2026": "CREDAI FAIRPRO 2026",
    "Credai Fairpro 2025": "CREDAI FAIRPRO 2026",
    "Existing Customer": "management reference", "Referral": "management reference",
}

OWNER_NAME_MAP = {
    "Narendran S": "Narendran S", "Piyush .": "Piyush", "Malathy .": "Malathy",
    "Anusha Omprakash": "Anusha Omprakash", "jigar .": "jigar",
    "shariff .": "shariff", "Roshni Madhav": "Roshini",
    "Harish Marlecha": "Narendran S", "Akshata LB": "Malathy", "Gowtham j": "jigar",
}

TEMPERATURE_MAP = {
    "Follow Up": "Hot", "Site Visit": "Hot", "Won": "Hot",
    "Contacted": "Warm", "Open": "Warm", "Lost": "Cold",
}

USER_DEFS = [
    {"name": "Narendran S",      "email": "narendran@arihants.co.in",  "role": "rep"},
    {"name": "Piyush",           "email": "piyush@arihants.co.in",     "role": "rep"},
    {"name": "Malathy",          "email": "malathy@arihants.co.in",    "role": "rep"},
    {"name": "Anusha Omprakash", "email": "anusha@arihants.co.in",     "role": "rep"},
    {"name": "jigar",            "email": "jigar@arihants.co.in",      "role": "rep"},
    {"name": "shariff",          "email": "shariff@arihants.co.in",    "role": "rep"},
    {"name": "Roshini",          "email": "roshini@rustomjee.com",     "role": "admin"},
]


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 2: HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def det_uuid(seed: str) -> str:
    return str(uuid.uuid5(NS, seed))

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def parse_date(val: str) -> Optional[str]:
    if not val or not val.strip():
        return None
    try:
        dt = datetime.strptime(val.strip().replace(" UTC", ""), "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, AttributeError):
        return None

def normalize_phone(raw: str) -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw.replace("'", ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None

def clean_phone(raw: str) -> Optional[str]:
    if not raw or not raw.strip():
        return None
    return raw.strip().replace("'", "").strip() or None

def hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()

def find_csv(directory: str, name: str) -> Optional[str]:
    d = Path(directory)
    if not d.exists():
        return None
    lo = name.lower()
    for f in d.iterdir():
        fl = f.name.lower()
        if fl == lo or fl.endswith("_" + lo) or fl.endswith("-" + lo):
            return str(f)
    return None

def read_csv_file(filepath: str) -> list[dict]:
    rows = []
    with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip(): v.strip() for k, v in row.items() if k and k.strip()})
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 3: BUDGET PARSER
# ═══════════════════════════════════════════════════════════════════════════════

BUDGET_JUNK = {
    "within_a_week", "this_month", "yes", "no", "maybe", "na", "n/a", "nil",
    "confirm_on_call", "ok", "open", "0", "-", "..", "hi", "chennai",
    "tamilnadu", "bihar", "assam", "india", "odisha", "nepal",
}

def parse_budget_to_crores(raw: str) -> Optional[float]:
    if not raw:
        return None
    text = raw.lower().strip().replace("_", " ").replace(",", "")
    if text in BUDGET_JUNK or len(text) < 2:
        return None
    if re.match(r"^[a-z]{4,}$", text) and text not in ("crore", "crores", "lakhs"):
        return None

    # "X cr" / "X crore" / "X crs" / "Xc"
    m = re.search(r"(\d+\.?\d*)\s*(?:cr(?:ore|s)?|c)\b", text)
    if m:
        return float(m.group(1))

    # "X lakh" / "X lac" / "XL"
    m = re.search(r"(\d+\.?\d*)\s*(?:lakh?s?|lacs?|l)\b", text)
    if m:
        return float(m.group(1)) / 100.0

    # Range in crores: "1-2 Cr", "1 to 2 crore"
    m = re.search(r"(\d+\.?\d*)\s*(?:to|-)\s*(\d+\.?\d*)\s*(?:cr|crore|c)\b", text)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2.0

    # Range in lakhs
    m = re.search(r"(\d+\.?\d*)\s*(?:to|-)\s*(\d+\.?\d*)\s*(?:lakh?s?|lacs?|l)\b", text)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 200.0

    # Bare number (rupees)
    m = re.match(r"^[\d.]+$", text)
    if m:
        try:
            val = float(text)
            if val >= 10_000_000:
                return val / 10_000_000
            elif val >= 100_000:
                return val / 10_000_000
        except ValueError:
            pass

    return None

def classify_budget(crores: Optional[float]) -> Optional[str]:
    if crores is None:
        return None
    if crores < 1:
        return "Under 1Cr"
    elif crores < 2:
        return "1-2 Cr"
    elif crores < 5:
        return "2-5 Cr"
    else:
        return "5 Cr+"

def simulate_budget(project: Optional[str]) -> str:
    if project and project in PROJECT_BUDGET_WEIGHTS:
        return random.choice(PROJECT_BUDGET_WEIGHTS[project])
    return random.choice(["Under 1Cr", "Under 1Cr", "1-2 Cr", "1-2 Cr", "2-5 Cr"])


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 4: PROJECT & SOURCE CLEANERS
# ═══════════════════════════════════════════════════════════════════════════════

def clean_project(raw: str) -> Optional[str]:
    if not raw or not raw.strip():
        return None
    parts = [p.strip() for p in raw.split(";") if p.strip() and p.strip() != "NA"]
    if not parts:
        return None
    for part in parts:
        if part in PROJECT_CLEAN_MAP:
            mapped = PROJECT_CLEAN_MAP[part]
            if mapped and mapped in VALID_PROJECTS:
                return mapped
    for part in parts:
        pl = part.lower()
        for vp in VALID_PROJECTS:
            if vp.lower() in pl or pl in vp.lower():
                return vp
    return None

def clean_source(raw: str, orig: str = "", recent: str = "") -> str:
    for candidate in [raw, orig, recent]:
        candidate = (candidate or "").strip()
        if not candidate:
            continue
        if candidate in SOURCE_MAP:
            return SOURCE_MAP[candidate]
        cl = candidate.lower()
        if "facebook" in cl:    return "facebook_ad"
        if "google" in cl:      return "google"
        if "instagram" in cl:   return "instagram"
        if "whatsapp" in cl or "chat" in cl: return "whatsapp"
        if "newspaper" in cl:   return "newspaper"
        if "walk" in cl or "direct" in cl or "mcube" in cl: return "direct-walkin"
        if "credai" in cl:      return "CREDAI FAIRPRO 2026"
        if "propmart" in cl:    return "propmart"
        if "referral" in cl or "reference" in cl or "partner" in cl: return "management reference"
        if "website" in cl or "web" in cl: return "website"
    return "google"

def derive_location(project: Optional[str], loc_interested: str = "") -> Optional[str]:
    if project and project in PROJECT_TO_LOCATION:
        return PROJECT_TO_LOCATION[project]
    if loc_interested:
        loc_clean = loc_interested.replace(";", " ").lower()
        for vl in VALID_LOCATIONS:
            if vl.lower() in loc_clean:
                return vl
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 5: BUSINESS CLASSIFICATION LOGIC
# ═══════════════════════════════════════════════════════════════════════════════

def check_area_match(project: Optional[str], location: Optional[str]) -> bool:
    if not project or not location:
        return False
    return PROJECT_TO_LOCATION.get(project) == location

def check_timeline_short(created_at: Optional[str], last_activity: Optional[str], status: str) -> bool:
    now = datetime.now(timezone.utc)
    six_m = now - timedelta(days=180)
    three_m = now - timedelta(days=90)
    if created_at:
        try:
            if datetime.fromisoformat(created_at) > six_m:
                return True
        except (ValueError, TypeError):
            pass
    if last_activity:
        try:
            if datetime.fromisoformat(last_activity) > three_m:
                return True
        except (ValueError, TypeError):
            pass
    return status in ("Site Visit", "Follow Up", "Won")

BUDGET_TO_CRORES = {
    "Under 1Cr": 0.5, "1-2 Cr": 1.5, "2-5 Cr": 3.5, "Above 2Cr": 3.0, "5 Cr+": 7.0,
}

def classify_pipeline(budget_label: Optional[str], timeline_short: bool, area_match: bool) -> str:
    """
    Qualified    : Budget >= 2Cr AND Timeline < 6m AND Area Match
    VIP Pipeline : Budget >= 2Cr AND Area Match
    Hot          : Budget >= 2Cr
    Cold         : (Area Match OR Timeline < 6m) AND Budget < 2Cr
    Dormant      : No match
    """
    crores = BUDGET_TO_CRORES.get(budget_label or "", 0)
    high_budget = crores >= 2.0

    if high_budget and timeline_short and area_match:
        return "Qualified"
    if high_budget and area_match:
        return "VIP Pipeline"
    if high_budget:
        return "Hot"
    if (area_match or timeline_short) and not high_budget:
        return "Cold"
    return "Dormant"


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 6: LEAD TRANSFORMER
# ═══════════════════════════════════════════════════════════════════════════════

def transform_lead(row, name_to_uuid, ctx_notes, ctx_calls, ctx_tasks):
    # ── Phone ────────────────────────────────────────────────────────────
    raw_phone = row.get("Mobile") or row.get("Work") or ""
    phone = clean_phone(raw_phone)
    normalized = normalize_phone(raw_phone)
    if not normalized:
        return None

    # ── Core fields ──────────────────────────────────────────────────────
    first = row.get("First name", "").strip() or "Unknown"
    last = row.get("Last name", "").strip() or ""
    email_raw = row.get("Emails", "").strip()
    email = email_raw.split(";")[0].strip() if email_raw else None
    if not email:
        email = row.get("Work email", "").strip() or None

    project = clean_project(row.get("Project", ""))

    # ── Budget ───────────────────────────────────────────────────────────
    budget_crores = parse_budget_to_crores(row.get("Budget", ""))
    budget = classify_budget(budget_crores)
    if not budget:
        budget = simulate_budget(project)

    location = derive_location(project, row.get("Location Interested", ""))

    # ── Status, Source, Assignment ────────────────────────────────────────
    fw_status = row.get("Status", "").strip()
    lead_status = STATUS_MAP.get(fw_status, "Open")
    lead_source = clean_source(
        row.get("Source", ""), row.get("Original source", ""),
        row.get("Most recent source", ""),
    )

    fw_owner = row.get("Sales owner", "").strip()
    assigned_name = OWNER_NAME_MAP.get(fw_owner)
    if not assigned_name:
        reps = [u["name"] for u in USER_DEFS if u["role"] == "rep"]
        assigned_name = reps[hash(normalized) % len(reps)]
    assigned_uid = name_to_uuid.get(assigned_name, name_to_uuid["Narendran S"])

    temperature = TEMPERATURE_MAP.get(lead_status, "Warm")

    # ── Timestamps ───────────────────────────────────────────────────────
    created_at = parse_date(row.get("Created at", "")) or now_iso()
    updated_at = parse_date(row.get("Updated at", "")) or created_at
    last_activity = parse_date(row.get("Last activity date", ""))

    # ── Pipeline Category ────────────────────────────────────────────────
    area_match = check_area_match(project, location)
    timeline_short = check_timeline_short(created_at, last_activity, lead_status)
    pipeline_cat = classify_pipeline(budget, timeline_short, area_match)

    # ── VIP ──────────────────────────────────────────────────────────────
    tags = (row.get("Tags", "") or "").lower()
    vip = pipeline_cat == "VIP Pipeline" or "vip" in tags or "hni" in tags
    if vip and pipeline_cat not in ("VIP Pipeline", "Qualified"):
        pipeline_cat = "VIP Pipeline"

    # ── Context Updates ──────────────────────────────────────────────────
    context_updates = []
    for n in ctx_notes:
        desc = n.get("Description", "").strip()
        if desc:
            entry = {
                "type": "note",
                "description": desc[:500],
                "timestamp": parse_date(n.get("Created at", "")) or created_at,
            }
            if n.get("Id"):
                entry["note_id"] = str(n.get("Id")).strip()
            context_updates.append(entry)
    for c in ctx_calls:
        outcome = c.get("Outcome", "").strip()
        notes = c.get("Notes", "").strip()
        desc = f"{outcome}: {notes}" if notes else outcome
        if desc:
            context_updates.append({
                "type": "call", "description": desc[:500],
                "timestamp": parse_date(c.get("Created at", "")) or created_at,
            })
    for t in ctx_tasks:
        title = t.get("Title", "").strip()
        ttype = t.get("Task type", "").strip()
        desc = f"[{ttype}] {title}" if ttype else title
        if desc:
            context_updates.append({
                "type": "task", "description": desc[:500],
                "timestamp": parse_date(t.get("Created at", "")) or created_at,
            })

    from crm.services.context_updates import dedupe_context_updates

    context_updates = dedupe_context_updates(context_updates)
    context_updates.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    context_updates = context_updates[:20]

    if not context_updates:
        rn = (row.get("Recent note") or "").strip()
        if rn:
            context_updates.append({"type": "note", "description": rn[:500], "timestamp": updated_at})

    # ── Final Document ───────────────────────────────────────────────────
    return {
        "id": det_uuid(f"lead:{row.get('Id', normalized)}"),
        "first_name": first,
        "last_name": last,
        "phone": phone,
        "normalized_phone": normalized,
        "email": email,
        "project": project,
        "budget": budget,
        "location": location,
        "lead_status": lead_status,
        "lead_source": lead_source,
        "assigned_user_id": assigned_uid,
        "assigned_to_name": assigned_name,
        "temperature": temperature,
        "pipeline_category": pipeline_cat,
        "vip": vip,
        "context_updates": context_updates,
        "created_at": created_at,
        "updated_at": updated_at,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 7: MARKETING SPENDS & SETTINGS SEED DATA
# ═══════════════════════════════════════════════════════════════════════════════

def build_marketing_spends():
    return [
        {"id": det_uuid("mkt:r16:meta"), "project": "ECR - Reserve 16",
         "channel": "Meta Ads (Facebook/Instagram)", "amount": 35000.0,
         "leads_generated": 7, "conversions": 2, "period": "2026-Q1",
         "campaign_name": "Reserve 16 - Meta Lead Gen Q1",
         "impressions": 125000, "clicks": 3200,
         "notes": "Facebook+Instagram campaigns for ECR Reserve 16", "created_at": now_iso()},
        {"id": det_uuid("mkt:r16:news"), "project": "ECR - Reserve 16",
         "channel": "Newspaper / Print", "amount": 15000.0,
         "leads_generated": 3, "conversions": 1, "period": "2026-Q1",
         "campaign_name": "Reserve 16 - Hindu Prop Plus Q1",
         "impressions": None, "clicks": None,
         "notes": "Print ads in The Hindu Property Plus", "created_at": now_iso()},
        {"id": det_uuid("mkt:mel:meta"), "project": "Saligramam Melange",
         "channel": "Meta Ads (Facebook/Instagram)", "amount": 175000.0,
         "leads_generated": 6, "conversions": 4, "period": "2026-Q1",
         "campaign_name": "Melange - Meta Lead Gen Q1",
         "impressions": 210000, "clicks": 5100,
         "notes": "High-budget Meta campaign for Melange launch", "created_at": now_iso()},
        {"id": det_uuid("mkt:mel:news"), "project": "Saligramam Melange",
         "channel": "Newspaper / Print", "amount": 25000.0,
         "leads_generated": 2, "conversions": 1, "period": "2026-Q1",
         "campaign_name": "Melange - Print Campaign Q1",
         "impressions": None, "clicks": None,
         "notes": "Print ads for Saligramam Melange", "created_at": now_iso()},
    ]

def build_settings():
    return {
        "id": det_uuid("settings:global"),
        "reminder_rules": {
            "followup_due": {"enabled": True, "threshold_days": 2, "channels": ["whatsapp", "in_app"]},
            "site_visit_tomorrow": {"enabled": True, "channels": ["whatsapp", "in_app"]},
            "rnr_stale": {"enabled": True, "threshold_days": 3, "channels": ["in_app"]},
            "task_overdue": {"enabled": True, "channels": ["whatsapp", "in_app"]},
            "cold_lead_reactivation": {"enabled": True, "threshold_days": 7, "channels": ["in_app"]},
            "dormant_lead_alert": {"enabled": True, "threshold_days": 7, "channels": ["in_app"]},
        },
        "api_keys": {"freshworks": None, "whatsapp_wati": None, "meta_ads": None},
        "project_configs": {
            p: {"name": p, "location": PROJECT_TO_LOCATION[p], "active": True}
            for p in VALID_PROJECTS
        },
        "notification_channels": {"email": True, "whatsapp": False, "push": False},
        "auto_assignment_rules": [{"name": "Round Robin", "type": "round_robin", "enabled": True}],
        "created_at": now_iso(), "updated_at": now_iso(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 8: SUMMARY PRINTER
# ═══════════════════════════════════════════════════════════════════════════════

def print_summary(leads, users):
    total = len(leads) or 1

    print("\n" + "═" * 65)
    print("  SEED SUMMARY")
    print("═" * 65)

    # Pipeline Category
    pc = {}
    for cat in VALID_PIPELINE_CATS:
        pc[cat] = 0
    for l in leads:
        pc[l["pipeline_category"]] = pc.get(l["pipeline_category"], 0) + 1

    print("\n  ┌────────────────────┬──────────┬────────┐")
    print("  │ Pipeline Category  │  Count   │   %    │")
    print("  ├────────────────────┼──────────┼────────┤")
    for cat in VALID_PIPELINE_CATS:
        c = pc.get(cat, 0)
        print(f"  │ {cat:<18} │ {c:>8,} │ {c*100/total:>5.1f}% │")
    print("  ├────────────────────┼──────────┼────────┤")
    print(f"  │ {'TOTAL':<18} │ {total:>8,} │ 100.0% │")
    print("  └────────────────────┴──────────┴────────┘")

    # Temperature
    tc = {}
    for l in leads:
        tc[l["temperature"]] = tc.get(l["temperature"], 0) + 1
    print("\n  ┌────────────────────┬──────────┐")
    print("  │ Temperature        │  Count   │")
    print("  ├────────────────────┼──────────┤")
    for t in VALID_TEMPERATURES:
        print(f"  │ {t:<18} │ {tc.get(t,0):>8,} │")
    print("  └────────────────────┴──────────┘")

    # Per Manager
    mc = {}
    for l in leads:
        mc[l["assigned_to_name"]] = mc.get(l["assigned_to_name"], 0) + 1
    print("\n  ┌──────────────────────┬──────────┐")
    print("  │ Assigned To          │  Leads   │")
    print("  ├──────────────────────┼──────────┤")
    for name, count in sorted(mc.items(), key=lambda x: -x[1]):
        print(f"  │ {name:<20} │ {count:>8,} │")
    print("  └──────────────────────┴──────────┘")

    # Per Project
    prc = {}
    for l in leads:
        prc[l["project"] or "Unassigned"] = prc.get(l["project"] or "Unassigned", 0) + 1
    print("\n  ┌──────────────────────────────┬──────────┐")
    print("  │ Project                      │  Leads   │")
    print("  ├──────────────────────────────┼──────────┤")
    for p, c in sorted(prc.items(), key=lambda x: -x[1])[:8]:
        print(f"  │ {p:<28} │ {c:>8,} │")
    print("  └──────────────────────────────┴──────────┘")

    # Collections
    print("\n  ┌──────────────────────┬──────────┐")
    print("  │ Collection           │  Docs    │")
    print("  ├──────────────────────┼──────────┤")
    print(f"  │ {'leads':<20} │ {len(leads):>8,} │")
    print(f"  │ {'users':<20} │ {len(users):>8,} │")
    print(f"  │ {'marketing_spends':<20} │ {4:>8} │")
    print(f"  │ {'settings':<20} │ {1:>8} │")
    print("  └──────────────────────┴──────────┘\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 9: MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Seed Freshworks CRM data into MongoDB")
    ap.add_argument("--csv-dir", default=DEFAULT_CSV_DIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mongo-uri", default=MONGO_URI)
    ap.add_argument("--db-name", default=DB_NAME)
    args = ap.parse_args()

    print("\n╔══════════════════════════════════════════════════════════════════╗")
    print("║    seed_db.py — Freshworks CRM → MongoDB                       ║")
    print("║    Rustomjee Dashboard · FastAPI Backend                        ║")
    print("╚══════════════════════════════════════════════════════════════════╝\n")
    print(f"  MongoDB  : {args.mongo_uri}")
    print(f"  Database : {args.db_name}")
    print(f"  CSV Dir  : {args.csv_dir}")
    print(f"  Dry Run  : {args.dry_run}\n")

    # ── Locate files ─────────────────────────────────────────────────────
    print("─── Step 1: Locating CSV files ───\n")
    FILES = {
        "contacts":     ("Contacts.csv",                True),
        "notes":        ("Notes.csv",                    False),
        "note_tgt":     ("Note_targetables.csv",         False),
        "tasks":        ("Tasks.csv",                    False),
        "task_tgt":     ("Task_targetables.csv",         False),
        "calls":        ("Call_logs.csv",                 False),
        "emails":       ("Contact_emails.csv",           False),
    }
    paths = {}
    for key, (fname, req) in FILES.items():
        fp = find_csv(args.csv_dir, fname)
        paths[key] = fp
        if fp:       print(f"  ✓  {fname:<38} found")
        elif req:    print(f"  ✗  {fname:<38} MISSING"); sys.exit(1)
        else:        print(f"  ○  {fname:<38} skipped")

    # ── Build users ──────────────────────────────────────────────────────
    print("\n─── Step 2: Building users ───\n")
    pwd_hash = hash_pw(DEFAULT_PASSWORD)
    name_to_uuid = {}
    users = []
    for ud in USER_DEFS:
        uid = det_uuid(f"user:{ud['email']}")
        name_to_uuid[ud["name"]] = uid
        users.append({
            "id": uid, "email": ud["email"], "full_name": ud["name"],
            "role": ud["role"], "password": pwd_hash,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        print(f"  ✓  {ud['name']:<22} {ud['role']:<6} {uid[:8]}...")

    # ── Build lookup maps ────────────────────────────────────────────────
    print("\n─── Step 3: Building activity lookup maps ───\n")

    note_data = {}
    if paths["notes"]:
        print("  Loading Notes.csv ...")
        for r in read_csv_file(paths["notes"]):
            if r.get("Id"):
                note_data[r["Id"]] = r
        print(f"    → {len(note_data):,} notes")

    contact_notes = {}
    if paths["note_tgt"]:
        print("  Loading Note_targetables.csv ...")
        for r in read_csv_file(paths["note_tgt"]):
            cid = r.get("Related to Id", "")
            nid = r.get("Note Id", "")
            if cid and nid and nid in note_data:
                contact_notes.setdefault(cid, []).append(note_data[nid])
        print(f"    → {len(contact_notes):,} contacts with notes")

    task_data = {}
    if paths["tasks"]:
        print("  Loading Tasks.csv ...")
        for r in read_csv_file(paths["tasks"]):
            if r.get("Id"):
                task_data[r["Id"]] = r
        print(f"    → {len(task_data):,} tasks")

    contact_tasks = {}
    if paths["task_tgt"]:
        print("  Loading Task_targetables.csv ...")
        for r in read_csv_file(paths["task_tgt"]):
            cid = r.get("Related to Id", "")
            tid = r.get("Task Id", "")
            if cid and tid and tid in task_data:
                contact_tasks.setdefault(cid, []).append(task_data[tid])
        print(f"    → {len(contact_tasks):,} contacts with tasks")

    contact_calls = {}
    if paths["calls"]:
        print("  Loading Call_logs.csv ...")
        for r in read_csv_file(paths["calls"]):
            cid = r.get("Related to id", "")
            if cid:
                contact_calls.setdefault(cid, []).append(r)
        print(f"    → {len(contact_calls):,} contacts with calls")

    email_fb = {}
    if paths["emails"]:
        print("  Loading Contact_emails.csv ...")
        for r in read_csv_file(paths["emails"]):
            cid = r.get("Contact id", "")
            em = r.get("Email", "")
            if cid and em:
                email_fb[cid] = em
        print(f"    → {len(email_fb):,} email fallbacks")

    # ── Transform leads ──────────────────────────────────────────────────
    print("\n─── Step 4: Transforming contacts → leads ───\n")
    print("  Reading Contacts.csv ...")
    raw = read_csv_file(paths["contacts"])
    print(f"  ✓  {len(raw):,} raw rows\n")

    leads = []
    skipped = 0
    dupes = 0
    seen = set()

    for i, row in enumerate(raw):
        fid = row.get("Id", "")
        if not row.get("Emails", "").strip() and fid in email_fb:
            row["Emails"] = email_fb[fid]

        lead = transform_lead(
            row, name_to_uuid,
            contact_notes.get(fid, []),
            contact_calls.get(fid, []),
            contact_tasks.get(fid, []),
        )
        if lead is None:
            skipped += 1
            continue
        if lead["normalized_phone"] in seen:
            dupes += 1
            continue
        seen.add(lead["normalized_phone"])
        leads.append(lead)

        if (i + 1) % 5000 == 0:
            print(f"    ... {i+1:,} / {len(raw):,}")

    print(f"\n  ✓  {len(leads):,} unique leads")
    print(f"  ○  {skipped:,} skipped (no valid phone)")
    print(f"  ○  {dupes:,} duplicates removed")

    # ── Supporting data ──────────────────────────────────────────────────
    mkt = build_marketing_spends()
    settings = build_settings()

    # ── Summary ──────────────────────────────────────────────────────────
    print_summary(leads, users)

    if args.dry_run:
        print("  ✓ Dry run complete. No data written.\n")
        sample = next((l for l in leads if l["project"] and l["email"]), leads[0])
        print("  ── Sample lead ──\n")
        print(json.dumps(sample, indent=2, default=str))
        return

    # ── Write to MongoDB ─────────────────────────────────────────────────
    print("─── Step 5: Writing to MongoDB ───\n")
    client = MongoClient(args.mongo_uri)
    db = client[args.db_name]

    try:
        for col in ["leads", "users", "marketing_spends", "settings"]:
            db.drop_collection(col)
            print(f"  ✓  Dropped {col}")
        print()

        # Users
        db.users.insert_many(users)
        print(f"  ✓  {len(users)} users inserted")

        # Leads (batch)
        inserted = 0
        for i in range(0, len(leads), BATCH_SIZE):
            batch = leads[i:i + BATCH_SIZE]
            db.leads.insert_many(batch, ordered=False)
            inserted += len(batch)
            sys.stdout.write(f"\r  ↳  leads: {inserted:,} / {len(leads):,} ({inserted*100//len(leads)}%)")
            sys.stdout.flush()
        print(f"\n  ✓  {inserted:,} leads inserted")

        # Marketing
        db.marketing_spends.insert_many(mkt)
        print(f"  ✓  {len(mkt)} marketing_spends inserted")

        # Settings
        db.settings.insert_one(settings)
        print("  ✓  1 settings document inserted")

        # Indexes
        print("\n  Creating indexes ...")
        db.leads.create_index("id", unique=True)
        db.leads.create_index("normalized_phone", unique=True)
        db.leads.create_index("assigned_user_id")
        db.leads.create_index("lead_status")
        db.leads.create_index("temperature")
        db.leads.create_index("pipeline_category")
        db.leads.create_index("project")
        db.leads.create_index("lead_source")
        db.leads.create_index("created_at")
        db.leads.create_index([("assigned_user_id", 1), ("lead_status", 1)])
        db.leads.create_index([("assigned_user_id", 1), ("temperature", 1)])
        db.leads.create_index([("project", 1), ("pipeline_category", 1)])
        db.users.create_index("id", unique=True)
        db.users.create_index("email", unique=True)
        db.marketing_spends.create_index("id", unique=True)
        db.settings.create_index("id", unique=True)
        print("  ✓  16 indexes created")

        # Verify
        print("\n  ── Verification ──\n")
        for col in ["leads", "users", "marketing_spends", "settings"]:
            print(f"    {col:<22} {db[col].count_documents({}):>8,} docs")

        print("\n  ╔════════════════════════════════════════════╗")
        print("  ║        ✓ Seed completed successfully       ║")
        print("  ╚════════════════════════════════════════════╝\n")

    except Exception as e:
        print(f"\n  ✗ Error: {e}")
        raise
    finally:
        client.close()


if __name__ == "__main__":
    main()
