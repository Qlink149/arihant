#!/usr/bin/env python3
"""
seed_db_v2.py — Freshworks + FreshSales CSV → MongoDB Seed Script (v2)
========================================================================
Goals:
- Merge Freshworks raw export (Contacts + optional activity CSVs) with the
  organized FreshSales contact export (adds All Notes rollups).
- Seed MongoDB documents aligned with backend expectations:
  - leads: includes *_at (ISO string) + *_at_dt (datetime) timestamps,
    normalized_phone, assigned_user_id, assigned_to_name, context_updates.
  - users: uses hashed_password field like /api/auth/register.
  - marketing_spends: includes created_at/_dt and derived CPL/CPC.

Usage:
  python backend/seed_db_v2.py --dry-run
  python backend/seed_db_v2.py

  Loads MONGO_URL and DB_NAME from backend/.env (same as the API). Override with:
  python backend/seed_db_v2.py --mongo-uri "mongodb+srv://..." --db-name your_db

CSV placement:
  Default directory: backend/csv/
  Required: Contacts.csv
  Optional: Notes.csv, Note_targetables.csv, Tasks.csv, Task_targetables.csv,
            Call_logs.csv, Contact_emails.csv, FreshSales Data - Organized (1).csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from crm.constants.lead_kpi import fw_status_indicates_rnr
from crm.constants.import_status_map import fw_status_to_canonical
from crm.constants.lead_status import UI_LEAD_STATUSES as CANONICAL_LEAD_STATUSES
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ─── Dependency Check ────────────────────────────────────────────────────────
try:
    from pymongo import MongoClient
    import bcrypt
except ImportError as e:
    print(f"\n  [X] Missing dependency: {e.name}")
    print("    Install with:  pip install pymongo bcrypt\n")
    sys.exit(1)


# Load backend/.env so MONGO_URL / DB_NAME match FastAPI (same as app_state.py).
_BACKEND_DIR = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv

    load_dotenv(_BACKEND_DIR / ".env")
except ImportError:
    pass


# ─── Configuration ───────────────────────────────────────────────────────────

DEFAULT_CSV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "csv")
MONGO_URI = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "arihant_crm")
BATCH_SIZE = 1000
DEFAULT_PASSWORD = os.getenv("SEED_DEFAULT_PASSWORD", "Arihant@2026")

# Deterministic UUID namespace — re-runs produce identical IDs if desired
NS = uuid.UUID("b7e49a1c-3f8d-4e2a-9c1b-0d5f6e7a8b9c")


# ─── Canonical UI enums (frontend hard-codes these) ──────────────────────────

UI_PROJECTS = [
    "ECR - Reserve 16",
    "Saligramam Melange",
    "OMR - Vivriti",
    "Abhiramapuram - Krishna",
    "Flowers Road - Kilpauk",
]

UI_LOCATIONS = ["ECR", "Abhiramapuram", "OMR", "Saligramam", "Kilpauk"]
UI_BUDGETS = ["Under 1Cr", "1-2 Cr", "2-5 Cr", "Above 2Cr", "5 Cr+"]
UI_LEAD_STATUSES = list(CANONICAL_LEAD_STATUSES)
UI_LEAD_SOURCES = [
    "Facebook Lead Form",
    "facebook_ad",
    "google",
    "website",
    "instagram",
    "whatsapp",
    "newspaper",
    "direct-walkin",
    "propmart",
    "management reference",
    "CREDAI FAIRPRO 2026",
]

# DigitalTwin pipeline dropdown (frontend)
UI_PIPELINE_CATEGORIES = ["Qualified", "VIP", "Nurture", "Standard"]


# ─── Project mapping (long UI label → backend PROJECT_REGISTRY id) ───────────
PROJECT_ID_MAP: Dict[str, str] = {
    "ECR - Reserve 16": "reserve-16",
    "Abhiramapuram - Krishna": "krsna",
    "OMR - Vivriti": "vivriti",
    "Saligramam Melange": "melange",
    "Flowers Road - Kilpauk": "flowers-road",
    "Chamiers Road - Project": "chamiers-road",
    "Guindy": "guindy",
    "Thoraipakkam": "thoraipakkam",
}

PROJECT_TO_LOCATION = {
    "ECR - Reserve 16": "ECR",
    "Saligramam Melange": "Saligramam",
    "OMR - Vivriti": "OMR",
    "Abhiramapuram - Krishna": "Abhiramapuram",
    "Flowers Road - Kilpauk": "Kilpauk",
    "Chamiers Road - Project": "Chamiers Road",
    "Guindy": "Guindy",
    "Thoraipakkam": "Thoraipakkam",
}


# ─── Normalization maps (source/status/project) ──────────────────────────────

STATUS_MAP = {
    "New": "New",
    "Contacted": "Contacted",
    "Follow Up 1": "Nurturing",
    "Follow Up 2": "Nurturing",
    "Interested": "Nurturing",
    "Negotiation": "Negotiation",
    "Site Visit Scheduled": "Site Visit Scheduled",
    "Site Visit Completed": "Visit Completed",
    "Office Visit Completed": "Visit Completed",
    "Advance Paid": "Closed Won",
    "Awaiting Completion": "Closed Won",
    "Handed over": "Closed Won",
    "Occupied": "Closed Won",
    "Unqualified": "Closed Lost",
    "Junk": "Closed Lost",
    "Gone Cold": "Gone Cold",
    "Dropped": "Closed Lost",
    "Churned": "Closed Lost",
    "Rental": "Closed Lost",
    "RNR 1": "RNR",
    "RNR 2": "RNR",
    "RNR - 1": "RNR",
    "RNR - 2": "RNR",
    "Ring No Response": "RNR",
    "No Response": "RNR",
    "Project Unavailability - Future prospect": "Future Prospect",
    "Future Prospect - Bangalore": "Future Prospect",
}

SOURCE_MAP = {
    "facebook_ad": "facebook_ad",
    "Facebook Lead Form": "Facebook Lead Form",
    "Facebook Lead Ads": "Facebook Lead Form",
    "google": "google",
    "Google": "google",
    "website": "website",
    "Website": "website",
    "Web Form": "website",
    "whatsapp": "whatsapp",
    "Chat": "whatsapp",
    "WATI Campaign": "whatsapp",
    "newspaper": "newspaper",
    "mcube": "direct-walkin",
    "Direct": "direct-walkin",
    "channel partner": "management reference",
    "Home Konnect": "management reference",
    "Aurum Analytica": "management reference",
    "propmart": "propmart",
    "Propmart": "propmart",
    "instagram": "instagram",
    "Instagram": "instagram",
    "CREDAI FAIRPRO 2026": "CREDAI FAIRPRO 2026",
    "Credai Fairpro 2025": "CREDAI FAIRPRO 2026",
    "Existing Customer": "management reference",
    "Referral": "management reference",
}

# Legacy/alias project tokens (from CSV) → canonical UI project label or None
PROJECT_CLEAN_MAP: Dict[str, Optional[str]] = {
    # Canonical
    "ECR - Reserve 16": "ECR - Reserve 16",
    "Reserve 16": "ECR - Reserve 16",
    "ECR": "ECR - Reserve 16",
    "Saligramam Melange": "Saligramam Melange",
    "Melange": "Saligramam Melange",
    "Saligramam": "Saligramam Melange",
    "OMR - Vivriti": "OMR - Vivriti",
    "Vivriti": "OMR - Vivriti",
    "OMR": "OMR - Vivriti",
    "Abhiramapuram - Krishna": "Abhiramapuram - Krishna",
    "Krishna": "Abhiramapuram - Krishna",
    "Abhiramapuram": "Abhiramapuram - Krishna",
    "Flowers Road - Kilpauk": "Flowers Road - Kilpauk",
    "Kilpauk": "Flowers Road - Kilpauk",
    # Legacy → nearest active
    "Srinagar Colony - Vipassana": "Saligramam Melange",
    "Vipassana": "Saligramam Melange",
    "Villa Viviana Plots": "ECR - Reserve 16",
    "Vinyasa": "Saligramam Melange",
    "Hunters Road - Vanya Vilas": "Flowers Road - Kilpauk",
    "Vanya Vilas": "Flowers Road - Kilpauk",
    "vihaana": "OMR - Vivriti",
    "Sri Niketan": "Saligramam Melange",
    "Poes Garden - Chirla": "Abhiramapuram - Krishna",
    "Sri Nivas": "Saligramam Melange",
    # Unknown / ignore
    "Bangalore - Vilaya": None,
    "Vilaya": None,
    "Others": None,
    "NA": None,
}


# ─── Users (seed defaults) ───────────────────────────────────────────────────
USER_DEFS = [
    {"full_name": "Narendran S", "email": "narendran@arihants.co.in", "role": "rep"},
    {"full_name": "Piyush", "email": "piyush@arihants.co.in", "role": "rep"},
    {"full_name": "Malathy", "email": "malathy@arihants.co.in", "role": "rep"},
    {"full_name": "Anusha Omprakash", "email": "anusha@arihants.co.in", "role": "rep"},
    {"full_name": "jigar", "email": "jigar@arihants.co.in", "role": "rep"},
    {"full_name": "shariff", "email": "shariff@arihants.co.in", "role": "general_manager"},
    {"full_name": "Harish Marlecha", "email": "harish@arihants.co.in", "role": "admin"},
    {"full_name": "Gowtham j", "email": "gowtham@arihants.co.in", "role": "rep"},
    {"full_name": "Roshini", "email": "roshni@arihantspaces.com", "role": "admin"},
    {"full_name": "Anantharaman", "email": "anantharaman@arihants.co.in", "role": "rep"},
    {"full_name": "Yogansh", "email": "yogansh@claraai.tech", "role": "admin"},
]

# Owner display normalization (Freshworks exports include dots/variants)
OWNER_NAME_MAP = {
    "Narendran S": "Narendran S",
    "Piyush .": "Piyush",
    "Malathy .": "Malathy",
    "Anusha Omprakash": "Anusha Omprakash",
    "jigar .": "jigar",
    "shariff .": "shariff",
    "Harish Marlecha": "Harish Marlecha",
    "Gowtham j": "Gowtham j",
    "Roshni Madhav": "Roshini",
    "Roshini": "Roshini",
    "Anantharaman": "Anantharaman",
}

# Case-insensitive match from CSV owner strings to canonical USER_DEFS full_name
_SEED_FULL_NAME_BY_LOWER: Dict[str, str] = {u["full_name"].strip().lower(): u["full_name"] for u in USER_DEFS}


# ─── Helpers ────────────────────────────────────────────────────────────────

def det_uuid(seed: str) -> str:
    return str(uuid.uuid5(NS, seed))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc_now() -> str:
    return utc_now().isoformat()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")


def normalize_phone(phone: str) -> str:
    """Match backend/app_state.normalize_phone behavior closely."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone.replace("'", ""))
    if digits.startswith("91") and len(digits) > 10:
        digits = digits[2:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits[-10:] if len(digits) >= 10 else digits


def clean_phone_display(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).strip().replace("'", "").strip()
    return s or None


def parse_dt(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    s = s.replace(" UTC", "").replace("Z", "+00:00")
    # Try ISO first
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d-%m-%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def read_csv_file(filepath: str) -> List[Dict[str, str]]:
    """Read CSV with robust encoding handling (FreshSales exports are often cp1252 on Windows)."""
    encodings_to_try = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    last_err: Optional[Exception] = None
    for enc in encodings_to_try:
        try:
            rows: List[Dict[str, str]] = []
            with open(filepath, "r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    cleaned = {
                        k.strip(): (v.strip() if isinstance(v, str) else str(v))
                        for k, v in row.items()
                        if k and k.strip()
                    }
                    rows.append(cleaned)
            return rows
        except UnicodeDecodeError as e:
            last_err = e
            continue
    raise RuntimeError(f"Unable to decode CSV: {filepath}") from last_err


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


def clean_source(*candidates: str) -> str:
    for candidate in candidates:
        c = (candidate or "").strip()
        if not c:
            continue
        if c in SOURCE_MAP:
            return SOURCE_MAP[c]
        cl = c.lower()
        if "facebook" in cl:
            return "facebook_ad"
        if "google" in cl:
            return "google"
        if "instagram" in cl:
            return "instagram"
        if "whatsapp" in cl or "chat" in cl:
            return "whatsapp"
        if "newspaper" in cl:
            return "newspaper"
        if "walk" in cl or "direct" in cl or "mcube" in cl:
            return "direct-walkin"
        if "credai" in cl:
            return "CREDAI FAIRPRO 2026"
        if "propmart" in cl:
            return "propmart"
        if "referral" in cl or "reference" in cl or "partner" in cl:
            return "management reference"
        if "website" in cl or "web" in cl:
            return "website"
    return "google"


def clean_project(raw: str) -> Optional[str]:
    if not raw or not str(raw).strip():
        return None
        
    invalid_re = re.compile(r'(?i)^\s*(unknown|na|n/a|others?|null|sold\s*out\s*enquiry|homepage\s*enquiry|all\s*projects?|commercial\s*space|upcoming\s*commercial)\s*$')
    
    parts = [p.strip() for p in str(raw).split(";") if p.strip()]
    
    valid_parts = []
    for p in parts:
        if invalid_re.match(p):
            continue
        if p in PROJECT_CLEAN_MAP:
            mapped = PROJECT_CLEAN_MAP[p]
            if mapped:
                valid_parts.append(mapped)
        else:
            valid_parts.append(p)
            
    # Deduplicate
    seen = set()
    final_parts = []
    for p in valid_parts:
        if p not in seen:
            seen.add(p)
            final_parts.append(p)
            
    if not final_parts:
        return None
        
    return ";".join(final_parts)


def derive_location(project: Optional[str], loc_interested: str = "") -> Optional[str]:
    if project and project in PROJECT_TO_LOCATION:
        return PROJECT_TO_LOCATION[project]
    if loc_interested:
        text = loc_interested.replace(";", " ").lower()
        for vl in UI_LOCATIONS:
            if vl.lower() in text:
                return vl
    return None


# Budget parsing: reuse pragmatic approach from v1
BUDGET_JUNK = {
    "within_a_week",
    "this_month",
    "yes",
    "no",
    "maybe",
    "na",
    "n/a",
    "nil",
    "confirm_on_call",
    "ok",
    "open",
    "0",
    "-",
    "..",
    "hi",
    "chennai",
    "tamilnadu",
    "bihar",
    "assam",
    "india",
    "odisha",
    "nepal",
}


def parse_budget_to_crores(raw: str) -> Optional[float]:
    if not raw:
        return None
    text = str(raw).lower().strip().replace("_", " ").replace(",", "")
    if text in BUDGET_JUNK or len(text) < 2:
        return None
    if re.match(r"^[a-z]{4,}$", text) and text not in ("crore", "crores", "lakhs"):
        return None

    m = re.search(r"(\d+\.?\d*)\s*(?:cr(?:ore|s)?|c)\b", text)
    if m:
        return float(m.group(1))

    m = re.search(r"(\d+\.?\d*)\s*(?:lakh?s?|lacs?|l)\b", text)
    if m:
        return float(m.group(1)) / 100.0

    m = re.search(r"(\d+\.?\d*)\s*(?:to|-)\s*(\d+\.?\d*)\s*(?:cr|crore|c)\b", text)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2.0

    m = re.search(r"(\d+\.?\d*)\s*(?:to|-)\s*(\d+\.?\d*)\s*(?:lakh?s?|lacs?|l)\b", text)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 200.0

    if re.match(r"^[\d.]+$", text):
        try:
            val = float(text)
            if val >= 100_000:
                return val / 10_000_000
        except ValueError:
            return None
    return None


def classify_budget(crores: Optional[float]) -> Optional[str]:
    if crores is None:
        return None
    if crores < 1:
        return "Under 1Cr"
    if crores < 2:
        return "1-2 Cr"
    if crores < 5:
        return "2-5 Cr"
    return "5 Cr+"


def simulate_budget(project: Optional[str]) -> str:
    # Keep in the UI set.
    return random.choice(["Under 1Cr", "Under 1Cr", "1-2 Cr", "1-2 Cr", "2-5 Cr"])


def classify_pipeline_category(budget_label: Optional[str], status: str) -> str:
    """
    Output a category compatible with frontend DigitalTwin dropdown:
    - Qualified: high budget + strong status
    - VIP: very high budget or VIP tags implied (handled elsewhere)
    - Standard: normal active
    - Nurture: cold/dormant
    """
    b = (budget_label or "").lower()
    s = (status or "").lower()
    very_high = "5" in b and "cr" in b
    high = "2-5" in b or "above 2" in b or very_high
    if high and s in (
        "site visit scheduled",
        "visit completed",
        "closed won",
        "nurturing",
        "negotiation",
    ):
        return "Qualified"
    if very_high:
        return "VIP"
    if s in ("closed lost", "gone cold", "future prospect"):
        return "Nurture"
    return "Standard"


def temperature_from_status(status: str) -> str:
    s = (status or "").lower()
    if s in (
        "site visit scheduled",
        "visit completed",
        "closed won",
        "nurturing",
        "negotiation",
    ):
        return "Hot"
    if s in ("contacted", "new", "rnr"):
        return "Warm"
    return "Cold"


def parse_all_notes(all_notes: str, fallback_updated_iso: str) -> List[Dict[str, Any]]:
    """
    FreshSales All Notes format observed:
      [YYYY-MM-DD] text | [YYYY-MM-DD] text | ...
    """
    if not all_notes:
        return []
    chunks = [c.strip() for c in all_notes.split(" | ") if c.strip()]
    out: List[Dict[str, Any]] = []
    for ch in chunks:
        m = re.match(r"^\[(\d{4}-\d{2}-\d{2})\]\s*(.*)$", ch)
        if m:
            dt = parse_dt(m.group(1))
            text = (m.group(2) or "").strip()
        else:
            dt = None
            text = ch
        if not text:
            continue
        ts_dt = dt or parse_dt(fallback_updated_iso) or utc_now()
        out.append(
            {
                "type": "note",
                "timestamp": ts_dt.astimezone(timezone.utc).isoformat(),
                "timestamp_dt": ts_dt.astimezone(timezone.utc),
                "description": text[:500],
                "agent": "freshsales",
            }
        )
    return out


@dataclass
class ContactMerged:
    contact_id: str
    fw: Optional[Dict[str, str]]
    fs: Optional[Dict[str, str]]
    chosen: Dict[str, str]
    updated_at_dt: datetime


def merge_contact_rows(contact_id: str, fw: Optional[Dict[str, str]], fs: Optional[Dict[str, str]]) -> ContactMerged:
    """
    Merge precedence (per field):
    - Compare Freshworks vs FreshSales using each row's own `Updated at`
    - Newer wins
    - Tie -> FreshSales wins
    - Missing timestamps: prefer non-empty; if still ambiguous -> FreshSales
    """
    fw = fw or {}
    fs = fs or {}

    fw_updated_dt = parse_dt(fw.get("Updated at"))
    fs_updated_dt = parse_dt(fs.get("Updated at"))

    keys = set(fw.keys()) | set(fs.keys())
    merged: Dict[str, str] = {}

    for k in keys:
        v_fw = (fw.get(k) or "").strip()
        v_fs = (fs.get(k) or "").strip()

        if v_fw and not v_fs:
            merged[k] = v_fw
            continue
        if v_fs and not v_fw:
            merged[k] = v_fs
            continue
        if not v_fw and not v_fs:
            merged[k] = ""
            continue

        # Both non-empty: choose based on newer Updated at for that row.
        if fw_updated_dt and fs_updated_dt:
            if fs_updated_dt >= fw_updated_dt:
                merged[k] = v_fs
            else:
                merged[k] = v_fw
            continue

        if fs_updated_dt and not fw_updated_dt:
            merged[k] = v_fs
            continue
        if fw_updated_dt and not fs_updated_dt:
            merged[k] = v_fw
            continue

        # Neither timestamp parses: tie-break FreshSales.
        merged[k] = v_fs

    upd = parse_dt(merged.get("Updated at")) or fs_updated_dt or fw_updated_dt or utc_now()
    return ContactMerged(contact_id=contact_id, fw=fw or None, fs=fs or None, chosen=merged, updated_at_dt=upd)


def build_users() -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    now_dt = utc_now()
    now_iso = now_dt.isoformat()
    pwd_hash = hash_password(DEFAULT_PASSWORD)
    users: List[Dict[str, Any]] = []
    name_to_id: Dict[str, str] = {}
    for u in USER_DEFS:
        uid = det_uuid(f"user:{u['email']}")
        name_to_id[u["full_name"]] = uid
        users.append(
            {
                "id": uid,
                "email": u["email"],
                "full_name": u["full_name"],
                "phone": None,
                "role": u["role"],
                "hashed_password": pwd_hash,
                "is_active": True,
                "created_at": now_iso,
                "created_at_dt": now_dt,
                "updated_at": now_iso,
                "updated_at_dt": now_dt,
                "current_session_id": None,
                "notification_dismissals": [],
            }
        )
    return users, name_to_id


def build_marketing_spends(now_dt: datetime) -> List[Dict[str, Any]]:
    now_iso = now_dt.isoformat()
    rows = [
        {
            "id": det_uuid("mkt:r16:meta"),
            "project": "ECR - Reserve 16",
            "channel": "meta_ads",
            "amount": 35000.0,
            "leads_generated": 7,
            "conversions": 2,
            "period": "2026-Q1",
            "campaign_name": "Reserve 16 - Meta Lead Gen Q1",
            "impressions": 125000,
            "clicks": 3200,
            "notes": "Facebook+Instagram campaigns for ECR Reserve 16",
        },
        {
            "id": det_uuid("mkt:r16:news"),
            "project": "ECR - Reserve 16",
            "channel": "newspaper",
            "amount": 15000.0,
            "leads_generated": 3,
            "conversions": 1,
            "period": "2026-Q1",
            "campaign_name": "Reserve 16 - Print Campaign Q1",
            "impressions": None,
            "clicks": None,
            "notes": "Print ads",
        },
        {
            "id": det_uuid("mkt:mel:meta"),
            "project": "Saligramam Melange",
            "channel": "meta_ads",
            "amount": 175000.0,
            "leads_generated": 6,
            "conversions": 4,
            "period": "2026-Q1",
            "campaign_name": "Melange - Meta Lead Gen Q1",
            "impressions": 210000,
            "clicks": 5100,
            "notes": "High-budget Meta campaign for Melange launch",
        },
        {
            "id": det_uuid("mkt:mel:news"),
            "project": "Saligramam Melange",
            "channel": "newspaper",
            "amount": 25000.0,
            "leads_generated": 2,
            "conversions": 1,
            "period": "2026-Q1",
            "campaign_name": "Melange - Print Campaign Q1",
            "impressions": None,
            "clicks": None,
            "notes": "Print ads",
        },
    ]
    for r in rows:
        r["created_at"] = now_iso
        r["created_at_dt"] = now_dt
        r["source"] = "seed"
        r["cost_per_lead"] = round(r["amount"] / r["leads_generated"], 2) if r["leads_generated"] else 0
        r["cost_per_conversion"] = round(r["amount"] / r["conversions"], 2) if r["conversions"] else 0
    return rows


def build_activity_maps(paths: Dict[str, Optional[str]]) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, List[Dict[str, str]]], Dict[str, List[Dict[str, str]]], Dict[str, str]]:
    """
    Returns:
      contact_notes, contact_calls, contact_tasks, email_fallback
    """
    note_data: Dict[str, Dict[str, str]] = {}
    contact_notes: Dict[str, List[Dict[str, str]]] = {}
    contact_calls: Dict[str, List[Dict[str, str]]] = {}
    task_data: Dict[str, Dict[str, str]] = {}
    contact_tasks: Dict[str, List[Dict[str, str]]] = {}
    email_fb: Dict[str, str] = {}

    if paths.get("notes"):
        for r in read_csv_file(paths["notes"]):  # type: ignore[arg-type]
            if r.get("Id"):
                note_data[r["Id"]] = r

    if paths.get("note_tgt"):
        for r in read_csv_file(paths["note_tgt"]):  # type: ignore[arg-type]
            cid = r.get("Related to Id", "")
            nid = r.get("Note Id", "")
            if cid and nid and nid in note_data:
                contact_notes.setdefault(cid, []).append(note_data[nid])

    if paths.get("tasks"):
        for r in read_csv_file(paths["tasks"]):  # type: ignore[arg-type]
            if r.get("Id"):
                task_data[r["Id"]] = r

    if paths.get("task_tgt"):
        for r in read_csv_file(paths["task_tgt"]):  # type: ignore[arg-type]
            cid = r.get("Related to Id", "")
            tid = r.get("Task Id", "")
            if cid and tid and tid in task_data:
                contact_tasks.setdefault(cid, []).append(task_data[tid])

    if paths.get("calls"):
        for r in read_csv_file(paths["calls"]):  # type: ignore[arg-type]
            cid = r.get("Related to id", "")
            if cid:
                contact_calls.setdefault(cid, []).append(r)

    if paths.get("emails"):
        for r in read_csv_file(paths["emails"]):  # type: ignore[arg-type]
            cid = r.get("Contact id", "")
            em = r.get("Email", "")
            if cid and em:
                email_fb[cid] = em

    return contact_notes, contact_calls, contact_tasks, email_fb


