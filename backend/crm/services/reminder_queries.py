"""Query helpers for the reminder rules engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from crm.constants.lead_kpi import RNR_STATUS_REGEX, SITE_VISIT_STATUS_REGEX
from crm.constants.lead_status import sla_paused_exclusion_clause
from crm.services.lead_overview_service import ist_tomorrow_window


def sla_paused_exclusion() -> Dict[str, Any]:
    """Mongo filter fragment: exclude leads on historical import SLA hold."""
    return {"sla_paused": sla_paused_exclusion_clause()}


def status_clause(statuses: Optional[List[str]], *, default_regex: str) -> Dict[str, Any]:
    """Build a lead_status filter from rule lead_statuses, or fall back to default_regex."""
    cleaned = [s.strip() for s in (statuses or []) if s and str(s).strip()]
    if not cleaned:
        return {"lead_status": {"$regex": default_regex, "$options": "i"}}
    if len(cleaned) == 1:
        return {"lead_status": cleaned[0]}
    return {"$or": [{"lead_status": s} for s in cleaned]}


def stale_updated_clause(cutoff_dt: datetime, cutoff_iso: str) -> Dict[str, Any]:
    """Leads not updated since cutoff (prefer updated_at_dt, fall back to updated_at string)."""
    return {
        "$or": [
            {"updated_at_dt": {"$lt": cutoff_dt}},
            {
                "$and": [
                    {"$or": [{"updated_at_dt": {"$exists": False}}, {"updated_at_dt": None}]},
                    {"$or": [{"updated_at": {"$lt": cutoff_iso}}, {"updated_at": {"$exists": False}}]},
                ]
            },
        ]
    }


def site_visit_tomorrow_clause(now_dt: Optional[datetime] = None) -> Dict[str, Any]:
    """Leads with a site visit scheduled for tomorrow (IST calendar day)."""
    _, tomorrow_start_utc, tomorrow_end_utc = ist_tomorrow_window(now_dt)
    return {
        "$and": [
            {"lead_status": {"$regex": SITE_VISIT_STATUS_REGEX}},
            {"visit_date_dt": {"$gte": tomorrow_start_utc, "$lt": tomorrow_end_utc}},
        ]
    }


def rnr_status_clause(statuses: Optional[List[str]]) -> Dict[str, Any]:
    """RNR stale filter — use rule lead_statuses when set, else broad RNR regex."""
    cleaned = [s.strip() for s in (statuses or []) if s and str(s).strip()]
    if cleaned:
        return status_clause(cleaned, default_regex=RNR_STATUS_REGEX)
    return {"lead_status": {"$regex": RNR_STATUS_REGEX}}
