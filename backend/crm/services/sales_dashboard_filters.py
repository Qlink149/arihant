"""Shared Mongo filters for sales dashboard metrics (aggregation + rep-leads drill-down)."""

from __future__ import annotations

from typing import Optional

from crm.constants.lead_kpi import RNR_STATUS_REGEX, SITE_VISIT_STATUS_REGEX

SALES_DASHBOARD_METRICS = frozenset(
    {"contacted", "rnr", "site_visits", "negotiation", "deals_won", "deals_lost"}
)

DEALS_WON_STATUS_REGEX = r"closed\s*won|booked|advance\s*paid|handed\s*over|occupied"
DEALS_LOST_STATUS_REGEX = r"closed\s*lost|dropped|junk|unqualified|churned|rental"
CONTACTED_STATUS_REGEX = r"^contacted$"
NEGOTIATION_STATUS_REGEX = r"negotiat"

_DEALS_WON_QUERY = {"$regex": DEALS_WON_STATUS_REGEX, "$options": "i"}
_DEALS_LOST_QUERY = {"$regex": DEALS_LOST_STATUS_REGEX, "$options": "i"}
_CONTACTED_QUERY = {"$regex": CONTACTED_STATUS_REGEX, "$options": "i"}
_NEGOTIATION_QUERY = {"$regex": NEGOTIATION_STATUS_REGEX, "$options": "i"}
_SITE_VISIT_QUERY = {"$regex": SITE_VISIT_STATUS_REGEX, "$options": "i"}
_RNR_LEAD_QUERY = {"$regex": RNR_STATUS_REGEX, "$options": "i"}


def rnr_metric_clause() -> dict:
    return {
        "$or": [
            {"is_rnr": True},
            {"lead_status": _RNR_LEAD_QUERY},
            {"original_fw_status": _RNR_LEAD_QUERY},
        ]
    }


def build_sales_metric_filter(metric: Optional[str]) -> Optional[dict]:
    """Return a Mongo match fragment for a sales dashboard metric, or None for all leads."""
    if not metric:
        return None
    key = metric.strip().lower()
    if key not in SALES_DASHBOARD_METRICS:
        raise ValueError(
            f"Invalid metric {metric!r}; allowed: {', '.join(sorted(SALES_DASHBOARD_METRICS))}"
        )
    if key == "contacted":
        return {"lead_status": _CONTACTED_QUERY}
    if key == "rnr":
        return rnr_metric_clause()
    if key == "site_visits":
        return {"lead_status": _SITE_VISIT_QUERY}
    if key == "negotiation":
        return {"lead_status": _NEGOTIATION_QUERY}
    if key == "deals_won":
        return {"lead_status": _DEALS_WON_QUERY}
    if key == "deals_lost":
        return {"lead_status": _DEALS_LOST_QUERY}
    return None
