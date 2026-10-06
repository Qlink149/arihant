"""Canonicalize project/source/channel-partner strings before a lead is written.

Single source of truth for the client-approved mapping (see
"Projects & Source list - Arihant (1).xlsx"). Used by:
  - Every production lead-creation path (see NORMALIZE_CALL_SITES below), so
    new leads never reintroduce the old short/stale names that
    backend/scripts/normalize_project_source_mapping.py already cleaned up
    in existing data.
  - backend/scripts/normalize_project_source_mapping.py itself, for one-off
    backfills against already-stored leads.

This module only normalizes the STORED string values (project, lead_source,
etc.) right before a document is persisted. It does not change how any
webhook recognizes/routes an incoming form field into a project_id or
partner name -- that recognition logic (crm/core/state.PROJECT_REGISTRY,
webflow_leads_service, channel_partner_leads_service) is untouched.

NORMALIZE_CALL_SITES (call normalize_lead_fields() immediately before each):
  - crm/services/lead_intake_service.py  _create_new_lead()  (Webflow, Zapier,
    Channel Partner, generic API-key intake)
  - crm/services/lead_service.py         create_lead()        (manual create)
  - crm/services/lead_service.py         import_csv()          (CSV import)
  - crm/services/mcube_lead_intake.py    create_mcube_unknown_lead()
  - crm/services/whatsapp_service.py     create_whatsapp_unknown_lead()
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

PROJECT_JOIN = "; "

# ---------------------------------------------------------------------------
# Mapping tables (normalized key -> canonical value). Keys are matched via
# _norm_key() below: casefolded, trimmed, internal whitespace collapsed.
# ---------------------------------------------------------------------------

PROJECT_MAP: Dict[str, str] = {
    "abhiramapuram - krishna": "Abhiramapuram - Krsna",
    "abiramapuram - krishna": "Abhiramapuram - Krsna",
    "abhiramapuram - krsna": "Abhiramapuram - Krsna",
    "krsna": "Abhiramapuram - Krsna",
    "amara": "Amara",
    "anna nagar - mira": "Anna Nagar - Mira",
    "mira": "Anna Nagar - Mira",
    "besant nagar": "Besant Nagar",
    "chamiers road - project": "Chamiers Road - Project",
    "commercial - vayu": "Commercial - Vayu",
    "commercial projects": "Commercial Projects",
    "ecr - reserve 16": "ECR - Reserve 16",
    "reserve 16": "ECR - Reserve 16",
    "ecr - swarang": "ECR - Swarang",
    "ecr- swarang": "ECR - Swarang",
    "swarang": "ECR - Swarang",
    "esta": "Esta",
    "flowers road - kilpauk": "Flowers Road - Mehek",
    "flowers road- kilpauk": "Flowers Road - Mehek",
    "flowers road - mehek": "Flowers Road - Mehek",
    "greenwood city": "Greenwood City",
    "greenwood commercial": "Greenwood City",  # no target given by client; folded per confirmed decision
    "harrington road - aurelia": "Harrington Road - Aurelia",
    "mgr salai - perungudi": "MGR Salai - Perungudi",
    "na": "NA",
    "omr - vivriti": "OMR - Vivriti",
    "omr- kottivakkam": "OMR - Vivriti",
    "omr- vivriti": "OMR - Vivriti",
    "vivriti": "OMR - Vivriti",
    "others": "Others",
    "perambur - ekanta": "Perambur - Ekanta",
    "poes garden - chirla": "Poes Garden - Chirla",
    "poes garden- chirla": "Poes Garden - Chirla",
    "rohini": "Rohini",
    "saligramam melange": "Saligramam - Melange",
    "saligramam - melange": "Saligramam - Melange",
    "m�lange": "Saligramam - Melange",  # mojibake variant seen in some exports
    "mélange": "Saligramam - Melange",
    "melange": "Saligramam - Melange",
    "sri niketan": "Sri Niketan",
    "sri nivas": "Sri Nivas",
    "thoraipakkam": "Thoraipakkam",
    "tiara": "Tiara",
    "vanya vilas": "Hunters Road - Vanya Vilas",
    "hunters road - vanya vilas": "Hunters Road - Vanya Vilas",
    "velachery upcoming": "Velachery - Park Street",
    "velachery - park street": "Velachery - Park Street",
    "venus colony - saraswathi": "Venus Colony - Saraswathi",
    "saraswathi": "Venus Colony - Saraswathi",
    "villa viviana plots": "Villa Viviana Plots",
    "vista": "Vista",
}

# canonical source name for each raw lead_source value
SOURCE_MAP: Dict[str, str] = {
    # Facebook
    "facebook_ad": "Facebook",
    "facebook lead form": "Facebook",
    "facebook_comments": "Facebook",
    "facebook": "Facebook",
    "alt facebook lead": "Facebook",
    "fb": "Facebook",
    "web form": "Facebook",
    "brochure": "Facebook",
    "socialmedia": "Facebook",
    "social media": "Facebook",
    # Incoming call
    "phone": "Incoming call",
    "incoming_call": "Incoming call",
    # Instagram
    "instagram": "Instagram",
    # Direct Walk-in
    "direct": "Direct Walk-in",
    "direct walk-in": "Direct Walk-in",
    "direct-walkin": "Direct Walk-in",
    "walk-in": "Direct Walk-in",
    # Existing Customer
    "existing client": "Existing Customer",
    # BTL
    "btl": "BTL",
    # Google
    "adwords": "Google",
    "paid social": "Google",
    "paid search": "Google",
    "organic social": "Google",
    "google": "Google",
    "digital": "Google",
    "pre launch campaign": "Google",
    "direct traffic": "Google",
    "google ads": "Google",
    "organic search": "Google",
    # Website
    "website": "Website",
    "web": "Website",
    "reserve 16 website": "Website",
    "vivriti website": "Website",
    "m�lange website": "Website",
    "mélange website": "Website",
    "melange website": "Website",
    "flowers road - kilpauk website": "Website",
    "thoraipakkam website": "Website",
    "krsna website": "Website",
    "mira website": "Website",
    "reserve 16": "Website",
    "mira": "Website",
    # Email campaign
    "emailer": "Email campaign",
    # Management Referral
    "management referral": "Management Referral",
    "management reference": "Management Referral",
    # Referral
    "reference": "Referral",
    "referral": "Referral",
    # Site Branding
    "signage": "Site Branding",
    "sitebranding": "Site Branding",
    "onsite branding": "Site Branding",
    # Outdoor Hoarding
    "hoarding": "Outdoor Hoarding",
    # Newspaper
    "newspaper": "Newspaper",
    "newspaper ad - toi 22dec": "Newspaper",
    # Mcube Inbound
    "mcube": "Mcube Inbound",
    "mcube inbound": "Mcube Inbound",
    # Whatsapp
    "whatsapp": "Whatsapp",
    "chat": "Whatsapp",
    "chatbot": "Whatsapp",
    "whatsapp chat": "Whatsapp",
    # Wati Campaign
    "wati - whatsapp campaign": "Wati Campaign",
    "wati campaign- existing customers": "Wati Campaign",
    "wati campaign - existing customers": "Wati Campaign",
    "wati campaign- leads": "Wati Campaign",
    "wati campaign - leads": "Wati Campaign",
    "wati campaign": "Wati Campaign",
    # Genie
    "genie": "Genie",
    # Aurum Analytica
    "aurum analytica": "Aurum Analytica",
    # Magic Bricks
    "magic bricks": "Magic Bricks",
    # Chennai Properties
    "chennai_properties": "Chennai Properties",
    # Housing.com
    "housing": "Housing.com",
    # Roof and Floor
    "roofandfloor": "Roof and Floor",
    # Credai Fairpro 2026
    "credai fairpro 2026": "Credai Fairpro 2026",
    "credai expo": "Credai Fairpro 2026",
    # Credai Fairpro 2025
    "credai fairpro 2025": "Credai Fairpro 2025",
    "expo": "Credai Fairpro 2025",
    # Property fair 2024
    "property fair": "Property fair 2024",
    # Channel Partner (source only; sub-source resolved via CP_SUBSOURCE_MAP)
    "channel partner": "Channel Partner",
    "channel_partner": "Channel Partner",
    "home konnect": "Channel Partner",
    "propmart": "Channel Partner",
    "propleaf": "Channel Partner",
    "nobroker": "Channel Partner",
    "chennai gated community": "Channel Partner",
    "southzone realty": "Channel Partner",
    "medsea properties": "Channel Partner",
    "proptiger": "Channel Partner",
    "thara properties": "Channel Partner",
    "jll": "Channel Partner",
    "propsmile": "Channel Partner",
    "reliable consultancy": "Channel Partner",
    "c4 realty": "Channel Partner",
    "estates61": "Channel Partner",
    # "others" (kept lowercase -- literal client-approved value, distinct from
    # the channel-partner sub-source "Others")
    "duckduckgo": "others",
    "model_1": "others",
    "bing": "others",
    "linktr.ee": "others",
    "l.wl.co": "others",
    "yahoo": "others",
    "homeloans_calling": "others",
    "t.co": "others",
    "outdoor": "others",
    "organ": "others",
    # Testing
    "testing": "Testing",
}

# raw lead_source value -> canonical channel-partner sub-source name.
# Only consulted when SOURCE_MAP resolves the same raw value to "Channel Partner".
CP_SUBSOURCE_MAP: Dict[str, str] = {
    "channel partner": "Others",
    "channel_partner": "Others",
    "home konnect": "Home Konnect",
    "propmart": "Propmart",
    "propleaf": "PropLeaf",
    "nobroker": "Nobroker",
    "chennai gated community": "Chennai Gated Community",
    "southzone realty": "Southzone Realty",
    "medsea properties": "Medsea Properties",
    "proptiger": "Proptiger",
    "thara properties": "Thara properties",
    "jll": "JLL",
    "propsmile": "Prop Smile",
    "reliable consultancy": "Reliable Consultancy",
    "c4 realty": "C4 Realty",
    "estates61": "Estates61",
}

# Fixed display order for multi-project leads, so "A; B" and "B; A" collapse
# into one canonical string instead of surviving as order-only duplicates.
PROJECT_ORDER: List[str] = list(dict.fromkeys(PROJECT_MAP.values()))


def _norm_key(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def map_project_name(raw: str) -> str:
    key = _norm_key(raw)
    return PROJECT_MAP.get(key, raw.strip())


def split_project_tokens(value: Optional[str]) -> List[str]:
    """Split on both ';' and ',' -- both separators appear in the wild."""
    if not value:
        return []
    return [t.strip() for t in re.split(r"[;,]", str(value)) if t.strip()]


def remap_projects_from_values(
    project: Optional[str], projects: Optional[List[str]]
) -> Tuple[Optional[str], Optional[List[str]]]:
    """Returns (new_project_str, new_projects_list), or (None, None) if nothing to normalize."""
    raw_tokens: List[str] = []
    raw_tokens += split_project_tokens(project)
    for item in projects or []:
        raw_tokens += split_project_tokens(item)

    if not raw_tokens:
        return None, None

    mapped: List[str] = []
    seen = set()
    for tok in raw_tokens:
        canonical = map_project_name(tok)
        key = canonical.casefold()
        if key in seen:
            continue
        seen.add(key)
        mapped.append(canonical)

    mapped.sort(key=lambda name: (PROJECT_ORDER.index(name) if name in PROJECT_ORDER else len(PROJECT_ORDER), name))
    return PROJECT_JOIN.join(mapped), mapped


def remap_source_field(raw: Optional[str]) -> Optional[str]:
    """Returns the canonical source name, or the original value unchanged if unmapped/blank."""
    if not raw or not str(raw).strip():
        return raw
    canonical = SOURCE_MAP.get(_norm_key(raw))
    return canonical if canonical is not None else raw


# Raw keys with no specific partner name attached -- only meaningful as a
# backfill catch-all for historical data (see the confirmed decision in
# backend/scripts/normalize_project_source_mapping.py). Live intake should
# never manufacture "Others" for a lead where no partner was ever resolved.
_GENERIC_CP_KEYS = frozenset({"channel partner", "channel_partner"})


def resolve_channel_partner(lead_source_raw: Optional[str], *, allow_generic_fallback: bool = True) -> Optional[str]:
    if not lead_source_raw:
        return None
    key = _norm_key(lead_source_raw)
    if SOURCE_MAP.get(key) != "Channel Partner":
        return None
    if not allow_generic_fallback and key in _GENERIC_CP_KEYS:
        return None
    return CP_SUBSOURCE_MAP.get(key)


def normalize_lead_fields(lead_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize project/source/channel_partner fields on a lead dict in place.

    Intended for a freshly-built lead document, immediately before it is
    persisted (insert_one). Safe to call on a dict missing some of these keys
    -- untouched fields are left exactly as they were. Never overwrites an
    already-populated channel_partner (mirrors the idempotency guard in
    backend/scripts/normalize_project_source_mapping.py -- once
    lead_source has been canonicalized to the literal string "Channel
    Partner", re-deriving from it would collide with the sheet's own
    generic "channel partner" raw bucket and downgrade a specific partner
    name to "Others").
    """
    raw_lead_source = lead_dict.get("lead_source")

    if "project" in lead_dict or "projects" in lead_dict:
        new_project, new_projects = remap_projects_from_values(
            lead_dict.get("project"), lead_dict.get("projects")
        )
        if new_project is not None:
            lead_dict["project"] = new_project
        if new_projects is not None:
            lead_dict["projects"] = new_projects

    for field in ("lead_source", "original_source", "most_recent_source"):
        if field in lead_dict:
            lead_dict[field] = remap_source_field(lead_dict.get(field))

    if not lead_dict.get("channel_partner"):
        new_cp = resolve_channel_partner(raw_lead_source, allow_generic_fallback=False)
        if new_cp:
            lead_dict["channel_partner"] = new_cp

    return lead_dict
