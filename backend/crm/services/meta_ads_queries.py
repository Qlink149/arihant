"""Read-side helpers for the Meta Ads dashboard (crm/api/v1/endpoints/meta_ads.py).

Correctness rules (see the dashboard plan):
  * Account totals come from CAMPAIGN-level rows only - summing campaign +
    ad set + ad rows would count every rupee three times.
  * Ratios (CTR, CPM, CPL, cost-per-X) are always recomputed from summed
    components, never averaged. Zero denominators give None.
  * Reach / frequency are non-additive (across levels AND across days), so
    they are never aggregated here - they only exist in the per-entity
    daily view where each row is exact.
  * Dates are IST calendar days (the ad account is Asia/Kolkata).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

UNASSIGNED_LABEL = "Brand / unassigned"
MAX_RANGE_DAYS = 400
DEFAULT_RANGE_DAYS = 30
MAX_PAGE_LIMIT = 500
LEVELS = ("campaign", "adset", "ad")
_IST = ZoneInfo("Asia/Kolkata")

# Additive components summed in every aggregation.
SUM_FIELDS = ("spend", "impressions", "clicks", "leads")


class RangeError(ValueError):
    """Invalid date range (maps to HTTP 400)."""


def today_ist() -> date:
    return datetime.now(_IST).date()


def _parse_day(value: str, label: str) -> date:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as e:
        raise RangeError(f"Invalid {label}: expected YYYY-MM-DD") from e


def parse_range(
    date_from: Optional[str],
    date_to: Optional[str],
    *,
    today: Optional[date] = None,
    default_days: int = DEFAULT_RANGE_DAYS,
) -> tuple[str, str]:
    """Inclusive (from, to) as YYYY-MM-DD. Defaults to the trailing
    `default_days` ending today (IST). Raises RangeError on bad/reversed/
    oversized ranges."""
    end = _parse_day(date_to, "date_to") if date_to else (today or today_ist())
    start = _parse_day(date_from, "date_from") if date_from else end - timedelta(days=default_days - 1)
    if start > end:
        raise RangeError("date_from must not be after date_to")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise RangeError(f"Range too large (max {MAX_RANGE_DAYS} days)")
    return start.isoformat(), end.isoformat()


def previous_period(date_from: str, date_to: str) -> tuple[str, str]:
    """The equally long window immediately before [date_from, date_to]."""
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return prev_start.isoformat(), prev_end.isoformat()


def safe_div(num: float, den: float) -> Optional[float]:
    return (num / den) if den else None


def _cost_per(spend: float, count: int) -> Optional[float]:
    """Cost per CRM outcome; None (not 0) when nothing was spent on Meta for
    that project - "Rs 0 per lead" would be a lie for organic/other leads."""
    if not spend or not count:
        return None
    return round(spend / count, 2)


def _round(v: Optional[float], nd: int = 2) -> Optional[float]:
    return None if v is None else round(v, nd)


def with_ratios(row: Dict[str, Any]) -> Dict[str, Any]:
    """Add ctr (%), cpm, cpc, cpl to a row holding summed spend/impressions/
    clicks/leads. Missing components count as 0; zero denominators -> None."""
    spend = float(row.get("spend") or 0)
    impressions = int(row.get("impressions") or 0)
    clicks = int(row.get("clicks") or 0)
    leads = int(row.get("leads") or 0)
    out = dict(row)
    out.update(
        spend=round(spend, 2),
        impressions=impressions,
        clicks=clicks,
        leads=leads,
        ctr=_round(safe_div(clicks * 100.0, impressions)),
        cpm=_round(safe_div(spend * 1000.0, impressions)),
        cpc=_round(safe_div(spend, clicks)),
        cpl=_round(safe_div(spend, leads)),
    )
    return out


def pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """% change vs previous period; None when there is no baseline."""
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100.0, 1)


def kpi_deltas(current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Optional[float]]:
    return {
        k: pct_change(current.get(k), previous.get(k))
        for k in ("spend", "leads", "cpl", "impressions", "clicks", "ctr", "cpm")
    }


def parse_projects(projects: Optional[str]) -> List[str]:
    return [p.strip() for p in (projects or "").split(",") if p.strip()]


def project_clause(projects: Sequence[str]) -> Optional[dict]:
    """Mongo clause on resolved_project; UNASSIGNED_LABEL means unresolved."""
    if not projects:
        return None
    named = [p for p in projects if p != UNASSIGNED_LABEL]
    ors: List[dict] = []
    if named:
        ors.append({"resolved_project": {"$in": named}})
    if UNASSIGNED_LABEL in projects:
        ors.append({"resolved_project": None})  # matches null or missing
    return ors[0] if len(ors) == 1 else {"$or": ors}


def daily_match(
    level: str,
    date_from: str,
    date_to: str,
    projects: Sequence[str] = (),
    *,
    parent_campaign_id: Optional[str] = None,
    parent_adset_id: Optional[str] = None,
) -> dict:
    q: Dict[str, Any] = {"level": level, "date": {"$gte": date_from, "$lte": date_to}}
    pc = project_clause(projects)
    if pc:
        q.update(pc)
    if parent_campaign_id:
        q["parent_campaign_id"] = parent_campaign_id
    if parent_adset_id:
        q["parent_adset_id"] = parent_adset_id
    return q


def _sum_group(id_expr: Any) -> dict:
    g: Dict[str, Any] = {"_id": id_expr}
    for f in SUM_FIELDS:
        g[f] = {"$sum": f"${f}"}
    return g


def totals_pipeline(match: dict) -> List[dict]:
    return [{"$match": match}, {"$group": _sum_group(None)}]


def daily_series_pipeline(match: dict) -> List[dict]:
    return [{"$match": match}, {"$group": _sum_group("$date")}, {"$sort": {"_id": 1}}]


def project_pipeline(match: dict) -> List[dict]:
    return [{"$match": match}, {"$group": _sum_group("$resolved_project")}]


def entity_pipeline(match: dict) -> List[dict]:
    g = _sum_group("$entity_id")
    g.update(
        entity_name={"$last": "$entity_name"},
        resolved_project={"$last": "$resolved_project"},
        parent_campaign_id={"$last": "$parent_campaign_id"},
        parent_adset_id={"$last": "$parent_adset_id"},
        creative_id={"$last": "$creative_id"},
        days_with_data={"$sum": 1},
    )
    return [{"$match": match}, {"$sort": {"date": 1}}, {"$group": g}]


def fill_series(rows: List[dict], date_from: str, date_to: str) -> List[dict]:
    """Daily series with zero-filled gaps so the chart x-axis is continuous."""
    by_day = {r["_id"]: r for r in rows}
    out: List[dict] = []
    d, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    while d <= end:
        key = d.isoformat()
        r = by_day.get(key) or {}
        out.append(
            with_ratios(
                {
                    "date": key,
                    "spend": r.get("spend", 0),
                    "impressions": r.get("impressions", 0),
                    "clicks": r.get("clicks", 0),
                    "leads": r.get("leads", 0),
                }
            )
        )
        d += timedelta(days=1)
    return out


def merge_entities(
    aggregated: List[dict],
    entities: Dict[str, dict],
    *,
    include_idle: bool = False,
    projects: Sequence[str] = (),
) -> List[dict]:
    """Join aggregated spend rows with entity metadata (status/objective/name).
    With include_idle, entities that had no data in range are listed with
    zeros (e.g. an active campaign that has not spent yet)."""
    rows: List[dict] = []
    seen = set()
    for a in aggregated:
        eid = a["_id"]
        seen.add(eid)
        meta = entities.get(eid) or {}
        rows.append(
            with_ratios(
                {
                    "entity_id": eid,
                    "name": meta.get("name") or a.get("entity_name") or eid,
                    "effective_status": meta.get("effective_status"),
                    "objective": meta.get("objective"),
                    "resolved_project": a.get("resolved_project"),
                    "parent_campaign_id": a.get("parent_campaign_id") or meta.get("parent_campaign_id"),
                    "parent_adset_id": a.get("parent_adset_id") or meta.get("parent_adset_id"),
                    "creative_id": a.get("creative_id") or meta.get("creative_id"),
                    "days_with_data": a.get("days_with_data", 0),
                    "spend": a.get("spend", 0),
                    "impressions": a.get("impressions", 0),
                    "clicks": a.get("clicks", 0),
                    "leads": a.get("leads", 0),
                }
            )
        )
    if include_idle:
        for eid, meta in entities.items():
            if eid in seen:
                continue
            if projects and not _project_selected(meta.get("resolved_project"), projects):
                continue
            rows.append(
                with_ratios(
                    {
                        "entity_id": eid,
                        "name": meta.get("name") or eid,
                        "effective_status": meta.get("effective_status"),
                        "objective": meta.get("objective"),
                        "resolved_project": meta.get("resolved_project"),
                        "parent_campaign_id": meta.get("parent_campaign_id"),
                        "parent_adset_id": meta.get("parent_adset_id"),
                        "creative_id": meta.get("creative_id"),
                        "days_with_data": 0,
                    }
                )
            )
    return rows


def _project_selected(resolved: Optional[str], projects: Sequence[str]) -> bool:
    if resolved is None:
        return UNASSIGNED_LABEL in projects
    return resolved in projects


def status_group(effective_status: Optional[str]) -> str:
    """Collapse Meta's many effective_status values into 3 UI buckets."""
    s = (effective_status or "").upper()
    if not s:
        return "unknown"
    if s == "ACTIVE":
        return "active"
    return "paused"  # PAUSED, CAMPAIGN_PAUSED, ADSET_PAUSED, ARCHIVED, DELETED, WITH_ISSUES...


