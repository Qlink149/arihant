"""Async CSV export jobs for admin lead exports (Virtual Customer)."""
from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from crm.core.state import db
from crm.services.context_updates import dedupe_context_updates
from crm.services.lead_list_query import (
    build_metric_snapshot_filter,
    compose_leads_list_query,
    resolve_leads_list_query_base,
)
from crm.services.lead_projections import EXPORT_LEAD_PROJECTION, LEAD_LIST_SORT
from crm.utils.helpers import coerce_datetime, iso_utc_now, utc_now

logger = logging.getLogger(__name__)

EXPORT_JOBS = "lead_export_jobs"
GRIDFS_BUCKET = "lead_exports"
BATCH_SIZE = 500
JOB_TTL_HOURS = 24

ExportFieldDef = Dict[str, Any]

EXPORT_FIELD_CATALOG: List[ExportFieldDef] = [
    {"key": "external_id", "label": "Id", "group": "Identity", "default": True},
    {"key": "first_name", "label": "First name", "group": "Identity", "default": True},
    {"key": "last_name", "label": "Last name", "group": "Identity", "default": True},
    {"key": "id", "label": "CRM Id", "group": "Identity", "default": False},
    {"key": "phone", "label": "Mobile", "group": "Contact", "default": True},
    {"key": "work_phone", "label": "Work", "group": "Contact", "default": False},
    {"key": "email", "label": "Emails", "group": "Contact", "default": True},
    {"key": "lead_status", "label": "Status", "group": "Status", "default": True},
    {"key": "lost_reason", "label": "Lost reason", "group": "Status", "default": False},
    {"key": "lead_source", "label": "Source", "group": "Status", "default": True},
    {"key": "original_source", "label": "Original source", "group": "Status", "default": False},
    {"key": "most_recent_source", "label": "Most recent source", "group": "Status", "default": False},
    {"key": "assigned_to", "label": "Sales owner", "group": "Status", "default": True},
    {"key": "temperature", "label": "Temperature", "group": "Status", "default": False},
    {"key": "intent", "label": "Intent", "group": "Status", "default": False},
    {"key": "vip", "label": "VIP", "group": "Status", "default": False},
    {"key": "project", "label": "Project", "group": "Property", "default": True},
    {"key": "budget", "label": "Budget", "group": "Property", "default": True},
    {"key": "location", "label": "Location Interested", "group": "Property", "default": True},
    {"key": "configuration", "label": "Configuration", "group": "Property", "default": False},
    {"key": "unit_size", "label": "Unit Size", "group": "Property", "default": False},
    {"key": "site_visit_count", "label": "No. of Site Visits", "group": "Property", "default": False},
    {"key": "meta_qualified", "label": "Meta Qualified", "group": "Property", "default": False},
    {"key": "reason_for_purchase", "label": "Reason For Purchase", "group": "Property", "default": False},
    {"key": "possession_requirement", "label": "Possession Requirement", "group": "Property", "default": False},
    {"key": "presales_description", "label": "Recent note", "group": "Notes", "default": False},
    {"key": "note_count", "label": "Note Count", "group": "Notes", "default": False},
    {"key": "all_notes", "label": "All Notes", "group": "Notes", "default": False},
    {"key": "campaign_name", "label": "Original campaign", "group": "Meta", "default": False},
    {"key": "next_action_date", "label": "Next Action Date", "group": "Meta", "default": False},
    {"key": "created_at", "label": "Created at", "group": "Meta", "default": True},
    {"key": "updated_at", "label": "Updated at", "group": "Meta", "default": True},
]

_EXPORT_KEYS = {f["key"] for f in EXPORT_FIELD_CATALOG}
_LABEL_BY_KEY = {f["key"]: f["label"] for f in EXPORT_FIELD_CATALOG}


def assert_admin(current_user: dict) -> None:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="CSV export requires admin role")


def get_export_field_catalog() -> List[Dict[str, Any]]:
    return [
        {
            "key": f["key"],
            "label": f["label"],
            "group": f["group"],
            "default": f["default"],
        }
        for f in EXPORT_FIELD_CATALOG
    ]


