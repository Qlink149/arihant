"""Inventory matching per Q5 budget/location/BHK rules."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from crm.core.state import db

INCOMPLETE_TAG = "preferences_incomplete"


def _norm(s: Optional[str]) -> str:
    return (s or "").strip()


def evaluate_lead_for_inventory(lead: dict, launch: dict) -> Tuple[bool, str, List[str]]:
    """
    Returns (should_alert, blocked_reason, warnings).
    launch keys: budget, location, configuration (BHK), title, project
    """
    budget = _norm(lead.get("budget"))
    location = _norm(lead.get("location") or lead.get("city"))
    bhk = _norm(lead.get("configuration") or lead.get("bhk"))

    if not budget and not location and not bhk:
        return False, "all_preferences_missing", []

    if not budget:
        return False, "budget_missing", []

    warnings: List[str] = []
    match = True

    launch_budget = _norm(launch.get("budget"))
    if launch_budget and budget:
        if not _budget_matches(budget, launch_budget):
            match = False

    launch_loc = _norm(launch.get("location"))
    if launch_loc:
        if not location:
            warnings.append("location_missing_city_match_skipped")
            match = False
        elif not _location_matches(location, launch_loc):
            match = False
    elif not location:
        warnings.append("location_missing")

    launch_bhk = _norm(launch.get("configuration"))
    if launch_bhk:
        if not bhk:
            warnings.append(INCOMPLETE_TAG)
        elif not _bhk_matches(bhk, launch_bhk):
            match = False

    if not match:
        return False, "", warnings
    return True, "", warnings


def _budget_matches(lead_budget: str, launch_budget: str) -> bool:
    lead_nums = [int(x) for x in re.findall(r"\d+", lead_budget.replace(",", ""))]
    launch_nums = [int(x) for x in re.findall(r"\d+", launch_budget.replace(",", ""))]
    if not lead_nums or not launch_nums:
        return launch_budget.lower() in lead_budget.lower() or lead_budget.lower() in launch_budget.lower()
    lead_max = max(lead_nums)
    launch_lo = min(launch_nums)
    launch_hi = max(launch_nums) if len(launch_nums) > 1 else launch_lo * 2
    return launch_lo <= lead_max <= launch_hi * 1.2


def _location_matches(lead_loc: str, launch_loc: str) -> bool:
    a = lead_loc.lower().split(",")[0].strip()
    b = launch_loc.lower().split(",")[0].strip()
    return a in b or b in a or a == b


def _bhk_matches(lead_bhk: str, launch_bhk: str) -> bool:
    def extract(s: str) -> Optional[str]:
        m = re.search(r"(\d+)\s*bhk", s, re.I)
        return m.group(1) if m else None

    lb = extract(lead_bhk)
    rb = extract(launch_bhk)
    if lb and rb:
        return lb == rb
    return launch_bhk.lower() in lead_bhk.lower() or lead_bhk.lower() in launch_bhk.lower()


async def find_matching_leads(launch: dict, *, status_regex: str = r".*") -> List[Dict[str, Any]]:
    query: dict = {"lead_status": {"$regex": status_regex, "$options": "i"}}
    leads = await db.leads.find(query, {"_id": 0}).to_list(2000)
    results = []
    for lead in leads:
        ok, blocked, warnings = evaluate_lead_for_inventory(lead, launch)
        if blocked:
            await db.leads.update_one(
                {"id": lead["id"]},
                {"$set": {"inventory_alert_blocked_reason": blocked}},
            )
            continue
        if ok:
            results.append({"lead": lead, "warnings": warnings})
    return results


async def list_leads_missing_preferences(limit: int = 100) -> List[dict]:
    cursor = db.leads.find(
        {
            "$or": [
                {"budget": {"$in": [None, ""]}},
                {"inventory_alert_blocked_reason": {"$exists": True}},
            ]
        },
        {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "budget": 1, "location": 1, "configuration": 1, "inventory_alert_blocked_reason": 1},
    ).limit(limit)
    return await cursor.to_list(limit)