SORTABLE = {"name", "spend", "leads", "cpl", "impressions", "clicks", "ctr", "cpm", "crm_leads"}


def filter_sort_page(
    rows: List[dict],
    *,
    status: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "spend",
    sort_dir: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> tuple[List[dict], int]:
    out = rows
    st = (status or "").strip().lower()
    if st in ("active", "paused", "unknown"):
        out = [r for r in out if status_group(r.get("effective_status")) == st]
    q = (search or "").strip()
    if q:
        pat = re.compile(re.escape(q), re.IGNORECASE)
        out = [r for r in out if pat.search(r.get("name") or "") or pat.search(r.get("entity_id") or "")]
    key = sort_by if sort_by in SORTABLE else "spend"
    reverse = (sort_dir or "desc").lower() != "asc"

    def sort_key(r: dict):
        v = r.get(key)
        if key == "name":
            return (v or "").lower()
        return v if v is not None else float("-inf") if reverse else float("inf")

    out = sorted(out, key=sort_key, reverse=reverse)
    total = len(out)
    limit = max(1, min(int(limit or 100), MAX_PAGE_LIMIT))
    offset = max(0, int(offset or 0))
    return out[offset : offset + limit], total


def assemble_funnel(meta_rows: List[dict], crm_rows: List[dict]) -> Dict[str, Any]:
    """Join Meta spend (by resolved_project) with the CRM cohort of
    Facebook/Instagram leads (by lead.project).

    Meta `leads` and CRM `crm_leads` are DIFFERENT definitions (form fills as
    Meta counts them vs. leads that reached the CRM after dedupe/validation),
    so both are returned and never merged. Cost-per-X divides Meta spend by
    the CRM count; None when the count is 0.
    """
    crm_by_project = {(r.get("_id") or UNASSIGNED_LABEL): r for r in crm_rows}
    names = []
    for r in meta_rows:
        names.append(r.get("_id") or UNASSIGNED_LABEL)
    for n in crm_by_project:
        if n not in names:
            names.append(n)
    meta_by_project = {(r.get("_id") or UNASSIGNED_LABEL): r for r in meta_rows}

    rows: List[dict] = []
    for name in names:
        m = meta_by_project.get(name) or {}
        c = crm_by_project.get(name) or {}
        spend = float(m.get("spend") or 0)
        crm_leads = int(c.get("leads") or 0)
        visits = int(c.get("site_visits") or 0)
        bookings = int(c.get("bookings") or 0)
        row = with_ratios(
            {
                "project": name,
                "spend": spend,
                "impressions": m.get("impressions", 0),
                "clicks": m.get("clicks", 0),
                "leads": m.get("leads", 0),
            }
        )
        row.update(
            crm_leads=crm_leads,
            crm_site_visits=visits,
            crm_bookings=bookings,
            cost_per_crm_lead=_cost_per(spend, crm_leads),
            cost_per_site_visit=_cost_per(spend, visits),
            cost_per_booking=_cost_per(spend, bookings),
        )
        rows.append(row)
    rows.sort(key=lambda r: r["spend"], reverse=True)

    total_spend = sum(r["spend"] for r in rows)
    totals = with_ratios(
        {
            "project": "Total",
            "spend": total_spend,
            "impressions": sum(r["impressions"] for r in rows),
            "clicks": sum(r["clicks"] for r in rows),
            "leads": sum(r["leads"] for r in rows),
        }
    )
    t_leads = sum(r["crm_leads"] for r in rows)
    t_visits = sum(r["crm_site_visits"] for r in rows)
    t_book = sum(r["crm_bookings"] for r in rows)
    totals.update(
        crm_leads=t_leads,
        crm_site_visits=t_visits,
        crm_bookings=t_book,
        cost_per_crm_lead=_cost_per(total_spend, t_leads),
        cost_per_site_visit=_cost_per(total_spend, t_visits),
        cost_per_booking=_cost_per(total_spend, t_book),
    )
    return {"rows": rows, "totals": totals}


def crm_funnel_pipeline(
    created_filter: dict, sources: Sequence[str], won_regex: str, group_key: str = "$project"
) -> List[dict]:
    """CRM cohort: Facebook/Instagram leads created in range, grouped by
    primary project. site visit = site_visit_count>=1 or a completed-visit
    timestamp; booking = current status matches the Deals-Won regex."""
    match: Dict[str, Any] = {"lead_source": {"$in": list(sources)}}
    if created_filter:
        match = {"$and": [match, created_filter]}
    return [
        {"$match": match},
        {
            "$group": {
                "_id": group_key,
                "leads": {"$sum": 1},
                "site_visits": {
                    "$sum": {
                        "$cond": [
                            {
                                "$or": [
                                    {"$gte": [{"$ifNull": ["$site_visit_count", 0]}, 1]},
                                    {"$ne": [{"$ifNull": ["$visit_completed_at_dt", None]}, None]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "bookings": {
                    "$sum": {
                        "$cond": [
                            {"$regexMatch": {"input": {"$ifNull": ["$lead_status", ""]}, "regex": won_regex, "options": "i"}},
                            1,
                            0,
                        ]
                    }
                },
                "with_campaign_id": {
                    "$sum": {
                        "$cond": [
                            {"$gt": [{"$strLenCP": {"$ifNull": [{"$toString": {"$ifNull": ["$campaign_id", ""]}}, ""]}}, 0]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
    ]


def attribution_summary(crm_rows: List[dict]) -> Dict[str, Any]:
    total = sum(int(r.get("leads") or 0) for r in crm_rows)
    tagged = sum(int(r.get("with_campaign_id") or 0) for r in crm_rows)
    return {
        "crm_meta_leads": total,
        "with_campaign_id": tagged,
        "coverage_pct": _round(safe_div(tagged * 100.0, total), 1) if total else None,
    }