def _format_export_datetime(value: Any) -> str:
    dt = coerce_datetime(value)
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _note_entries(lead: dict) -> List[dict]:
    updates = dedupe_context_updates(lead.get("context_updates") or [])
    with_text = [u for u in updates if (u.get("description") or "").strip()]
    with_text.sort(
        key=lambda u: coerce_datetime(u.get("timestamp_dt") or u.get("timestamp"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )
    return with_text


def _format_all_notes(lead: dict) -> str:
    parts: List[str] = []
    for entry in _note_entries(lead):
        desc = (entry.get("description") or "").strip()
        if not desc:
            continue
        ts = coerce_datetime(entry.get("timestamp_dt") or entry.get("timestamp"))
        if ts:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            date_prefix = ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
            parts.append(f"[{date_prefix}] {desc}")
        else:
            parts.append(desc)
    return " | ".join(parts)


def _recent_note(lead: dict) -> str:
    entries = _note_entries(lead)
    if not entries:
        return (lead.get("presales_description") or "").strip()
    return (entries[-1].get("description") or "").strip()


def _field_value(lead: dict, key: str) -> Any:
    if key == "assigned_to":
        return lead.get("assigned_to") or lead.get("assigned_to_name") or lead.get("presales_agent") or ""
    if key == "note_count":
        return len(_note_entries(lead))
    if key == "all_notes":
        return _format_all_notes(lead)
    if key == "presales_description":
        return _recent_note(lead)
    if key in ("created_at", "updated_at"):
        return _format_export_datetime(lead.get(key) or lead.get(f"{key}_dt"))
    if key == "vip":
        val = lead.get("vip")
        if val is True:
            return "Yes"
        if val is False:
            return "No"
        return ""
    if key == "project":
        from crm.services.lead_project_fields import format_projects_display, coalesce_projects
        names = coalesce_projects(lead)
        if names:
            return format_projects_display(names)
        return lead.get("project") or ""
    raw = lead.get(key)
    if raw is None:
        return ""
    return raw


def _validate_fields(fields: List[str]) -> List[str]:
    if not fields:
        raise HTTPException(status_code=400, detail="Select at least one field to export")
    invalid = [f for f in fields if f not in _EXPORT_KEYS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown export fields: {', '.join(invalid)}")
    catalog_order = [f["key"] for f in EXPORT_FIELD_CATALOG]
    return [k for k in catalog_order if k in fields]


async def ensure_export_indexes() -> None:
    await db[EXPORT_JOBS].create_index("expires_at", expireAfterSeconds=0)
    await db[EXPORT_JOBS].create_index([("user_id", 1), ("status", 1)])


async def cleanup_expired_exports() -> None:
    now = utc_now()
    bucket = AsyncIOMotorGridFSBucket(db, bucket_name=GRIDFS_BUCKET)
    cursor = db[EXPORT_JOBS].find({"expires_at": {"$lt": now.isoformat()}})
    async for job in cursor:
        file_id = job.get("file_id")
        if file_id:
            try:
                await bucket.delete(ObjectId(file_id))
            except Exception:
                pass
        await db[EXPORT_JOBS].delete_one({"id": job["id"]})


async def _active_job_for_user(user_id: str) -> Optional[dict]:
    return await db[EXPORT_JOBS].find_one(
        {
            "user_id": user_id,
            "status": {"$in": ["queued", "processing"]},
        },
        {"_id": 0},
    )


async def create_export_job(
    current_user: dict,
    fields: List[str],
    filters: Dict[str, Any],
) -> dict:
    assert_admin(current_user)
    await ensure_export_indexes()
    await cleanup_expired_exports()

    selected = _validate_fields(fields)
    user_id = current_user["id"]

    active = await _active_job_for_user(user_id)
    if active:
        raise HTTPException(
            status_code=409,
            detail="An export is already in progress. Please wait for it to finish.",
        )

    snapshot_filter = None
    use_rep_pipeline = bool(filters.get("mine"))
    if filters.get("metric"):
        snapshot_filter = build_metric_snapshot_filter(
            current_user,
            project=filters.get("project"),
            projects=filters.get("projects"),
            use_rep_pipeline=use_rep_pipeline,
        )
    query_base = await resolve_leads_list_query_base(
        current_user,
        metric=filters.get("metric"),
        dormant=filters.get("dormant"),
        snapshot_filter=snapshot_filter,
        use_rep_pipeline=use_rep_pipeline,
    )
    query = compose_leads_list_query(
        query_base,
        project=filters.get("project"),
        projects=filters.get("projects"),
        project_id=filters.get("project_id"),
        temperature=filters.get("temperature"),
        budget=filters.get("budget"),
        budgets=filters.get("budgets"),
        location=filters.get("location"),
        locations=filters.get("locations"),
        intent=filters.get("intent"),
        vip=filters.get("vip"),
        re_enquiry=filters.get("re_enquiry"),
        status=filters.get("status"),
        statuses=filters.get("statuses"),
        search=filters.get("search"),
        days=filters.get("days"),
        created_from=filters.get("created_from"),
        created_to=filters.get("created_to"),
        updated_from=filters.get("updated_from"),
        updated_to=filters.get("updated_to"),
        sources=filters.get("sources"),
        source=filters.get("source"),
        sales_owners=filters.get("sales_owners"),
        sales_owner=filters.get("sales_owner"),
        meta_qualified=filters.get("meta_qualified"),
        site_visit_min=filters.get("site_visit_min"),
        site_visit_max=filters.get("site_visit_max"),
    )

    total_count = await db.leads.count_documents(query)
    if total_count == 0:
        raise HTTPException(status_code=400, detail="No leads match the current filters")

    now = utc_now()
    job_id = str(uuid.uuid4())
    stamp = now.strftime("%Y-%m-%d")
    filename = f"leads-export-{stamp}.csv"

    job = {
        "id": job_id,
        "user_id": user_id,
        "status": "queued",
        "filters": filters,
        "fields": selected,
        "query": query,
        "total_count": total_count,
        "processed_count": 0,
        "file_id": None,
        "filename": filename,
        "error": None,
        "created_at": iso_utc_now(),
        "completed_at": None,
        "expires_at": (now + timedelta(hours=JOB_TTL_HOURS)).isoformat(),
    }
    await db[EXPORT_JOBS].insert_one(job)
    job.pop("_id", None)
    job.pop("query", None)
    return job


async def get_export_job(job_id: str, current_user: dict) -> dict:
    assert_admin(current_user)
    job = await db[EXPORT_JOBS].find_one({"id": job_id}, {"_id": 0, "query": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
    if job.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not allowed to access this export job")
    expires = coerce_datetime(job.get("expires_at"))
    if expires and expires < utc_now():
        raise HTTPException(status_code=410, detail="Export has expired")
    return job


async def run_export_job(job_id: str) -> None:
    job = await db[EXPORT_JOBS].find_one({"id": job_id})
    if not job:
        return

    await db[EXPORT_JOBS].update_one(
        {"id": job_id},
        {"$set": {"status": "processing", "processed_count": 0}},
    )

    try:
        fields: List[str] = job["fields"]
        headers = [_LABEL_BY_KEY[k] for k in fields]
        query = job["query"]
        total = job["total_count"]

        buffer = io.StringIO()
        buffer.write("\ufeff")
        writer = csv.writer(buffer)
        writer.writerow(headers)

        processed = 0
        skip = 0
        while skip < total:
            batch = (
                await db.leads.find(query, EXPORT_LEAD_PROJECTION)
                .sort(LEAD_LIST_SORT)
                .skip(skip)
                .limit(BATCH_SIZE)
                .to_list(BATCH_SIZE)
            )
            if not batch:
                break
            for lead in batch:
                row = [_field_value(lead, key) for key in fields]
                writer.writerow(row)
            processed += len(batch)
            skip += len(batch)
            await db[EXPORT_JOBS].update_one(
                {"id": job_id},
                {"$set": {"processed_count": processed}},
            )

        csv_bytes = buffer.getvalue().encode("utf-8")
        bucket = AsyncIOMotorGridFSBucket(db, bucket_name=GRIDFS_BUCKET)
        file_id = await bucket.upload_from_stream(
            job.get("filename") or "leads-export.csv",
            io.BytesIO(csv_bytes),
            metadata={"job_id": job_id, "content_type": "text/csv"},
        )

        await db[EXPORT_JOBS].update_one(
            {"id": job_id},
            {
                "$set": {
                    "status": "completed",
                    "processed_count": processed,
                    "file_id": str(file_id),
                    "completed_at": iso_utc_now(),
                }
            },
        )
    except Exception as exc:
        logger.exception("Export job %s failed", job_id)
        await db[EXPORT_JOBS].update_one(
            {"id": job_id},
            {"$set": {"status": "failed", "error": str(exc), "completed_at": iso_utc_now()}},
        )


async def download_export_file(job_id: str, current_user: dict) -> tuple[bytes, str]:
    job = await get_export_job(job_id, current_user)
    if job.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Export is not ready for download")
    file_id = job.get("file_id")
    if not file_id:
        raise HTTPException(status_code=404, detail="Export file not found")

    bucket = AsyncIOMotorGridFSBucket(db, bucket_name=GRIDFS_BUCKET)
    stream = io.BytesIO()
    await bucket.download_to_stream(ObjectId(file_id), stream)
    return stream.getvalue(), job.get("filename") or "leads-export.csv"
