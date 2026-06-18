"""Canonical picklists for lead Source, Project, Location, and Budget fields."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

BUDGET_RANGES: List[str] = [
    "Under 1Cr",
    "1-2 Cr",
    "2-5 Cr",
    "5 Cr+",
]

CANONICAL_PROJECTS: List[str] = [
    "ECR - Reserve 16",
    "OMR - Vivriti",
    "Saligramam Melange",
    "Anna Nagar - Mira",
    "Abhiramapuram - Krishna",
    "NA",
    "MGR Salai - Perungudi",
    "Velachery upcoming",
    "Others",
    "Hunters Road - Vanya Vilas",
    "Saraswathi",
    "Sri Nivas",
    "Rohini",
    "Villa Viviana Plots",
    "Tiara",
    "Besant Nagar",
    "Esta",
    "Greenwood City",
    "Sri Niketan",
    "Vinyasa",
    "Harrington Road - Aurelia",
    "Greenwood Commercial",
    "Vihaana",
    "Amara",
    "All projects",
    "Commercial Projects",
    "Commercial - Vayu",
    "Poes Garden - Chirla",
    "ECR - Swarang",
    "Flowers Road - Kilpauk",
    "Bangalore - Vilaya",
    "Srinagar Colony - Vipassana",
    "Homepage Enquiry",
    "Perambur - Ekanta",
    "Venus Colony - Saraswathi",
    "Sold Out Enquiry",
    "Chamiers Road - Project",
]

CANONICAL_LOCATIONS: List[str] = [
    "Adyar",
    "Abiramapuram",
    "Alwarpet",
    "Ambattur",
    "Aminjikarai",
    "Anna Nagar",
    "Ashok Nagar",
    "Ayanavaram",
    "Besant Nagar",
    "Boat Club Road",
    "Cathedral Road",
    "Cenotaph Road",
    "Chetpet",
    "Chromepet",
    "Egmore",
    "Ennore",
    "Gopalapuram",
    "Guindy",
    "Harrington Road",
    "Injambakkam",
    "Kelambakkam",
    "Kilpauk",
    "KK Nagar",
    "Korattur",
    "Kotturpuram",
    "Kovalam",
    "Madhavaram",
    "Madipakkam",
    "Mahabalipuram",
    "Mandaveli",
    "Medavakkam",
    "Mogappair",
    "Muttukadu",
    "Mylapore",
    "Nanganallur",
    "Navalur",
    "Neelankarai",
    "Nolambur",
    "Nungambakkam",
    "Others",
    "Padur",
    "Palavakkam",
    "Pallavaram",
    "Pallikaranai",
    "Pattipulam",
    "Perambur",
    "Perungudi",
    "Poes Garden",
    "Porur",
    "Purasawalkam",
    "R.A. Puram",
    "Red Hills",
    "Royapettah",
    "Saligramam",
    "Selaiyur",
    "Shenoy Nagar",
    "Sholinganallur",
    "Siruseri",
    "T. Nagar",
    "Tambaram",
    "Teynampet",
    "Thiruvanmiyur",
    "Thoraipakkam",
    "Uthandi",
    "Vadapalani",
    "Valasaravakkam",
    "Velachery",
    "Vepery",
    "Virugambakkam",
]

CANONICAL_SOURCES: List[str] = [
    "19 estates",
    "99acres",
    "adwords",
    "aurum analytica",
    "brochure",
    "btl",
    "channel partner",
    "chatbot",
    "chennai_properties",
    "cold calling",
    "commonfloor",
    "corporate activity",
    "credai expo",
    "data migration",
    "digital",
    "direct",
    "direct walk-in",
    "economic_times",
    "email",
    "employee referral",
    "etconnect",
    "event / exhibition",
    "expo",
    "facebook_ad",
    "gantry",
    "google ads",
    "hoarding",
    "housing",
    "instagram",
    "justdial",
    "landingpage",
    "leaflet",
    "linkedin",
    "magicbricks",
    "management referral",
    "mcube",
    "mygate",
    "newspaper",
    "nobroker",
    "offline activity",
    "old digital leads",
    "organic",
    "outdoor",
    "outdoor-mobile van",
    "portal",
    "print",
    "property fair",
    "property_portal",
    "propertyfinder",
    "propertywala",
    "propstory",
    "prospect referral",
    "quora ads",
    "radio",
    "realatte",
    "realty acres",
    "referral",
    "roofandfloor",
    "self generated",
    "signage",
    "sitebranding",
    "socialmedia",
    "society marketing",
    "taboola",
    "tele calling",
    "testing",
    "times_of_india",
    "twitter",
    "voice calls",
    "website",
    "whatsapp",
    "youtube",
]


def _norm_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def merge_picklist_with_db(
    canonical: List[str],
    db_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Canonical options first (count from DB when present), then DB-only legacy values."""
    counts: Dict[str, int] = {}
    display_by_key: Dict[str, str] = {}
    for row in db_rows or []:
        name = str(row.get("name") or row.get("_id") or "").strip()
        if not name:
            continue
        key = _norm_key(name)
        counts[key] = counts.get(key, 0) + int(row.get("count") or 0)
        if key not in display_by_key:
            display_by_key[key] = name

    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for name in canonical:
        key = _norm_key(name)
        if key in seen:
            continue
        seen.add(key)
        merged.append({"name": name, "count": counts.get(key, 0)})

    extras: List[Dict[str, Any]] = []
    for key, name in display_by_key.items():
        if key in seen:
            continue
        extras.append({"name": name, "count": counts.get(key, 0)})
    extras.sort(key=lambda x: (-x["count"], x["name"].lower()))
    merged.extend(extras)
    return merged
