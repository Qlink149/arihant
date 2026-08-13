import os
import uuid
import jwt
import bcrypt
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer

from crm.models.schemas import (
    AlertConfig,
    AssignmentRule,
    CallSummary,
    CampaignBase,
    CampaignCreate,
    CampaignResponse,
    LeadBase,
    LeadCreate,
    LeadResponse,
    LeadUpdatePatch,
    RefreshTokenRequest,
    Token,
    UserBase,
    UserCreate,
    UserResponse,
    WhatsAppMessage,
    WhatsAppMessageResponse,
)
from crm.utils.helpers import (
    coerce_datetime,
    determine_lead_intent,
    generate_ai_persona,
    get_time_greeting,
    iso_utc_now,
    is_vip_lead,
    normalize_phone,
    utc_now,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env")


# MongoDB connection
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]


# JWT Configuration
SECRET_KEY = os.environ.get("SECRET_KEY", "arihant-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))
REFRESH_TOKEN_EXPIRE_DAYS = 7


# Gupshup WhatsApp Configuration (legacy — kept for dead-code reference)
GUPSHUP_TOKEN = os.environ.get("GUPSHUP_TOKEN", "")
GUPSHUP_API_KEY = os.environ.get("GUPSHUP_API_KEY", "")
GUPSHUP_APP_ID = os.environ.get("GUPSHUP_APP_ID", "")
GUPSHUP_SOURCE_PHONE = os.environ.get("GUPSHUP_SOURCE_PHONE", "")
GUPSHUP_APP_NAME = os.environ.get("GUPSHUP_APP_NAME", "ArihantSalesIntelligence")
GUPSHUP_BASE_URL = "https://api.gupshup.io"
GUPSHUP_PARTNER_URL = "https://partner.gupshup.io"

# WATI WhatsApp Configuration
# WHATSAPP_PROVIDER: 'disabled' (default) | 'wati'
# Keep disabled until client delivers: approved templates, webhook, token, test numbers.
WHATSAPP_PROVIDER = os.environ.get("WHATSAPP_PROVIDER", "disabled")
WATI_API_ENDPOINT = os.environ.get("WATI_API_ENDPOINT", "")
WATI_API_TOKEN = os.environ.get("WATI_API_TOKEN", "")
WATI_CHANNEL_PHONE = os.environ.get("WATI_CHANNEL_PHONE", "919894474820")
# Public base URL of this backend (used to build static PDF URLs sent to WATI)
# Example: https://api.claraai.tech
# Must have no trailing slash.
WATI_BASE_URL = os.environ.get("WATI_BASE_URL", "").rstrip("/")
# Legacy single-URL var — kept for backward compat, no longer used by send_brochure
WATI_BROCHURE_PDF_URL = os.environ.get("WATI_BROCHURE_PDF_URL", "")

# Meta Conversions API (CAPI) — QualifiedLead events
# Leave META_TEST_EVENT_CODE empty in production; set it only for Events Manager → Test Events.
META_DATASET_ID = os.environ.get("META_DATASET_ID", "")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
META_API_VERSION = os.environ.get("META_API_VERSION", "v21.0")
META_TEST_EVENT_CODE = os.environ.get("META_TEST_EVENT_CODE", "")

# Meta Instant Form → Zapier → CRM (inbound). Form ID → project.
# Outbound CRM → Meta is CAPI above (META_ACCESS_TOKEN / META_DATASET_ID).

_DEFAULT_META_LEAD_FORM_PROJECT_MAP = {
    "2124096745052549": "reserve-16",
    "1874174036585908": "mira",
    "4309061012643289": "melange",
    "28059295887006740": "krsna",
    "1858929181319661": "vivriti",
}


def _parse_meta_lead_form_project_map() -> dict:
    import json as _json

    raw = (os.environ.get("META_LEAD_FORM_PROJECT_MAP") or "").strip()
    if not raw:
        return dict(_DEFAULT_META_LEAD_FORM_PROJECT_MAP)
    try:
        data = _json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return dict(_DEFAULT_META_LEAD_FORM_PROJECT_MAP)


META_LEAD_FORM_PROJECT_MAP: dict = _parse_meta_lead_form_project_map()

# Zapier Meta Instant Form webhook (Meta → Zap → CRM)
ZAPIER_WEBHOOK_SECRET = os.environ.get("ZAPIER_WEBHOOK_SECRET", "")

# Webflow form_submission webhook (enquiry forms → CRM)
WEBFLOW_WEBHOOK_SECRET = os.environ.get("WEBFLOW_WEBHOOK_SECRET", "")

# ── Project → Brochure PDF filename mapping ─────────────────────────────────
# Keys must match project names/IDs stored on leads (case-insensitive lookup).
# Filenames must match files in backend/static/.
PROJECT_BROCHURE_MAP: dict = {
    "melange":   "Arihant Melange Brochure.pdf",
    "mélange":   "Arihant Melange Brochure.pdf",
    "reserve-16": "Arihant Reserve16 Brochure.pdf",
    "reserve16": "Arihant Reserve16 Brochure.pdf",
    "reserve 16": "Arihant Reserve16 Brochure.pdf",
    "krsna":     "Krsna Brochure.pdf",
    "vivriti":   "Vivriti Brochure.pdf",
}

# ── Project → Starting Price (Template 2 — {{3}}) ───────────────────────────
# Format: human-readable string shown directly in WhatsApp.
PROJECT_PRICING_MAP: dict = {
    "melange":   "₹12,800/sq.ft. (basic price) + other applicable charges",
    "mélange":   "₹12,800/sq.ft. (basic price) + other applicable charges",
    "reserve-16": "₹3,500/sq.ft. (basic price) + other applicable charges",
    "reserve16": "₹3,500/sq.ft. (basic price) + other applicable charges",
    "reserve 16": "₹3,500/sq.ft. (basic price) + other applicable charges",
    "krsna":     "",   # TODO: client has not shared Krsna pricing yet
    "vivriti":   "₹13,000/sq.ft. (basic price) + other applicable charges",
}

# ── Lead → canonical project key resolution ─────────────────────────────────
# Leads store display strings like 'Saligramam Melange', 'ECR - Reserve 16',
# 'OMR - Vivriti', 'Abhiramapuram - Krishna' — often multi-valued with ';'.
# Tokens are searched as substrings of lead.project (lowercased); for
# multi-project leads the earliest match in the string wins.
_PROJECT_KEY_TOKENS: list = [
    ("mélange",    "melange"),
    ("melange",    "melange"),
    ("reserve-16", "reserve-16"),
    ("reserve 16", "reserve-16"),
    ("reserve16",  "reserve-16"),
    ("vivriti",    "vivriti"),
    ("krishna",    "krsna"),   # DB spells it 'Krishna'; brochure/pricing keys use 'krsna'
    ("krsna",      "krsna"),
    ("abhiramapuram", "krsna"),  # Krsna's location (brochure cover: 'Krsna — Abhiramapuram')
    ("abiramapuram",  "krsna"),  # common typo variant seen in DB
    ("mira",       "mira"),
    ("vipassanā",  "vipassana"),
    ("vipassana",  "vipassana"),
]


def resolve_lead_project_key(lead: dict) -> str:
    """
    Canonical project key for a lead (includes mira, vipassana).

    Prefers the already-canonical lead.project_id; falls back to scanning the
    lead.project display string. Returns '' when no known project matches.
    """
    pid = (lead.get("project_id") or "").strip().lower()
    if pid in ("melange", "reserve-16", "vivriti", "krsna", "mira", "vipassana"):
        return pid
    text = (lead.get("project") or "").lower()
    if not text:
        return ""
    best_pos = -1
    best_key = ""
    for token, key in _PROJECT_KEY_TOKENS:
        pos = text.find(token)
        if pos >= 0 and (best_pos < 0 or pos < best_pos):
            best_pos = pos
            best_key = key
    return best_key

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ==================== PROJECT REGISTRY ====================

PROJECT_REGISTRY = [
    {"id": "reserve-16", "name": "Reserve 16"},
    {"id": "krsna", "name": "Krsna"},
    {"id": "vivriti", "name": "Vivriti"},
    {"id": "melange", "name": "Mélange"},
    {"id": "mira", "name": "Mira"},
    {"id": "vipassana", "name": "Vipassanā"},
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
        await db.leads.create_index([("created_at_dt", -1)], name="leads_created_at_dt_desc")
        await db.leads.create_index([("updated_at", -1)], name="leads_updated_at_desc")
        await db.leads.create_index([("lead_status", 1), ("updated_at", -1)], name="leads_status_updatedAt")
        await db.leads.create_index([("assigned_to", 1), ("updated_at", -1)], name="leads_assignedTo_updatedAt")
        await db.leads.create_index([("lead_status", 1), ("updated_at_dt", 1)], name="leads_status_updatedAtDt")
        await db.leads.create_index(
            [("lead_status", 1), ("temperature", 1), ("updated_at_dt", 1)],
            name="leads_status_temperature_updatedAtDt",
        )
        await db.leads.create_index([("lead_status", 1), ("visit_date_dt", 1)], name="leads_status_visitDateDt")
        await db.leads.create_index(
            [("next_action_date", 1), ("lead_status", 1)],
            name="leads_nextActionDate_status",
        )

        # tasks
        await db.tasks.create_index([("id", 1)], unique=True, name="tasks_id_uq")
        await db.tasks.create_index([("lead_id", 1), ("due_date", 1)], name="tasks_leadId_dueDate")
        await db.tasks.create_index([("assigned_to", 1), ("status", 1), ("due_date", 1)], name="tasks_assigned_status_dueDate")
        await db.tasks.create_index([("status", 1), ("due_date", 1)], name="tasks_status_dueDate")
        await db.tasks.create_index([("assigned_user_id", 1), ("status", 1), ("due_at_dt", 1)], name="tasks_assignedUser_status_dueAtDt")
        await db.tasks.create_index([("dedupe_key", 1)], unique=True, sparse=True, name="tasks_dedupeKey_uq_sparse")

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
        # Prefer unique sparse wati_message_id for idempotent upserts. Drop legacy non-unique
        # index if present so create_index can establish the unique constraint.
        try:
            await db.whatsapp_messages.drop_index("whatsapp_messages_watiId")
        except Exception:
            pass
        try:
            await db.whatsapp_messages.create_index(
                [("wati_message_id", 1)],
                unique=True,
                sparse=True,
                name="whatsapp_messages_watiId_uq_sparse",
            )
        except Exception as idx_err:
            logger.warning(
                f"Unique wati_message_id index failed (likely duplicate legacy ids): {idx_err}. "
                "Falling back to non-unique sparse index."
            )
            try:
                await db.whatsapp_messages.create_index(
                    [("wati_message_id", 1)],
                    sparse=True,
                    name="whatsapp_messages_watiId",
                )
            except Exception:
                pass
        await db.whatsapp_messages.create_index([("source", 1), ("created_at", -1)], name="whatsapp_messages_source_createdAt")
        await db.whatsapp_messages.create_index([("destination", 1), ("created_at", -1)], name="whatsapp_messages_destination_createdAt")
        await db.whatsapp_messages.create_index(
            [("destination", 1), ("created_at_dt", -1)],
            name="whatsapp_messages_destination_createdAtDt",
        )
        await db.whatsapp_messages.create_index(
            [("source", 1), ("created_at_dt", -1)],
            name="whatsapp_messages_source_createdAtDt",
        )
        await db.whatsapp_messages.create_index(
            [("direction", 1), ("source", 1), ("created_at_dt", -1)],
            name="whatsapp_messages_dir_source_createdAtDt",
        )

        # Per-user WhatsApp inbox read receipts (unread badges)
        await db.whatsapp_thread_reads.create_index(
            [("user_id", 1), ("peer_phone", 1)],
            unique=True,
            name="whatsapp_thread_reads_user_peer_uq",
        )

        # lead_transfers
        await db.lead_transfers.create_index([("id", 1)], unique=True, name="lead_transfers_id_uq")
        await db.lead_transfers.create_index([("to_rep", 1), ("acknowledged", 1), ("transferred_at", -1)], name="lead_transfers_to_ack_transferredAt")
        await db.lead_transfers.create_index([("to_user_id", 1), ("acknowledged", 1), ("transferred_at_dt", -1)], name="lead_transfers_toUser_ack_transferredAtDt")
        await db.lead_transfers.create_index([("lead_id", 1), ("transferred_at", -1)], name="lead_transfers_lead_transferredAt")
        await db.lead_transfers.create_index(
            [("from_user_id", 1), ("acknowledged", 1), ("transferred_at_dt", -1)],
            name="lead_transfers_fromUser_ack_transferredAtDt",
        )

        await db.lead_filter_views.create_index([("user_id", 1)], name="lead_filter_views_user_id")

        # lead_view_grants — temporary view-only access (exact lookup); TTL auto-expire
        await db.lead_view_grants.create_index(
            [("user_id", 1), ("lead_id", 1)],
            unique=True,
            name="lead_view_grants_user_lead_uq",
        )
        await db.lead_view_grants.create_index(
            "expires_at_dt",
            expireAfterSeconds=0,
            name="lead_view_grants_ttl",
        )
        await db.lead_view_grants.create_index(
            [("lead_id", 1), ("expires_at_dt", -1)],
            name="lead_view_grants_lead_expires",
        )

        # lead_events (audit log)
        await db.lead_events.create_index([("id", 1)], unique=True, name="lead_events_id_uq")
        await db.lead_events.create_index([("lead_id", 1), ("created_at_dt", -1)], name="lead_events_lead_createdAtDt")
        await db.lead_events.create_index([("event_type", 1), ("created_at_dt", -1)], name="lead_events_type_createdAtDt")

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

        # cron_locks — one doc per job + TTL auto-expire at expires_at
        await db.cron_locks.create_index(
            [("job", 1)],
            unique=True,
            name="cron_locks_job_uq",
        )
        await db.cron_locks.create_index(
            "expires_at",
            expireAfterSeconds=0,
            name="cron_locks_ttl",
        )

        # user_activity — active agent routing
        await db.user_activity.create_index(
            [("user_id", 1), ("last_heartbeat_dt", -1)],
            name="user_activity_routing",
        )

        # app_settings — frequent key lookups
        await db.app_settings.create_index(
            "key",
            unique=True,
            sparse=True,
            name="app_settings_key",
        )

        # meta_capi_logs — CAPI send audit (no raw PII)
        await db.meta_capi_logs.create_index(
            [("lead_id", 1), ("created_at_dt", -1)],
            name="meta_capi_logs_lead_createdAtDt",
        )
        await db.meta_capi_logs.create_index(
            [("event_id", 1)],
            name="meta_capi_logs_eventId",
        )

        # zapier_leads_logs — inbound Meta→Zapier webhook audit
        await db.zapier_leads_logs.create_index(
            [("leadgen_id", 1)],
            unique=True,
            name="zapier_leads_logs_leadgen_id_uq",
        )
        await db.zapier_leads_logs.create_index(
            [("created_at_dt", -1)],
            name="zapier_leads_logs_createdAtDt",
        )

        # webflow_leads_logs — inbound Webflow enquiry webhook audit
        await db.webflow_leads_logs.create_index(
            [("submission_id", 1)],
            unique=True,
            name="webflow_leads_logs_submission_id_uq",
        )
        await db.webflow_leads_logs.create_index(
            [("created_at_dt", -1)],
            name="webflow_leads_logs_createdAtDt",
        )

        # api_keys — multi-tenant public lead intake
        await db.api_keys.create_index(
            [("id", 1)],
            unique=True,
            name="api_keys_id_uq",
        )
        await db.api_keys.create_index(
            [("key_hash", 1)],
            unique=True,
            name="api_keys_key_hash_uq",
        )
        await db.api_keys.create_index(
            [("is_active", 1), ("project_id", 1)],
            name="api_keys_active_project",
        )

        # lead_intake_logs — public intake audit
        await db.lead_intake_logs.create_index(
            [("created_at_dt", -1)],
            name="lead_intake_logs_createdAtDt",
        )
        await db.lead_intake_logs.create_index(
            [("api_key_id", 1), ("created_at_dt", -1)],
            name="lead_intake_logs_key_createdAtDt",
        )
        await db.lead_intake_logs.create_index(
            [("project_id", 1), ("created_at_dt", -1)],
            name="lead_intake_logs_project_createdAtDt",
        )
        await db.lead_intake_logs.create_index(
            [("lead_id", 1), ("created_at_dt", -1)],
            name="lead_intake_logs_lead_createdAtDt",
        )

        # Intake soft-dedupe helpers
        await db.leads.create_index(
            [("project_id", 1), ("email", 1), ("created_at_dt", -1)],
            name="leads_project_email_createdAtDt",
        )
        await db.leads.create_index(
            [("project_id", 1), ("normalized_phone", 1), ("created_at_dt", -1)],
            name="leads_project_normPhone_createdAtDt",
        )

        logger.info("DB indexes ensured")
    except Exception as e:
        logger.critical(f"FATAL: Index creation failed: {e}. DB may be misconfigured.")


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


async def resolve_user_id_by_full_name(full_name: Optional[str]) -> Optional[str]:
    if not full_name:
        return None
    user = await db.users.find_one({"full_name": full_name}, {"_id": 0, "id": 1})
    return user.get("id") if user else None


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
        if payload.get("type") != "access":
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

