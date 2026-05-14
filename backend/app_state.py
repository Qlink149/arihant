import os
import re
import io
import csv
import json
import uuid
import jwt
import bcrypt
import httpx
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Union, Literal

from bson import ObjectId
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from fastapi import HTTPException, Depends, UploadFile, File, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")


# MongoDB connection
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]


# JWT Configuration
SECRET_KEY = os.environ.get("SECRET_KEY", "arihant-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


# Gupshup WhatsApp Configuration
GUPSHUP_TOKEN = os.environ.get("GUPSHUP_TOKEN", "")
GUPSHUP_API_KEY = os.environ.get("GUPSHUP_API_KEY", "")
GUPSHUP_APP_ID = os.environ.get("GUPSHUP_APP_ID", "")
GUPSHUP_SOURCE_PHONE = os.environ.get("GUPSHUP_SOURCE_PHONE", "")
GUPSHUP_APP_NAME = os.environ.get("GUPSHUP_APP_NAME", "ArihantSalesIntelligence")
GUPSHUP_BASE_URL = "https://api.gupshup.io"
GUPSHUP_PARTNER_URL = "https://partner.gupshup.io"


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ==================== DATETIME HELPERS ====================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc_now() -> str:
    # Keep legacy ISO string format for backwards compatibility in existing queries.
    return utc_now().isoformat()


def coerce_datetime(value: Union[None, str, datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


# ==================== PROJECT REGISTRY ====================

PROJECT_REGISTRY = [
    {"id": "reserve-16", "name": "Reserve 16"},
    {"id": "krsna", "name": "Krsna"},
    {"id": "vivriti", "name": "Vivriti"},
    {"id": "melange", "name": "Mélange"},
]


def resolve_project_id(project_name: Optional[str]) -> Optional[str]:
    if not project_name:
        return None
    for p in PROJECT_REGISTRY:
        if p["name"].strip().lower() == project_name.strip().lower():
            return p["id"]
    return None


# ==================== DB INDEXES ====================

async def ensure_db_indexes():
    """
    Ensure critical MongoDB indexes exist.
    Safe to run on startup; Mongo will no-op if index already exists.
    """
    try:
        # users
        await db.users.create_index([("id", 1)], unique=True, name="users_id_uq")
        await db.users.create_index([("email", 1)], unique=True, name="users_email_uq")

        # leads
        await db.leads.create_index([("id", 1)], unique=True, name="leads_id_uq")
        await db.leads.create_index([("project_id", 1), ("updated_at", -1)], name="leads_projectId_updatedAt")
        await db.leads.create_index([("assigned_user_id", 1), ("updated_at_dt", -1)], name="leads_assignedUser_updatedAtDt")
        await db.leads.create_index(
            [("normalized_phone", 1)],
            unique=True,
            sparse=True,
            name="leads_normalized_phone_uq_sparse",
        )
        await db.leads.create_index([("created_at", -1)], name="leads_created_at_desc")
        await db.leads.create_index([("updated_at", -1)], name="leads_updated_at_desc")
        await db.leads.create_index([("lead_status", 1), ("updated_at", -1)], name="leads_status_updatedAt")
        await db.leads.create_index([("assigned_to", 1), ("updated_at", -1)], name="leads_assignedTo_updatedAt")

        # tasks
        await db.tasks.create_index([("id", 1)], unique=True, name="tasks_id_uq")
        await db.tasks.create_index([("lead_id", 1), ("due_date", 1)], name="tasks_leadId_dueDate")
        await db.tasks.create_index([("assigned_to", 1), ("status", 1), ("due_date", 1)], name="tasks_assigned_status_dueDate")
        await db.tasks.create_index([("status", 1), ("due_date", 1)], name="tasks_status_dueDate")
        await db.tasks.create_index([("assigned_user_id", 1), ("status", 1), ("due_at_dt", 1)], name="tasks_assignedUser_status_dueAtDt")

        # notifications
        await db.notifications.create_index([("id", 1)], unique=True, name="notifications_id_uq")
        await db.notifications.create_index([("assigned_to", 1), ("is_read", 1), ("created_at", -1)], name="notifications_assigned_unread_createdAt")
        await db.notifications.create_index([("user_id", 1), ("is_read", 1), ("created_at", -1)], name="notifications_user_unread_createdAt")
        await db.notifications.create_index([("recipient_user_id", 1), ("is_read", 1), ("created_at_dt", -1)], name="notifications_recipientUser_unread_createdAtDt")
        await db.notifications.create_index([("lead_id", 1), ("created_at", -1)], name="notifications_lead_createdAt")
        await db.notifications.create_index([("task_id", 1)], name="notifications_taskId")
        await db.notifications.create_index([("dedupe_key", 1)], unique=True, sparse=True, name="notifications_dedupeKey_uq_sparse")

        # campaigns
        await db.campaigns.create_index([("id", 1)], unique=True, name="campaigns_id_uq")
        await db.campaigns.create_index([("created_at", -1)], name="campaigns_created_at_desc")

        # whatsapp_messages
        await db.whatsapp_messages.create_index([("id", 1)], unique=True, name="whatsapp_messages_id_uq")
        await db.whatsapp_messages.create_index([("gupshup_message_id", 1)], name="whatsapp_messages_gsId")
        await db.whatsapp_messages.create_index([("source", 1), ("created_at", -1)], name="whatsapp_messages_source_createdAt")
        await db.whatsapp_messages.create_index([("destination", 1), ("created_at", -1)], name="whatsapp_messages_destination_createdAt")

        # lead_transfers
        await db.lead_transfers.create_index([("id", 1)], unique=True, name="lead_transfers_id_uq")
        await db.lead_transfers.create_index([("to_rep", 1), ("acknowledged", 1), ("transferred_at", -1)], name="lead_transfers_to_ack_transferredAt")
        await db.lead_transfers.create_index([("to_user_id", 1), ("acknowledged", 1), ("transferred_at_dt", -1)], name="lead_transfers_toUser_ack_transferredAtDt")
        await db.lead_transfers.create_index([("lead_id", 1), ("transferred_at", -1)], name="lead_transfers_lead_transferredAt")

        # reminder_rules / reminders
        await db.reminder_rules.create_index([("id", 1)], unique=True, name="reminder_rules_id_uq")
        await db.reminders.create_index([("id", 1)], unique=True, name="reminders_id_uq")
        await db.reminders.create_index([("lead_id", 1), ("trigger", 1), ("created_at", -1)], name="reminders_lead_trigger_createdAt")
        await db.reminders.create_index([("task_id", 1), ("trigger", 1), ("created_at", -1)], name="reminders_task_trigger_createdAt")
        await db.reminders.create_index([("dedupe_key", 1)], unique=True, sparse=True, name="reminders_dedupeKey_uq_sparse")

        # marketing_spends
        await db.marketing_spends.create_index([("id", 1)], unique=True, name="marketing_spends_id_uq")
        await db.marketing_spends.create_index([("project", 1), ("period", 1)], name="marketing_spends_project_period")
        await db.marketing_spends.create_index([("channel", 1), ("period", 1)], name="marketing_spends_channel_period")

        # webhook_configs
        await db.webhook_configs.create_index([("app_id", 1)], unique=True, name="webhook_configs_app_id_uq")

        logger.info("DB indexes ensured")
    except Exception as e:
        logger.error(f"Failed ensuring DB indexes: {e}")


async def seed_default_alert_configs():
    """Seed default alert configurations if none exist"""
    count = await db.alert_configs.count_documents({})
    if count == 0:
        now_dt = utc_now()
        now_iso = iso_utc_now()
        defaults = [
            {
                "id": str(uuid.uuid4()),
                "name": "RNR Follow-up Reminder",
                "alert_type": "rnr_followup",
                "description": "Alert when an RNR lead hasn't been contacted within 24 hours",
                "threshold_hours": 24,
                "is_active": True,
                "severity": "high",
                "created_at": now_iso,
                "created_at_dt": now_dt,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Dormant Lead Alert",
                "alert_type": "dormant_lead",
                "description": "Alert when a lead has no activity for 7+ days",
                "threshold_days": 7,
                "is_active": True,
                "severity": "medium",
                "created_at": now_iso,
                "created_at_dt": now_dt,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Task Reminders",
                "alert_type": "task_reminder",
                "description": "Send reminders for upcoming and overdue tasks",
                "threshold_hours": 1,
                "is_active": True,
                "severity": "high",
                "created_at": now_iso,
                "created_at_dt": now_dt,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "New Lead Assignment",
                "alert_type": "new_lead_assigned",
                "description": "Notify when a new lead is assigned to a sales rep",
                "threshold_hours": 0,
                "is_active": True,
                "severity": "low",
                "created_at": now_iso,
                "created_at_dt": now_dt,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Site Visit Reminder",
                "alert_type": "site_visit_reminder",
                "description": "Remind 1 hour before and on the day of a scheduled site visit",
                "threshold_hours": 1,
                "is_active": True,
                "severity": "medium",
                "created_at": now_iso,
                "created_at_dt": now_dt,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Campaign Milestone Alert",
                "alert_type": "campaign_alert",
                "description": "Alert when a campaign hits 50% pickup rate or completes",
                "threshold_percent": 50,
                "is_active": True,
                "severity": "low",
                "created_at": now_iso,
                "created_at_dt": now_dt,
            },
        ]
        for config in defaults:
            await db.alert_configs.insert_one(config)
        logger.info("Seeded 6 default alert configurations")


# ==================== MODELS ====================

class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    role: Literal["admin", "manager", "rep"] = "rep"


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    model_config = ConfigDict(extra="ignore")
    id: str
    is_active: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class LeadBase(BaseModel):
    first_name: str
    last_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    project: Optional[str] = None
    project_id: Optional[str] = None
    pipeline_category: Optional[str] = None
    lead_status: Optional[str] = "Open"
    lead_source: Optional[str] = None
    original_fw_status: Optional[str] = None
    is_rnr: bool = False
    budget: Optional[str] = None
    configuration: Optional[str] = None
    location: Optional[str] = None
    ethnicity: Optional[str] = None
    designation: Optional[str] = None
    reason_for_purchase: Optional[str] = None
    possession_requirement: Optional[str] = None
    current_residence_type: Optional[str] = None
    campaign_name: Optional[str] = None
    presales_agent: Optional[str] = None
    presales_description: Optional[str] = None
    next_action_date: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_to_name: Optional[str] = None


class LeadCreate(LeadBase):
    model_config = ConfigDict(extra="ignore")


class LeadUpdatePatch(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    project: Optional[str] = None
    pipeline_category: Optional[str] = None
    lead_status: Optional[str] = None
    lead_source: Optional[str] = None
    budget: Optional[str] = None
    configuration: Optional[str] = None
    location: Optional[str] = None
    ethnicity: Optional[str] = None
    designation: Optional[str] = None
    reason_for_purchase: Optional[str] = None
    possession_requirement: Optional[str] = None
    current_residence_type: Optional[str] = None
    campaign_name: Optional[str] = None
    presales_agent: Optional[str] = None
    presales_description: Optional[str] = None
    next_action_date: Optional[str] = None
    assigned_to: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_to_name: Optional[str] = None


class LeadResponse(LeadBase):
    model_config = ConfigDict(extra="ignore")
    id: str
    normalized_phone: Optional[str] = None
    temperature: str = "Warm"
    intent: str = "Unknown"
    vip: bool = False
    assigned_to: Optional[str] = None
    ai_persona_summary: Optional[str] = None
    strategic_next_moves: List[Dict[str, Any]] = Field(default_factory=list)
    ai_grounded_profile: Optional[Dict[str, str]] = None
    ai_last_generated_at: Optional[datetime] = None
    ai_configured: Optional[bool] = None
    ai_stale: Optional[bool] = None
    ai_generation_pending: Optional[bool] = None
    context_updates: List[dict] = []
    created_at: datetime
    updated_at: datetime


async def resolve_user_id_by_full_name(full_name: Optional[str]) -> Optional[str]:
    if not full_name:
        return None
    user = await db.users.find_one({"full_name": full_name}, {"_id": 0, "id": 1})
    return user.get("id") if user else None


class CampaignBase(BaseModel):
    name: str
    agent_type: str
    agent_prompt: Optional[str] = None
    filters: dict = {}
    lead_count: int = 0


class CampaignCreate(CampaignBase):
    lead_ids: List[str] = []


class CampaignResponse(CampaignBase):
    model_config = ConfigDict(extra="ignore")
    id: str
    status: str = "draft"
    created_at: datetime
    leads: List[dict] = []
    stats: dict = {}


class AssignmentRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    rule_type: str
    config: dict = {}
    is_active: bool = True


class AlertConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    alert_type: str
    threshold_hours: int = 24
    notification_channels: List[str] = ["email"]
    is_active: bool = True


class CallSummary(BaseModel):
    lead_id: str
    transcript: str
    summary: Optional[str] = None
    intent_level: str = "neutral"
    key_points: List[str] = []
    next_steps: Optional[str] = None


class WhatsAppMessage(BaseModel):
    destination: str
    message_type: str = "text"
    text: Optional[str] = None
    template_id: Optional[str] = None
    template_params: Optional[List[str]] = None
    media_url: Optional[str] = None
    media_filename: Optional[str] = None


class WhatsAppMessageResponse(BaseModel):
    status: str
    message_id: Optional[str] = None
    error: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


# NOTE: Additional request/response models exist in server.py today; they will be moved
# into this module as part of the router split to preserve behavior.


# ==================== AUTH HELPERS / DEPENDENCIES ====================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if user is None:
            raise credentials_exception
        token_sid = payload.get("sid")
        db_sid = user.get("current_session_id")
        if db_sid and token_sid != db_sid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session invalidated. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise credentials_exception


# ==================== GENERIC HELPERS (copied from server.py) ====================

def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("91") and len(digits) > 10:
        digits = digits[2:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits[-10:] if len(digits) >= 10 else digits


def get_time_greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good Morning"
    if hour < 17:
        return "Good Afternoon"
    return "Good Evening"


def determine_lead_temperature(lead: dict) -> str:
    status_val = lead.get("lead_status", "").lower().strip()
    if status_val in ["qualified", "hot", "interested", "site visit completed", "advance paid", "negotiation"]:
        return "Hot"
    if status_val in ["open", "new", "contacted", "follow up 1", "follow up 2", "site visit scheduled"]:
        return "Warm"
    return "Cold"


def determine_lead_intent(lead: dict) -> str:
    reason = (lead.get("reason_for_purchase") or "").lower()
    if "invest" in reason or "rental" in reason:
        return "Investor"
    if "self" in reason or "own" in reason or "live" in reason:
        return "End User"
    return "Unknown"


def is_vip_lead(lead: dict) -> bool:
    budget = (lead.get("budget") or "").lower()
    if "5 cr" in budget or "5cr" in budget or ">5" in budget or "5+" in budget:
        return True
    if "10" in budget or "15" in budget or "20" in budget:
        return True
    return False


def generate_ai_persona(lead: dict) -> str:
    name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
    designation = lead.get("designation", "Professional")
    location = lead.get("location", "Chennai")
    budget = lead.get("budget", "Not specified")
    intent = lead.get("intent", "Unknown")
    project = lead.get("project", "Not specified")
    return (
        f"{name} is a {designation} based in {location} with a budget range of {budget}. "
        f"Profile indicates {intent} intent with interest in {project}. {lead.get('presales_description', '')}"
    )


# ==================== REMINDERS (kept in shared state) ====================

reminder_task = None


async def reminder_scheduler(process_reminders_func):
    """Run reminder engine every hour"""
    while True:
        try:
            await asyncio.sleep(3600)
            await process_reminders_func()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Reminder scheduler error: {e}")
            await asyncio.sleep(60)

