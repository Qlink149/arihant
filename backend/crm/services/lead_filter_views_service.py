"""Per-user saved filter views for Virtual Customer."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from crm.core.state import db
from crm.utils.helpers import iso_utc_now

COLLECTION = "lead_filter_views"
MAX_VIEWS_PER_USER = 20
MAX_NAME_LEN = 60


class LeadFilterViewFilters(BaseModel):
    budgets: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    projects: List[str] = Field(default_factory=list)
    statuses: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    sales_owners: List[str] = Field(default_factory=list)
    vip: Optional[bool] = None
    re_enquiry: Optional[bool] = None
    intent: str = ""
    temperature: str = ""
    days: str = ""
    created_from: str = ""
    created_to: str = ""
    updated_from: str = ""
    updated_to: str = ""
    date_field: str = "created"  # created | updated — match VC date filter mode
    meta_qualified: Optional[bool] = None
    site_visit_min: Optional[int] = None
    site_visit_max: Optional[int] = None
    metric: str = ""
    dormant: bool = False
    mine: bool = False
    search: str = ""

    @field_validator(
        "budgets",
        "locations",
        "projects",
        "statuses",
        "sources",
        "sales_owners",
        mode="before",
    )
    @classmethod
    def _coerce_str_list(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if v is not None and str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []


class LeadFilterViewCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=MAX_NAME_LEN)
    filters: LeadFilterViewFilters


class LeadFilterViewUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=MAX_NAME_LEN)
    filters: Optional[LeadFilterViewFilters] = None


def _normalize_name(name: str) -> str:
    return " ".join(str(name).strip().split())


async def list_filter_views(user_id: str) -> List[dict]:
    cursor = db[COLLECTION].find({"user_id": user_id}, {"_id": 0}).sort("name", 1)
    return await cursor.to_list(MAX_VIEWS_PER_USER)


async def create_filter_view(user_id: str, body: LeadFilterViewCreate) -> dict:
    name = _normalize_name(body.name)
    if not name:
        raise HTTPException(status_code=400, detail="View name is required")

    existing_count = await db[COLLECTION].count_documents({"user_id": user_id})
    if existing_count >= MAX_VIEWS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum of {MAX_VIEWS_PER_USER} saved views allowed",
        )

    duplicate = await db[COLLECTION].find_one({"user_id": user_id, "name": name}, {"_id": 0, "id": 1})
    if duplicate:
        raise HTTPException(status_code=409, detail="A view with this name already exists")

    now = iso_utc_now()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "name": name,
        "filters": body.filters.model_dump(),
        "created_at": now,
        "updated_at": now,
    }
    await db[COLLECTION].insert_one(doc)
    doc.pop("_id", None)
    return doc


async def update_filter_view(user_id: str, view_id: str, body: LeadFilterViewUpdate) -> dict:
    existing = await db[COLLECTION].find_one({"id": view_id, "user_id": user_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Filter view not found")

    updates: Dict[str, Any] = {"updated_at": iso_utc_now()}
    if body.name is not None:
        name = _normalize_name(body.name)
        if not name:
            raise HTTPException(status_code=400, detail="View name is required")
        duplicate = await db[COLLECTION].find_one(
            {"user_id": user_id, "name": name, "id": {"$ne": view_id}},
            {"_id": 0, "id": 1},
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="A view with this name already exists")
        updates["name"] = name
    if body.filters is not None:
        updates["filters"] = body.filters.model_dump()

    await db[COLLECTION].update_one({"id": view_id, "user_id": user_id}, {"$set": updates})
    return await db[COLLECTION].find_one({"id": view_id, "user_id": user_id}, {"_id": 0})


async def delete_filter_view(user_id: str, view_id: str) -> None:
    result = await db[COLLECTION].delete_one({"id": view_id, "user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Filter view not found")
