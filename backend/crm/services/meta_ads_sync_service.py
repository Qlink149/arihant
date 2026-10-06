"""Daily Meta Ads (Campaign/AdSet/Ad) performance sync.

Pulls a trailing window (default 30 days - Meta's attribution window means
recent days keep changing) and upserts into meta_ads_daily_metrics, keyed by
(account_id, level, entity_id, date) so late-arriving conversions within
that window are picked up on the next run without duplicating rows. Reach
and frequency are fetched per level directly from Meta (never derived by
summing a lower level) - summing ad-level reach was proven to overcount
campaign-level reach by ~9% in the live audit that preceded this service.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from crm.core.state import (
    META_ADS_ACCESS_TOKEN,
    META_ADS_ACCOUNT_IDS,
    META_API_VERSION,
    db,
    utc_now,
)

# The token must never appear in a request URL: httpx's own request logger
# (enabled INFO-and-up by crm.core.state's root logging config) logs the
# full method+URL line for every call, which would print the token in
# cleartext to logs/console. Always send it via the Authorization header
# instead (Meta's Graph API supports this explicitly for this reason).
# Quieting the httpx logger here too, as a second layer - belt and braces.
logging.getLogger("httpx").setLevel(logging.WARNING)
from crm.services.notification_service import create_notification

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 30.0
SYNC_WINDOW_DAYS = 30
_CRON_LOCK_JOB = "meta_ads_sync"
_CRON_LOCK_TTL_MINUTES = 15
TOKEN_EXPIRY_WARNING_DAYS = 7

# The two action_types confirmed (live audit) to represent actual leads -
# everything else in Meta's `actions` array is a different engagement signal.
LEAD_ACTION_TYPES = ("lead", "onsite_conversion.lead_grouped")

INSIGHTS_FIELDS = "spend,impressions,reach,clicks,ctr,cpm,frequency,actions"

# Campaign-name -> canonical CRM project (crm/constants/lead_picklists.py
# CANONICAL_PROJECTS). Deliberately a standalone list, not a reuse of
# lead_field_normalize.PROJECT_MAP: that map's keys are tuned for exact
# normalized project-field values, not substring-matching inside free-text
# campaign names, and several of its short/generic keys ("na", "others",
# "esta") would false-positive-match unrelated campaign text. Verified
# against the live account's 304 campaign names (Meta Ads audit) - covers
# every clear lead-gen campaign; anything else resolves to None rather than
# guess (most of the other ~160 campaigns are generic brand/engagement
# content that genuinely isn't tied to one project).
CAMPAIGN_PROJECT_ALIASES: List[tuple] = [
    ("vanya vilas", "Hunters Road - Vanya Vilas"),
    ("reserve 16", "ECR - Reserve 16"),
    ("r-16", "ECR - Reserve 16"),
    ("r16", "ECR - Reserve 16"),
    ("melange", "Saligramam - Melange"),
    ("mira", "Anna Nagar - Mira"),
    ("krsna", "Abhiramapuram - Krsna"),
    ("vipassana", "Srinagar Colony - Vipassana"),
    ("saraswathi", "Venus Colony - Saraswathi"),
    ("chirla", "Poes Garden - Chirla"),
    ("vilaya", "Bangalore - Vilaya"),
    ("vinyasa", "Vinyasa"),
    ("sri niketan", "Sri Niketan"),
    ("sri nivas", "Sri Nivas"),
    ("greenwood city", "Greenwood City"),
    ("villa viviana", "Villa Viviana Plots"),
    ("tiara", "Tiara"),
    ("vihaana", "Vihaana"),
    ("ekanta", "Perambur - Ekanta"),
    ("vivriti", "OMR - Vivriti"),
    ("chamiers road", "Chamiers Road - Project"),
]


def resolve_project_from_campaign_name(campaign_name: Optional[str]) -> Optional[str]:
    """Case-insensitive match on whole keywords (not bare substrings - "mira"
    must not match inside "admiration"). Underscore/hyphen/space/punctuation
    all count as boundaries, so "Sri Nivas_Calls" and "Melange-LG" match.
    Returns None (never guesses) for generic/brand/engagement campaigns."""
    name = (campaign_name or "").strip().lower()
    if not name:
        return None
    for keyword, project in CAMPAIGN_PROJECT_ALIASES:
        if re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", name):
            return project
    return None


def sum_lead_actions(actions: Optional[List[dict]]) -> int:
    """Leads for one insights row. Meta reports the same lead under both
    `lead` (the total) and `onsite_conversion.lead_grouped` (the on-Meta
    subset of it) - verified on live data: summing them double-counted
    (325 vs 166 across the synced window). So take `lead` when present and
    only fall back to the grouped type when `lead` is absent."""
    if not actions:
        return 0
    by_type: Dict[str, float] = {}
    for a in actions:
        t = a.get("action_type")
        if t in LEAD_ACTION_TYPES:
            try:
                by_type[t] = float(a.get("value") or 0)
            except (TypeError, ValueError):
                continue
    for t in LEAD_ACTION_TYPES:  # priority order: lead, then lead_grouped
        if t in by_type:
            return int(by_type[t])
    return 0


_ACCOUNT_TZ = ZoneInfo("Asia/Kolkata")


def _redact(text: str) -> str:
    """Strip the access token (and the same value as input_token) from any
    string that is about to be stored, notified or logged."""
    out = text or ""
    token = META_ADS_ACCESS_TOKEN
    if token:
        out = out.replace(token, "***")
    return out


async def _release_cron_lock() -> None:
    try:
        await db.cron_locks.delete_one({"job": _CRON_LOCK_JOB})
    except Exception as e:
        logger.warning("meta_ads_sync lock release failed (TTL will expire it): %s", e)


async def _acquire_cron_lock(now_dt: datetime) -> bool:
    """Same mutex shape as sla_engine.py's _acquire_cron_lock, parameterized
    for this job - reuses the existing cron_locks collection/index as-is."""
    expires = now_dt + timedelta(minutes=_CRON_LOCK_TTL_MINUTES)
    owner = str(uuid.uuid4())
    try:
        result = await db.cron_locks.find_one_and_update(
            {
                "job": _CRON_LOCK_JOB,
                "$or": [{"expires_at": {"$lt": now_dt}}, {"expires_at": {"$exists": False}}],
            },
            {"$set": {"job": _CRON_LOCK_JOB, "locked_at": now_dt, "expires_at": expires, "owner": owner}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return False
    except Exception as e:
        logger.warning("meta_ads_sync lock not acquired: %s", e)
        return False
    if not result:
        return False
    return (result.get("owner") or "") == owner


def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {META_ADS_ACCESS_TOKEN}"}


async def _debug_token(client: httpx.AsyncClient) -> Dict[str, Any]:
    r = await client.get(
        f"https://graph.facebook.com/{META_API_VERSION}/debug_token",
        params={"input_token": META_ADS_ACCESS_TOKEN},
        headers=_auth_headers(),
    )
    r.raise_for_status()
    return r.json().get("data", {})


async def _get_paginated(client: httpx.AsyncClient, path: str, params: dict) -> List[dict]:
    out: List[dict] = []
    url = f"https://graph.facebook.com/{META_API_VERSION}/{path}"
    p: Optional[dict] = dict(params)
    while url:
        r = await client.get(url, params=p, headers=_auth_headers())
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("data", []))
        next_url = (data.get("paging") or {}).get("next")
        if next_url:
            # Meta's own "next" link embeds access_token as a query param -
            # strip it before following, since the Authorization header
            # above already carries it and we never want the token in a URL.
            parsed = httpx.URL(next_url)
            p = {k: v for k, v in parsed.params.multi_items() if k != "access_token"}
            url = str(parsed.copy_with(query=None))
        else:
            url = None
            p = None
    return out


async def _find_admin() -> Optional[dict]:
    return await db.users.find_one(
        {"role": {"$regex": r"^\s*admin\s*$", "$options": "i"}},
        {"_id": 0, "id": 1, "full_name": 1},
    )


async def _write_sync_log(
    *,
    started_at_dt: datetime,
    finished_at_dt: datetime,
    status: str,
    accounts_synced: int,
    rows_upserted: int,
    error_message: Optional[str] = None,
    token_info: Optional[dict] = None,
) -> None:
    doc: Dict[str, Any] = {
        "job": _CRON_LOCK_JOB,
        "started_at_dt": started_at_dt,
        "started_at": started_at_dt.isoformat(),
        "finished_at_dt": finished_at_dt,
        "finished_at": finished_at_dt.isoformat(),
        "status": status,
        "accounts_synced": accounts_synced,
        "rows_upserted": rows_upserted,
        "error_message": (error_message[:500] if error_message else None),
    }
    if token_info:
        doc["token_expires_at"] = token_info.get("expires_at")
        doc["token_data_access_expires_at"] = token_info.get("data_access_expires_at")
        doc["token_expiring_soon"] = bool(token_info.get("expiring_soon"))
    try:
        await db.meta_ads_sync_logs.insert_one(doc)
    except Exception as e:
        logger.error("meta_ads_sync_logs insert failed: %s", e)


async def _notify_admin(*, title: str, message: str, dedupe_key: str) -> None:
    admin = await _find_admin()
    if not admin:
        return
    await create_notification(
        recipient_user_id=admin["id"],
        recipient_name=admin.get("full_name") or "",
        title=title,
        message=message,
        notification_type="action_required",
        severity="high",
        urgency="action_needed",
        dedupe_key=dedupe_key,
    )


def _check_token_expiry(raw_token_info: dict, now_dt: datetime) -> Dict[str, Any]:
    expires_at = raw_token_info.get("expires_at")
    data_access_expires_at = raw_token_info.get("data_access_expires_at")
    expiring_soon = False
    if data_access_expires_at:
        remaining = datetime.fromtimestamp(data_access_expires_at, tz=timezone.utc) - now_dt
        expiring_soon = remaining.days <= TOKEN_EXPIRY_WARNING_DAYS
    return {
        "expires_at": expires_at,
        "data_access_expires_at": data_access_expires_at,
        "expiring_soon": expiring_soon,
    }


def _row_entity_id(row: dict, id_field: str) -> Optional[str]:
    return row.get(id_field)


async def _sync_one_account(client: httpx.AsyncClient, account_id: str, since: str, until: str) -> int:
    """Returns rows upserted for this account."""
    campaigns = await _get_paginated(
        client, f"{account_id}/campaigns", {"fields": "id,name,effective_status,objective", "limit": 500}
    )
    campaign_project = {c["id"]: resolve_project_from_campaign_name(c.get("name")) for c in campaigns}

    adsets = await _get_paginated(
        client, f"{account_id}/adsets", {"fields": "id,name,campaign_id,effective_status", "limit": 500}
    )
    adset_campaign = {a["id"]: a.get("campaign_id") for a in adsets}

    ads = await _get_paginated(
        client,
        f"{account_id}/ads",
        {"fields": "id,name,adset_id,campaign_id,effective_status,creative{id}", "limit": 500},
    )
    ad_by_id = {a["id"]: a for a in ads}

    rows_upserted = 0
    for level, id_field, name_field in (
        ("campaign", "campaign_id", "campaign_name"),
        ("adset", "adset_id", "adset_name"),
        ("ad", "ad_id", "ad_name"),
    ):
        insights = await _get_paginated(
            client,
            f"{account_id}/insights",
            {
                "level": level,
                "fields": f"{id_field},{name_field},{INSIGHTS_FIELDS}",
                "time_range": json.dumps({"since": since, "until": until}),
                "time_increment": 1,
                "limit": 500,
            },
        )
        for row in insights:
            entity_id = _row_entity_id(row, id_field)
            if not entity_id or not row.get("date_start"):
                continue

            parent_campaign_id: Optional[str] = None
            parent_adset_id: Optional[str] = None
            creative_id: Optional[str] = None
            if level == "campaign":
                resolved_project = campaign_project.get(entity_id)
            elif level == "adset":
                parent_campaign_id = adset_campaign.get(entity_id)
                resolved_project = campaign_project.get(parent_campaign_id)
            else:
                ad_doc = ad_by_id.get(entity_id) or {}
                parent_adset_id = ad_doc.get("adset_id")
                parent_campaign_id = ad_doc.get("campaign_id")
                creative_id = (ad_doc.get("creative") or {}).get("id")
                resolved_project = campaign_project.get(parent_campaign_id)

            doc = {
                "account_id": account_id,
                "level": level,
                "entity_id": entity_id,
                "entity_name": row.get(name_field),
                "parent_campaign_id": parent_campaign_id,
                "parent_adset_id": parent_adset_id,
                "creative_id": creative_id,
                "resolved_project": resolved_project,
                "date": row.get("date_start"),
                "spend": float(row.get("spend") or 0),
                "impressions": int(row.get("impressions") or 0),
                "reach": int(row.get("reach") or 0),
                "clicks": int(row.get("clicks") or 0),
                "ctr": float(row.get("ctr") or 0),
                "cpm": float(row.get("cpm") or 0),
                "frequency": float(row.get("frequency") or 0),
                "actions": row.get("actions") or [],
                "leads": sum_lead_actions(row.get("actions")),
                "synced_at_dt": utc_now(),
            }
            await db.meta_ads_daily_metrics.update_one(
                {"account_id": account_id, "level": level, "entity_id": entity_id, "date": doc["date"]},
                {"$set": doc},
                upsert=True,
            )
            rows_upserted += 1
    return rows_upserted


async def sync_daily_meta_ads(*, window_days: int = SYNC_WINDOW_DAYS) -> dict:
    now_dt = utc_now()
    today = now_dt.strftime("%Y-%m-%d")

    if not META_ADS_ACCESS_TOKEN or not META_ADS_ACCOUNT_IDS:
        return {"ok": False, "skipped": True, "reason": "not_configured"}

    if not await _acquire_cron_lock(now_dt):
        return {"skipped": True, "reason": "lock_held"}

    accounts_synced = 0
    rows_upserted = 0
    error_message: Optional[str] = None
    token_info: Dict[str, Any] = {}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        try:
            raw_token_info = await _debug_token(client)
            token_info = _check_token_expiry(raw_token_info, now_dt)

            # Meta interprets time_range dates in the AD ACCOUNT's timezone
            # (Asia/Kolkata for act_337772997348503), so derive the window
            # from the IST calendar day, not UTC - otherwise runs between
            # 18:30 and 24:00 UTC would miss "today" in IST.
            today_ist = now_dt.astimezone(_ACCOUNT_TZ)
            since = (today_ist - timedelta(days=window_days)).strftime("%Y-%m-%d")
            until = today_ist.strftime("%Y-%m-%d")

            for account_id in META_ADS_ACCOUNT_IDS:
                rows_upserted += await _sync_one_account(client, account_id, since, until)
                accounts_synced += 1
        except Exception as e:
            # Never let the token reach the DB/notification/log: httpx's
            # HTTPStatusError text embeds the full request URL, and
            # debug_token's URL carries input_token=<token>.
            error_message = _redact(str(e))
            logger.error("meta_ads_sync failed: %s", error_message)
        finally:
            await _release_cron_lock()

    finished_at_dt = utc_now()
    status = "error" if error_message else "ok"
    await _write_sync_log(
        started_at_dt=now_dt,
        finished_at_dt=finished_at_dt,
        status=status,
        accounts_synced=accounts_synced,
        rows_upserted=rows_upserted,
        error_message=error_message,
        token_info=token_info,
    )

    if error_message:
        await _notify_admin(
            title="Meta Ads sync failed",
            message=f"Daily Meta Ads sync failed: {error_message[:200]}",
            dedupe_key=f"meta_ads_sync_failed:{today}",
        )
    elif token_info.get("expiring_soon"):
        await _notify_admin(
            title="Meta Ads token expiring soon",
            message="The Meta Ads access token's data access will expire within 7 days. Please refresh META_ADS_ACCESS_TOKEN.",
            dedupe_key=f"meta_ads_token_expiring:{today}",
        )

    return {
        "ok": not error_message,
        "accounts_synced": accounts_synced,
        "rows_upserted": rows_upserted,
        "error": error_message,
        "token_expiring_soon": bool(token_info.get("expiring_soon")),
    }