def build_context_updates(
    merged_row: Dict[str, str],
    updated_at_dt: datetime,
    ctx_notes: List[Dict[str, str]],
    ctx_calls: List[Dict[str, str]],
    ctx_tasks: List[Dict[str, str]],
    *,
    include_import_marker: bool = False,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    updated_iso = updated_at_dt.isoformat()
    row_updated = parse_dt(merged_row.get("Updated at"))

    # Freshworks Notes
    for n in ctx_notes:
        desc = (n.get("Description") or "").strip()
        if not desc:
            continue
        ts_dt = parse_dt(n.get("Created at")) or row_updated or updated_at_dt
        entry: Dict[str, Any] = {
            "type": "note",
            "timestamp": ts_dt.isoformat(),
            "timestamp_dt": ts_dt,
            "description": desc[:500],
            "agent": "freshworks",
        }
        if n.get("Id"):
            entry["note_id"] = str(n.get("Id")).strip()
        out.append(entry)

    # Freshworks Calls
    for c in ctx_calls:
        outcome = (c.get("Outcome") or "").strip()
        notes = (c.get("Notes") or "").strip()
        desc = f"{outcome}: {notes}" if notes else outcome
        if not desc:
            continue
        ts_dt = parse_dt(c.get("Created at")) or row_updated or updated_at_dt
        out.append(
            {
                "type": "call",
                "timestamp": ts_dt.isoformat(),
                "timestamp_dt": ts_dt,
                "description": desc[:500],
                "agent": "freshworks",
            }
        )

    # Freshworks Tasks
    for t in ctx_tasks:
        title = (t.get("Title") or "").strip()
        ttype = (t.get("Task type") or "").strip()
        desc = f"[{ttype}] {title}" if ttype else title
        if not desc:
            continue
        ts_dt = parse_dt(t.get("Created at")) or row_updated or updated_at_dt
        out.append(
            {
                "type": "task",
                "timestamp": ts_dt.isoformat(),
                "timestamp_dt": ts_dt,
                "description": desc[:500],
                "agent": "freshworks",
            }
        )

    # FreshSales rollup notes
    all_notes = (merged_row.get("All Notes") or "").strip()
    if all_notes:
        out.extend(parse_all_notes(all_notes, merged_row.get("Updated at") or updated_iso))

    # If still empty, fall back to Recent note
    if not out:
        rn = (merged_row.get("Recent note") or "").strip()
        if rn:
            out.append(
                {
                    "type": "note",
                    "timestamp": updated_iso,
                    "timestamp_dt": updated_at_dt,
                    "description": rn[:500],
                    "agent": "freshworks",
                }
            )

    if include_import_marker:
        out.append(
            {
                "type": "imported",
                "timestamp": updated_iso,
                "timestamp_dt": updated_at_dt,
                "description": "Imported via seed_db_v2",
                "agent": "seed_db_v2",
            }
        )

    from crm.services.context_updates import dedupe_context_updates

    out = dedupe_context_updates(out)
    out.sort(key=lambda x: x.get("timestamp_dt") or updated_at_dt, reverse=True)
    return out[:50]


def transform_to_lead(
    cm: ContactMerged,
    name_to_user_id: Dict[str, str],
    contact_notes: Dict[str, List[Dict[str, str]]],
    contact_calls: Dict[str, List[Dict[str, str]]],
    contact_tasks: Dict[str, List[Dict[str, str]]],
    email_fb: Dict[str, str],
    *,
    include_import_marker: bool = False,
) -> Optional[Dict[str, Any]]:
    row = cm.chosen
    contact_id = cm.contact_id

    # Resolve email fallback if Emails empty.
    if not (row.get("Emails") or "").strip() and contact_id in email_fb:
        row["Emails"] = email_fb[contact_id]

    # Phone
    raw_mobile = (row.get("Mobile") or "").strip()
    raw_work = (row.get("Work") or "").strip()
    raw_phone = raw_mobile or raw_work
    display_phone = clean_phone_display(raw_phone)
    normalized = normalize_phone(raw_phone)
    if len(normalized) != 10:
        return None
    work_phone = None
    normalized_work_phone = None
    if raw_mobile and raw_work and raw_work != raw_mobile:
        work_phone = clean_phone_display(raw_work)
        normalized_work_phone = normalize_phone(raw_work) if work_phone else None

    original_source = (row.get("Original source") or "").strip() or None
    most_recent_source = (row.get("Most recent source") or "").strip() or None

    # Names
    first = (row.get("First name") or "").strip() or "Unknown"
    last = (row.get("Last name") or "").strip() or ""

    # Email (prefer Emails first token; then Work email)
    email_raw = (row.get("Emails") or "").strip()
    email = None
    if email_raw:
        email = email_raw.split(";")[0].strip() or None
    if not email:
        email = (row.get("Work email") or "").strip() or None

    # Project + location
    project = clean_project(row.get("Project") or "")
    location = derive_location(project, row.get("Location Interested") or "")

    # Budget
    budget_c = parse_budget_to_crores(row.get("Budget") or "")
    budget = classify_budget(budget_c) or simulate_budget(project)
    if budget not in UI_BUDGETS:
        # Keep in UI list as much as possible.
        if budget == "5 Cr+":
            budget = "5 Cr+"
        else:
            budget = random.choice(UI_BUDGETS)

    # Status & source
    fw_status = (row.get("Status") or "").strip()
    lead_status, is_rnr_mapped = fw_status_to_canonical(fw_status)
    if lead_status not in UI_LEAD_STATUSES:
        lead_status = "New"
    is_rnr = is_rnr_mapped or fw_status_indicates_rnr(fw_status)

    lead_source = clean_source(
        row.get("Source") or "",
        row.get("Original source") or "",
        row.get("Most recent source") or "",
    )
    if lead_source not in UI_LEAD_SOURCES:
        lead_source = "google"

    # Assignment
    reps = [u["full_name"] for u in USER_DEFS if u["role"] == "rep"]

    def _pick_rep_by_phone() -> str:
        if reps:
            return reps[hash(normalized) % len(reps)]
        return "Narendran S"

    fw_owner = (row.get("Sales owner") or "").strip()
    assigned_name = OWNER_NAME_MAP.get(fw_owner) or fw_owner or None
    if not assigned_name:
        assigned_name = _pick_rep_by_phone()
    elif assigned_name not in name_to_user_id:
        canon = _SEED_FULL_NAME_BY_LOWER.get(assigned_name.strip().lower())
        if canon and canon in name_to_user_id:
            assigned_name = canon
    if assigned_name not in name_to_user_id:
        assigned_name = _pick_rep_by_phone()
    assigned_user_id = name_to_user_id.get(assigned_name)

    # Profile / DNA from CSV (best-effort column aliases)
    unit = (
        (row.get("Unit Size") or row.get("Unit size") or row.get("Preferred Unit") or row.get("Preferred unit") or "")
        .strip()
    ) or None
    apt = (
        (
            row.get("Apartment Type")
            or row.get("Apartment type")
            or row.get("Configuration")
            or row.get("BHK")
            or row.get("Unit Type")
            or ""
        ).strip()
    )
    configuration = apt.strip() or None
    if configuration and configuration.lower() in ("yes", "may_be", "no", "yes ", "may_be "):
        configuration = None
    unit_size = unit

    meta_raw = (row.get("Meta Qualified") or row.get("Meta qualified") or "").strip().lower()
    meta_qualified = None
    if meta_raw in ("yes", "y", "true", "1"):
        meta_qualified = True
    elif meta_raw in ("no", "n", "false", "0"):
        meta_qualified = False

    site_visit_raw = (row.get("No. of Site Visits") or row.get("Site Visits") or "").strip()
    site_visit_count = 0
    if site_visit_raw:
        try:
            site_visit_count = max(0, int(float(site_visit_raw)))
        except ValueError:
            site_visit_count = 0
    possession_requirement = (
        (row.get("Possession") or row.get("Possession timeline") or row.get("Possession requirement") or "").strip()
        or None
    )
    reason_for_purchase = (
        (row.get("Reason for purchase") or row.get("Purpose") or row.get("Buying intent") or "").strip() or None
    )
    rlow = (reason_for_purchase or "").lower()
    if "invest" in rlow or "rental" in rlow:
        intent = "Investor"
    elif "self" in rlow or "end user" in rlow or "own use" in rlow or "live" in rlow:
        intent = "Self-Occupation"
    elif reason_for_purchase:
        intent = "Not Decided"
    else:
        intent = "Unknown"

    # Timestamps
    created_dt = parse_dt(row.get("Created at")) or utc_now()
    updated_dt = cm.updated_at_dt or created_dt
    created_iso = created_dt.isoformat()
    updated_iso = updated_dt.isoformat()

    # Pipeline category + temperature
    pipeline_category = classify_pipeline_category(budget, lead_status)
    temperature = temperature_from_status(lead_status)

    # VIP flag: conservative heuristic aligned to UI
    vip = ("vip" in (row.get("Tags") or "").lower()) or ("hni" in (row.get("Tags") or "").lower()) or ("5" in (budget or ""))
    if vip and pipeline_category != "Qualified":
        pipeline_category = "VIP"

    # project_id (explicit map)
    project_id = PROJECT_ID_MAP.get(project) if project else None

    # Context updates
    ctx = build_context_updates(
        row,
        updated_dt,
        contact_notes.get(contact_id, []),
        contact_calls.get(contact_id, []),
        contact_tasks.get(contact_id, []),
        include_import_marker=include_import_marker,
    )

    # Lead id deterministic by contact id (stable), fallback to phone
    lead_id = det_uuid(f"lead:{contact_id or normalized}")

    doc: Dict[str, Any] = {
        "id": lead_id,
        "external_id": contact_id,
        "first_name": first,
        "last_name": last,
        "phone": display_phone,
        "normalized_phone": normalized,
        "work_phone": work_phone,
        "normalized_work_phone": normalized_work_phone,
        "email": email,
        "project": project,
        "project_id": project_id,
        "budget": budget,
        "location": location,
        "lead_status": lead_status,
        "lead_source": lead_source,
        "original_source": original_source,
        "most_recent_source": most_recent_source,
        "original_fw_status": fw_status or None,
        "is_rnr": is_rnr,
        "configuration": configuration,
        "unit_size": unit_size,
        "site_visit_count": site_visit_count,
        "meta_qualified": meta_qualified,
        "possession_requirement": possession_requirement,
        "reason_for_purchase": reason_for_purchase,
        "pipeline_category": pipeline_category if pipeline_category in UI_PIPELINE_CATEGORIES else "Standard",
        "temperature": temperature,
        "intent": intent if intent in ("Investor", "Self-Occupation", "Not Decided", "Unknown") else "Unknown",
        "vip": bool(vip),
        "assigned_to": assigned_name,
        "assigned_to_name": assigned_name,
        "assigned_user_id": assigned_user_id,
        "presales_agent": assigned_name,
        "presales_description": None,
        "campaign_name": (row.get("Most recent campaign") or row.get("Campaign") or "").strip() or None,
        "context_updates": ctx,
        "ai_persona_summary": None,
        "strategic_next_moves": [],
        "ai_grounded_profile": None,
        "ai_last_generated_at": None,
        "ai_last_generated_at_dt": None,
        "created_at": created_iso,
        "created_at_dt": created_dt,
        "updated_at": updated_iso,
        "updated_at_dt": updated_dt,
        # Provenance
        "source_system": "merged" if cm.fw and cm.fs else ("freshsales" if cm.fs else "freshworks"),
        "seed_inputs": ["Contacts.csv", "FreshSales Data - Organized (1).csv"] if cm.fs else ["Contacts.csv"],
        "import_provenance": "freshworks",
        "sla_paused": True,
    }

    # ai_persona_summary / Grok fields left None for live AI service (GET lead stale-while-revalidate)

    return doc


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed Freshworks + FreshSales CRM data into MongoDB (v2)")
    ap.add_argument("--csv-dir", default=DEFAULT_CSV_DIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mongo-uri", default=MONGO_URI)
    ap.add_argument("--db-name", default=DB_NAME)
    ap.add_argument(
        "--skip-drop",
        action="store_true",
        help="Do not drop collections before insert (default drops leads/users/marketing_spends unless --upsert).",
    )
    ap.add_argument("--upsert", action="store_true", help="Upsert instead of drop+insert (uses normalized_phone).")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of Contacts processed (debug).")
    ap.add_argument(
        "--include-seed-marker",
        action="store_true",
        help="Append synthetic 'Imported via seed_db_v2' context_updates entry (default: off for production timelines).",
    )
    args = ap.parse_args()

    print("\n" + "=" * 72)
    print("seed_db_v2.py - Freshworks + FreshSales -> MongoDB")
    print("=" * 72 + "\n")
    print(f"  MongoDB  : {args.mongo_uri}")
    print(f"  Database : {args.db_name}")
    print(f"  CSV Dir  : {args.csv_dir}")
    print(f"  Dry Run  : {args.dry_run}")
    print(f"  Seed marker in timeline : {args.include_seed_marker}")
    drop_collections = (not args.skip_drop) and (not args.upsert)
    print(f"  DropCols : {drop_collections}")
    print(f"  Upsert   : {args.upsert}\n")

    # ── Locate files ─────────────────────────────────────────────────
    print("--- Step 1: Locating input files ---\n")
    FILES = {
        "contacts": ("Contacts.csv", True),
        "freshsales": ("FreshSales Data - Organized (1).csv", False),
        "notes": ("Notes.csv", False),
        "note_tgt": ("Note_targetables.csv", False),
        "tasks": ("Tasks.csv", False),
        "task_tgt": ("Task_targetables.csv", False),
        "calls": ("Call_logs.csv", False),
        "emails": ("Contact_emails.csv", False),
    }
    paths: Dict[str, Optional[str]] = {}
    for key, (fname, req) in FILES.items():
        fp = find_csv(args.csv_dir, fname)
        paths[key] = fp
        if fp:
            print(f"  [OK] {fname:<40} found")
        elif req:
            print(f"  [X]  {fname:<40} MISSING")
            sys.exit(1)
        else:
            print(f"  [SKIP] {fname:<37} skipped")

    # ── Build users ──────────────────────────────────────────────────
    print("\n--- Step 2: Building users ---\n")
    users, name_to_user_id = build_users()
    for u in users:
        print(f"  [OK] {u['full_name']:<22} {u['role']:<6} {u['id'][:8]}...")

    # ── Load contact sources ─────────────────────────────────────────
    print("\n--- Step 3: Loading contact sources ---\n")
    fw_rows = read_csv_file(paths["contacts"])  # type: ignore[arg-type]
    if args.limit and args.limit > 0:
        fw_rows = fw_rows[: args.limit]
    fw_by_id = {r.get("Id", ""): r for r in fw_rows if r.get("Id")}
    print(f"  [OK] Freshworks Contacts: {len(fw_by_id):,}")

    fs_by_id: Dict[str, Dict[str, str]] = {}
    if paths.get("freshsales"):
        fs_rows = read_csv_file(paths["freshsales"])  # type: ignore[arg-type]
        if args.limit and args.limit > 0:
            fs_rows = fs_rows[: args.limit]
        fs_by_id = {r.get("Id", ""): r for r in fs_rows if r.get("Id")}
        print(f"  [OK] FreshSales Organized: {len(fs_by_id):,}")
    else:
        print("  [SKIP] FreshSales Organized not provided")

    # ── Activity maps ────────────────────────────────────────────────
    print("\n--- Step 4: Building activity lookup maps ---\n")
    contact_notes, contact_calls, contact_tasks, email_fb = build_activity_maps(paths)
    print(f"  Notes links : {len(contact_notes):,} contacts")
    print(f"  Calls links : {len(contact_calls):,} contacts")
    print(f"  Tasks links : {len(contact_tasks):,} contacts")
    print(f"  Email fb    : {len(email_fb):,} contacts")

    # ── Merge and transform ──────────────────────────────────────────
    print("\n--- Step 5: Merging + transforming contacts -> leads ---\n")
    all_ids = set(fw_by_id.keys()) | set(fs_by_id.keys())
    merged_contacts: List[ContactMerged] = []
    for cid in all_ids:
        merged_contacts.append(merge_contact_rows(cid, fw_by_id.get(cid), fs_by_id.get(cid)))

    merged_contacts.sort(key=lambda c: c.updated_at_dt, reverse=True)

    leads: List[Dict[str, Any]] = []
    skipped = 0
    merged_dupes = 0
    seen_phone: Dict[str, str] = {}  # normalized_phone -> lead_id kept
    seen_email: Dict[str, str] = {}  # email -> lead_id kept

    for i, cm in enumerate(merged_contacts):
        lead = transform_to_lead(
            cm,
            name_to_user_id,
            contact_notes,
            contact_calls,
            contact_tasks,
            email_fb,
            include_import_marker=args.include_seed_marker,
        )
        if not lead:
            skipped += 1
            continue

        nphone = lead.get("normalized_phone") or ""
        email = (lead.get("email") or "").strip().lower()

        # Dedup by normalized_phone first, then by email when no phone (rare here).
        if nphone and nphone in seen_phone:
            merged_dupes += 1
            continue
        if (not nphone or len(nphone) != 10) and email and email in seen_email:
            merged_dupes += 1
            continue
        if nphone:
            seen_phone[nphone] = lead["id"]
        if email:
            seen_email[email] = lead["id"]

        leads.append(lead)
        if (i + 1) % 10000 == 0:
            print(f"    ... processed {i+1:,} / {len(merged_contacts):,}")

    print(f"\n  [OK] Leads ready: {len(leads):,}")
    print(f"  [INFO] Skipped    : {skipped:,} (no valid phone)")
    print(f"  [INFO] Duplicates : {merged_dupes:,} (deduped)")

    # Supporting seeded spends
    now_dt = utc_now()
    marketing_spends = build_marketing_spends(now_dt)

    # ── Dry run output ───────────────────────────────────────────────
    if args.dry_run:
        print("\n--- Dry run sample ---\n")
        sample = next((l for l in leads if l.get("project") and l.get("email")), leads[0] if leads else None)
        if sample:
            safe = dict(sample)
            if isinstance(safe.get("created_at_dt"), datetime):
                safe["created_at_dt"] = safe["created_at_dt"].isoformat()
            if isinstance(safe.get("updated_at_dt"), datetime):
                safe["updated_at_dt"] = safe["updated_at_dt"].isoformat()
            cu_out = []
            for cu in safe.get("context_updates", []):
                cu = dict(cu)
                if isinstance(cu.get("timestamp_dt"), datetime):
                    cu["timestamp_dt"] = cu["timestamp_dt"].isoformat()
                cu_out.append(cu)
            safe["context_updates"] = cu_out
            print(json.dumps(safe, indent=2, default=str))
        print("\n  [OK] Dry run complete. No data written.\n")
        return

    # ── Write to MongoDB ─────────────────────────────────────────────
    print("--- Step 6: Writing to MongoDB ---\n")
    client = MongoClient(args.mongo_uri)
    db = client[args.db_name]
    try:
        if drop_collections:
            for col in ["leads", "users", "marketing_spends", "project_registry"]:
                db.drop_collection(col)
                print(f"  [OK] Dropped {col}")
            print()

        # Users
        if args.upsert:
            for u in users:
                db.users.update_one({"email": u["email"]}, {"$set": u}, upsert=True)
            print(f"  [OK] {len(users)} users upserted")
        else:
            db.users.insert_many(users, ordered=False)
            print(f"  [OK] {len(users)} users inserted")

        # Leads
        if args.upsert:
            up = 0
            for l in leads:
                key = {"normalized_phone": l.get("normalized_phone")} if l.get("normalized_phone") else {"id": l["id"]}
                db.leads.update_one(key, {"$set": l}, upsert=True)
                up += 1
                if up % 5000 == 0:
                    sys.stdout.write(f"\r  -> leads upserted: {up:,} / {len(leads):,}")
                    sys.stdout.flush()
            print(f"\n  [OK] {up:,} leads upserted")
        else:
            inserted = 0
            for i in range(0, len(leads), BATCH_SIZE):
                batch = leads[i : i + BATCH_SIZE]
                db.leads.insert_many(batch, ordered=False)
                inserted += len(batch)
                sys.stdout.write(f"\r  -> leads inserted: {inserted:,} / {len(leads):,}")
                sys.stdout.flush()
            print(f"\n  [OK] {inserted:,} leads inserted")

        # Project registry (discovered project names from CSV / clean_project)
        invalid_proj = re.compile(r"(?i)^\s*(unknown|na|n/a|others|null)\s*$")
        seen_projects: set[str] = set()
        for l in leads:
            p = (l.get("project") or "").strip()
            if p and not invalid_proj.match(p):
                seen_projects.add(p)
        now_iso = utc_now().isoformat()
        for pname in sorted(seen_projects):
            slug = re.sub(r"[^a-z0-9]+", "-", pname.lower()).strip("-")[:120] or "project"
            db.project_registry.update_one(
                {"name": pname},
                {"$set": {"name": pname, "slug": slug, "updated_at": now_iso}, "$setOnInsert": {"created_at": now_iso}},
                upsert=True,
            )
        if seen_projects:
            print(f"  [OK] project_registry upserted: {len(seen_projects):,} distinct projects")

        # Marketing spends
        if args.upsert:
            for s in marketing_spends:
                db.marketing_spends.update_one({"id": s["id"]}, {"$set": s}, upsert=True)
            print(f"  [OK] {len(marketing_spends)} marketing_spends upserted")
        else:
            db.marketing_spends.insert_many(marketing_spends, ordered=False)
            print(f"  [OK] {len(marketing_spends)} marketing_spends inserted")

        # Indexes (match backend critical ones)
        print("\n  Creating indexes ...")
        db.users.create_index("id", unique=True, name="users_id_uq")
        db.users.create_index("email", unique=True, name="users_email_uq")
        db.leads.create_index("id", unique=True, name="leads_id_uq")
        db.leads.create_index([("project_id", 1), ("updated_at", -1)], name="leads_projectId_updatedAt")
        db.leads.create_index([("assigned_user_id", 1), ("updated_at_dt", -1)], name="leads_assignedUser_updatedAtDt")
        db.leads.create_index("normalized_phone", unique=True, sparse=True, name="leads_normalized_phone_uq_sparse")
        db.leads.create_index([("lead_status", 1), ("updated_at", -1)], name="leads_status_updatedAt")
        db.leads.create_index([("assigned_to", 1), ("updated_at", -1)], name="leads_assignedTo_updatedAt")
        db.marketing_spends.create_index("id", unique=True, name="marketing_spends_id_uq")
        db.marketing_spends.create_index([("project", 1), ("period", 1)], name="marketing_spends_project_period")
        db.marketing_spends.create_index([("channel", 1), ("period", 1)], name="marketing_spends_channel_period")
        print("  [OK] Indexes created")

        # Verify
        print("\n  ── Verification ──\n")
        for col in ["leads", "users", "marketing_spends"]:
            print(f"    {col:<18} {db[col].count_documents({}):>8,} docs")

        print("\n" + "=" * 52)
        print("  [OK] Seed v2 completed successfully")
        print("=" * 52 + "\n")
    finally:
        client.close()


if __name__ == "__main__":
    main()

