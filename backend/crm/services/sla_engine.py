"""
Event-driven SLA engine: bulk Mongo writes, BSON datetime queries, idempotent flags + task dedupe.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from pymongo import InsertOne, ReturnDocument, UpdateOne
from pymongo.errors import BulkWriteError, DuplicateKeyError

from crm.constants.lead_kpi import RNR_STATUS_REGEX
from crm.constants.task import TASK_REMINDER_METHOD_DEFAULT
from crm.constants.lead_status import (
    SV_FOLLOWUP_1_STATUS_QUERY,
    SV_FOLLOWUP_2_STATUS_QUERY,
    SV_FOLLOWUP_STATUS_QUERY,
    sla_paused_exclusion_clause,
    terminal_exclusion_clause,
)
from crm.core.state import db, logger
from crm.services.assignment_router import reassign_new_lead
from crm.services.lead_sla_utils import is_booking_progress_status
from crm.services.notifications_stream import notifications_stream
from crm.utils.business_time import business_seconds_elapsed, is_business_hours_ist as _bh_ist
from crm.utils.helpers import coerce_datetime, iso_utc_now, utc_now

IST = ZoneInfo("Asia/Kolkata")
_CRON_LOCK_JOB = "process_slas"
_CRON_LOCK_TTL_MINUTES = 4

# Status matchers (case-insensitive)
_RE_CONTACTED = {"$regex": r"^\s*contacted\s*$", "$options": "i"}
_RE_NURTURING = {"$regex": r"nurtur", "$options": "i"}
_RE_INTERESTED = {"$regex": r"^\s*interested\s*$", "$options": "i"}
_RE_VISIT_SCHEDULED = {"$regex": r"(site\s*)?visit\s*scheduled", "$options": "i"}
_RE_VISIT_COMPLETED = {"$regex": r"(site\s*)?visit\s*completed", "$options": "i"}
_RE_VISIT_COMPLETED_PY = re.compile(r"(site\s*)?visit\s*completed", re.IGNORECASE)
_RE_NEGOTIATION = {"$regex": r"negotiat", "$options": "i"}
_RE_GONE_COLD = {"$regex": r"gone\s*cold", "$options": "i"}
_RE_FUTURE_PROSPECT = {"$regex": r"future\s*prospect", "$options": "i"}
_RE_REENGAGED = {"$regex": r"re[\s\-]*engaged", "$options": "i"}
_SV_FOLLOWUP_STATUS = SV_FOLLOWUP_STATUS_QUERY


async def _paginate_leads(
    collection,
    query: dict,
    *,
    projection: Optional[dict] = None,
    batch_size: int = 200,
) -> AsyncIterator[List[dict]]:
    """Yield lead batches using cursor pagination (stable sort on Mongo _id)."""
    proj = projection if projection is not None else {"_id": 0}
    cursor = collection.find(query, proj).sort("_id", 1)
    batch: List[dict] = []
    async for doc in cursor:
        batch.append(doc)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _new_lead_filter() -> dict:
    return {
        "$or": [
            {"lead_status": {"$regex": r"^\s*new\s*$", "$options": "i"}},
            {
                "$and": [
                    {"lead_status": {"$regex": r"^\s*open\s*$", "$options": "i"}},
                    {"original_fw_status": {"$regex": r"^\s*new\s*$", "$options": "i"}},
                ]
            },
        ]
    }


def _rnr_status_filter() -> dict:
    return {
        "$or": [
            {"is_rnr": True},
            {"lead_status": {"$regex": RNR_STATUS_REGEX}},
            {"original_fw_status": {"$regex": RNR_STATUS_REGEX}},
        ]
    }


def _flag_not_set(dot_path: str) -> dict:
    return {dot_path: {"$exists": False}}


def _missing_dt(field: str) -> dict:
    return {"$or": [{field: {"$exists": False}}, {field: None}]}


def _entered_at_or_updated_fallback(field: str, cutoff: datetime) -> dict:
    return {
        "$or": [
            {field: {"$lt": cutoff}},
            {field: {"$exists": False}, "updated_at_dt": {"$lt": cutoff}},
            {field: None, "updated_at_dt": {"$lt": cutoff}},
        ],
    }


# Max RNR reminder buckets per RNR stay (4 business hours each).
_RNR_REMINDER_MAX_BUCKETS = 3
_RNR_REMINDER_OPEN_STATUSES = ("pending", "in_progress")


def _rnr_open_reminder_query(lead_id: str) -> dict:
    """Match any still-open SLA RNR reminder for a lead."""
    return {
        "lead_id": lead_id,
        "source": "sla",
        "sla_rule": "rnr",
        "status": {"$in": list(_RNR_REMINDER_OPEN_STATUSES)},
        "sla_threshold": {"$regex": r"^reminder_"},
    }


def is_business_hours_ist(now_dt: datetime) -> bool:
    return _bh_ist(now_dt)


def is_new_lead_intake_window_ist(created_at_dt: datetime) -> bool:
    """
    Client rule: 2h hard-cap (admin alert) only applies to leads created between
    10:00–17:00 IST (Mon–Sat). The alert itself may fire after-hours.
    """
    ist = created_at_dt.astimezone(IST)
    if ist.weekday() == 6:
        return False
    minutes = ist.hour * 60 + ist.minute
    return (10 * 60) <= minutes <= (17 * 60)


def build_task_doc(
    *,
    lead: dict,
    description: str,
    dedupe_key: str,
    now_dt: datetime,
    now_iso: str,
    name_to_user_id: Dict[str, str],
    escalation_user: Optional[dict] = None,
    priority: str = "medium",
    due_date: Optional[str] = None,
    due_time: str = "09:00",
    sla_rule: Optional[str] = None,
    sla_threshold: Optional[str] = None,
) -> Optional[dict]:
    assigned = lead.get("assigned_to") or lead.get("presales_agent") or ""
    assigned_user_id = lead.get("assigned_user_id")
    if not assigned_user_id and assigned:
        assigned_user_id = name_to_user_id.get(assigned.strip())

    if escalation_user and escalation_user.get("id"):
        assigned_user_id = escalation_user["id"]
        if escalation_user.get("full_name"):
            assigned = escalation_user["full_name"]
    if not assigned_user_id:
        return None

    due_date = due_date or now_dt.strftime("%Y-%m-%d")
    due_at_dt = datetime.fromisoformat(f"{due_date}T{due_time}:00").replace(tzinfo=timezone.utc)
    lead_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()

    doc = {
        "id": str(uuid.uuid4()),
        "lead_id": lead["id"],
        "lead_name": lead_name,
        "project": (lead.get("project") or "").strip(),
        "description": description,
        "due_date": due_date,
        "due_time": due_time,
        "due_at_dt": due_at_dt,
        "priority": priority,
        "reminder_method": TASK_REMINDER_METHOD_DEFAULT,
        "assigned_to": assigned,
        "assigned_to_name": assigned,
        "assigned_user_id": assigned_user_id,
        "status": "pending",
        "created_by": "SLA Engine",
        "created_by_user_id": None,
        "created_at": now_iso,
        "created_at_dt": now_dt,
        "dedupe_key": dedupe_key,
        "source": "sla",
    }
    if sla_rule:
        doc["sla_rule"] = sla_rule
    if sla_threshold:
        doc["sla_threshold"] = sla_threshold
    return doc


class SLAEngineService:
    def __init__(self) -> None:
        self._task_ops: List[InsertOne] = []
        self._notif_ops: List[InsertOne] = []
        self._lead_ops: List[UpdateOne] = []
        self._event_ops: List[InsertOne] = []
        self._notif_publish: List[Tuple[str, dict]] = []
        self._admin_email_ops: List[dict] = []
        self._summary: Dict[str, int] = {}
        self._skipped_no_assignee = 0
        self._escalation_targets: Dict[str, dict] = {}
        self._terminal_exclusion = terminal_exclusion_clause()

    def _rule_query(self, base: dict) -> dict:
        return {
            "$and": [
                base,
                {"lead_status": self._terminal_exclusion},
                {"sla_paused": sla_paused_exclusion_clause()},
            ]
        }

    def _bump(self, key: str, n: int = 1) -> None:
        self._summary[key] = self._summary.get(key, 0) + n

    def _queue_admin_notification(
        self,
        lead: dict,
        title: str,
        message: str,
        dedupe_key: str,
        now_dt: datetime,
        now_iso: str,
    ) -> None:
        admin = self._escalation_targets.get("admin")
        if not admin or not admin.get("id"):
            return
        notif = {
            "id": str(uuid.uuid4()),
            "type": "sla_alert",
            "notification_type": "escalation",
            "title": title,
            "message": message,
            "lead_id": lead["id"],
            "lead_name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
            "task_id": None,
            "stage": "sla",
            "sla_threshold": "",
            "severity": "high",
            "urgency": "action_needed",
            "assigned_to": admin.get("full_name", ""),
            "recipient_name": admin.get("full_name", ""),
            "recipient_user_id": admin["id"],
            "is_read": False,
            "fired_at_dt": now_dt,
            "created_at": now_iso,
            "created_at_dt": now_dt,
            "dedupe_key": dedupe_key,
        }
        self._notif_ops.append(InsertOne(notif))
        self._notif_publish.append((admin["id"], notif))

    def _queue_task(
        self,
        lead: dict,
        description: str,
        dedupe_key: str,
        flag_path: str,
        now_dt: datetime,
        now_iso: str,
        name_to_user_id: Dict[str, str],
        escalation_target: Optional[str] = None,
        priority: str = "medium",
        sla_rule: str = "",
        sla_threshold: str = "",
        extra_lead_set: Optional[dict] = None,
        due_date: Optional[str] = None,
    ) -> None:
        escalation_user = None
        if escalation_target:
            escalation_user = self._escalation_targets.get(escalation_target)
        task = build_task_doc(
            lead=lead,
            description=description,
            dedupe_key=dedupe_key,
            now_dt=now_dt,
            now_iso=now_iso,
            name_to_user_id=name_to_user_id,
            escalation_user=escalation_user,
            priority=priority,
            due_date=due_date,
            sla_rule=sla_rule,
            sla_threshold=sla_threshold,
        )
        if not task:
            self._skipped_no_assignee += 1
            return
        self._task_ops.append(InsertOne(task))

        due_str = task.get("due_date") or now_dt.strftime("%Y-%m-%d")
        if task.get("due_time"):
            due_str += f" at {task['due_time']}"
        notif_type = "escalation" if escalation_target else "action_required"
        notif = {
            "id": str(uuid.uuid4()),
            "type": "sla_task",
            "notification_type": notif_type,
            "title": f"SLA: {description[:50]}",
            "message": f"Due {due_str} for {task.get('lead_name', '')}",
            "lead_id": lead["id"],
            "lead_name": task.get("lead_name", ""),
            "task_id": task["id"],
            "stage": sla_rule,
            "sla_threshold": sla_threshold,
            "severity": "high" if priority == "high" else "medium" if priority == "medium" else "low",
            "urgency": "action_needed",
            "assigned_to": task.get("assigned_to", ""),
            "recipient_name": task.get("assigned_to", ""),
            "recipient_user_id": task.get("assigned_user_id", ""),
            "is_read": False,
            "fired_at_dt": now_dt,
            "created_at": now_iso,
            "created_at_dt": now_dt,
            "dedupe_key": f"notif:{dedupe_key}",
        }
        self._notif_ops.append(InsertOne(notif))
        if notif.get("recipient_user_id"):
            self._notif_publish.append((notif["recipient_user_id"], notif))

        self._event_ops.append(
            InsertOne(
                {
                    "id": str(uuid.uuid4()),
                    "event_type": "sla_action",
                    "lead_id": lead["id"],
                    "actor_user_id": "",
                    "actor_name": "SLA Engine",
                    "payload": {
                        "action": "task_created",
                        "sla_rule": sla_rule,
                        "sla_threshold": sla_threshold,
                        "dedupe_key": dedupe_key,
                        "task_id": task["id"],
                        "assigned_user_id": task.get("assigned_user_id"),
                    },
                    "created_at": now_iso,
                    "created_at_dt": now_dt,
                }
            )
        )

        self._lead_ops.append(
            UpdateOne(
                {"id": lead["id"]},
                {
                    "$set": {
                        flag_path: now_dt,
                        "updated_at": now_iso,
                        "updated_at_dt": now_dt,
                        **(extra_lead_set or {}),
                    }
                },
            )
        )
        self._bump(f"task:{sla_rule}:{sla_threshold}")

    def _queue_lead_mutation(
        self,
        lead_id: str,
        set_fields: dict,
        flag_path: str,
        now_dt: datetime,
        now_iso: str,
        summary_key: str,
    ) -> None:
        patch = {**set_fields, flag_path: now_dt, "updated_at": now_iso, "updated_at_dt": now_dt}
        self._lead_ops.append(UpdateOne({"id": lead_id}, {"$set": patch}))
        self._event_ops.append(
            InsertOne(
                {
                    "id": str(uuid.uuid4()),
                    "event_type": "sla_action",
                    "lead_id": lead_id,
                    "actor_user_id": "",
                    "actor_name": "SLA Engine",
                    "payload": {"action": "lead_mutation", "set_fields": set_fields, "flag_path": flag_path},
                    "created_at": now_iso,
                    "created_at_dt": now_dt,
                }
            )
        )
        self._bump(summary_key)

    async def _acquire_cron_lock(self, now_dt: datetime) -> bool:
        """
        Acquire a single-job lock. Relies on unique index on cron_locks.job.
        Only succeeds when we create/refresh an expired lock ourselves.
        """
        expires = now_dt + timedelta(minutes=_CRON_LOCK_TTL_MINUTES)
        try:
            result = await db.cron_locks.find_one_and_update(
                {
                    "job": _CRON_LOCK_JOB,
                    "$or": [
                        {"expires_at": {"$lt": now_dt}},
                        {"expires_at": {"$exists": False}},
                    ],
                },
                {
                    "$set": {
                        "job": _CRON_LOCK_JOB,
                        "locked_at": now_dt,
                        "expires_at": expires,
                    }
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            # Another runner holds a non-expired lock (unique job index)
            return False
        except Exception as e:
            logger.warning("SLA cron lock not acquired: %s", e)
            return False
        locked_at = coerce_datetime((result or {}).get("locked_at"))
        if locked_at and locked_at.tzinfo is None:
            locked_at = locked_at.replace(tzinfo=timezone.utc)
        if locked_at is None:
            return False
        # Exact match only — no soft <2s window that allows double runners
        return locked_at == now_dt

    async def _load_name_to_user_id(self) -> Dict[str, str]:
        users = await db.users.find({}, {"_id": 0, "id": 1, "full_name": 1}).to_list(500)
        return {u["full_name"]: u["id"] for u in users if u.get("full_name") and u.get("id")}

    async def _load_escalation_targets(self) -> Dict[str, dict]:
        admin = await db.users.find_one(
            {"role": {"$regex": r"^\s*admin\s*$", "$options": "i"}},
            {"_id": 0, "id": 1, "full_name": 1, "role": 1},
        )
        manager = await db.users.find_one(
            {"role": {"$regex": r"^\s*manager\s*$", "$options": "i"}},
            {"_id": 0, "id": 1, "full_name": 1, "role": 1},
        )
        out: Dict[str, dict] = {}
        if admin and admin.get("id"):
            out["admin"] = admin
        if manager and manager.get("id"):
            out["manager"] = manager
        return out

    async def _process_rule_new(self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]) -> None:
        base = _new_lead_filter()

        if is_business_hours_ist(now_dt):
            query_30m = self._rule_query(
                {**base, **_flag_not_set("sla_flags.new.reassign_30m_at_dt")}
            )
            async for batch in _paginate_leads(db.leads, query_30m):
                for lead in batch:
                    created = coerce_datetime(lead.get("created_at_dt")) or now_dt
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if business_seconds_elapsed(created, now_dt) < 1800:
                        continue
                    await reassign_new_lead(lead["id"])
                    self._queue_lead_mutation(
                        lead["id"],
                        {},
                        "sla_flags.new.reassign_30m_at_dt",
                        now_dt,
                        now_iso,
                        "mutation:new:auto_reassign_30m",
                    )

        cutoff_2h = now_dt - timedelta(hours=2)
        query_2h = self._rule_query(
            {
                **base,
                "created_at_dt": {"$lt": cutoff_2h},
                **_flag_not_set("sla_flags.new.alert_admin_2h_at_dt"),
            }
        )
        async for batch in _paginate_leads(db.leads, query_2h):
            for lead in batch:
                created = coerce_datetime(lead.get("created_at_dt")) or now_dt
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if not is_new_lead_intake_window_ist(created):
                    continue
                dedupe = f"sla:new:2h:{lead['id']}"
                self._queue_task(
                    lead,
                    "Alert Admin",
                    dedupe,
                    "sla_flags.new.alert_admin_2h_at_dt",
                    now_dt,
                    now_iso,
                    name_to_user_id,
                    escalation_target="admin",
                    priority="high",
                    sla_rule="new",
                    sla_threshold="2h",
                )

    async def _process_rule_rnr(self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]) -> None:
        if not is_business_hours_ist(now_dt):
            return

        status_base = _rnr_status_filter()
        today_ist = now_dt.astimezone(IST).date().isoformat()
        query_reminder = self._rule_query(status_base)
        async for batch in _paginate_leads(db.leads, query_reminder):
            for lead in batch:
                updated = coerce_datetime(lead.get("rnr_entered_at_dt")) or coerce_datetime(lead.get("updated_at_dt")) or now_dt
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                elapsed_biz = business_seconds_elapsed(updated, now_dt)
                periods = elapsed_biz // (4 * 3600)
                if periods < 1:
                    continue
                # Lifetime cap: at most 3 reminders per RNR stay
                if periods > _RNR_REMINDER_MAX_BUCKETS:
                    periods = _RNR_REMINDER_MAX_BUCKETS
                bucket = str(periods)
                flag = f"sla_flags.rnr.reminder_{bucket}_at_dt"
                rnr_flags = (lead.get("sla_flags") or {}).get("rnr") or {}
                if rnr_flags.get(f"reminder_{bucket}_at_dt"):
                    continue
                # Max one open RNR reminder at a time
                existing_open = await db.tasks.find_one(
                    _rnr_open_reminder_query(lead["id"]),
                    {"_id": 0, "id": 1},
                )
                if existing_open:
                    continue
                dedupe = f"sla:rnr:reminder:{lead['id']}:{bucket}"
                self._queue_task(
                    lead,
                    "RNR Reminder",
                    dedupe,
                    flag,
                    now_dt,
                    now_iso,
                    name_to_user_id,
                    due_date=today_ist,
                    sla_rule="rnr",
                    sla_threshold=f"reminder_{bucket}",
                )

        for hours, threshold, desc, target in (
            (24, "24h", "RNR Escalation — Admin Review Required", "admin"),
            (48, "48h", "RNR Escalation — Admin Review Required", "admin"),
            (15 * 24, "15d", "RNR Lead — 15 Days Uncontacted — High Priority Admin Review", "admin"),
        ):
            cutoff = now_dt - timedelta(hours=hours)
            flag = f"sla_flags.rnr.escalate_{threshold}_at_dt"
            query = self._rule_query(
                {
                    **status_base,
                    **_entered_at_or_updated_fallback("rnr_entered_at_dt", cutoff),
                    **_flag_not_set(flag),
                }
            )
            async for batch in _paginate_leads(db.leads, query):
                for lead in batch:
                    priority = "high" if threshold == "15d" else "medium"
                    dedupe = f"sla:rnr:escalate:{threshold}:{lead['id']}"
                    self._queue_task(
                        lead,
                        desc,
                        dedupe,
                        flag,
                        now_dt,
                        now_iso,
                        name_to_user_id,
                        escalation_target=target,
                        priority=priority,
                        due_date=today_ist,
                        sla_rule="rnr",
                        sla_threshold=threshold,
                    )

    async def _process_rule_contacted(self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]) -> None:
        for hours, threshold, desc, priority, target in (
            (48, "48h", "Follow up — log outcome for this lead", "medium", None),
            (72, "72h", "Admin Alert — Contacted lead unactioned 72h", "high", "admin"),
        ):
            cutoff = now_dt - timedelta(hours=hours)
            flag = f"sla_flags.contacted.{threshold}_at_dt"
            query = self._rule_query(
                {
                    "lead_status": _RE_CONTACTED,
                    **_entered_at_or_updated_fallback("contacted_at_dt", cutoff),
                    **_flag_not_set(flag),
                }
            )
            async for batch in _paginate_leads(db.leads, query):
                for lead in batch:
                    dedupe = f"sla:contacted:{threshold}:{lead['id']}"
                    self._queue_task(
                        lead,
                        desc,
                        dedupe,
                        flag,
                        now_dt,
                        now_iso,
                        name_to_user_id,
                        escalation_target=target,
                        priority=priority,
                        sla_rule="contacted",
                        sla_threshold=threshold,
                    )

    async def _process_rule_nurturing(self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]) -> None:
        cutoff_24h = now_dt - timedelta(hours=24)
        query_warm = self._rule_query(
            {
                "lead_status": _RE_NURTURING,
                "updated_at_dt": {"$lt": cutoff_24h},
                "$or": [
                    {"temperature": {"$exists": False}},
                    {"temperature": None},
                    {"temperature": ""},
                ],
                **_flag_not_set("sla_flags.nurturing.temperature_warm_at_dt"),
            }
        )
        async for batch in _paginate_leads(db.leads, query_warm, projection={"_id": 0, "id": 1}):
            for lead in batch:
                self._queue_lead_mutation(
                    lead["id"],
                    {"temperature": "Warm"},
                    "sla_flags.nurturing.temperature_warm_at_dt",
                    now_dt,
                    now_iso,
                    "mutation:nurturing:warm",
                )

        query_nurture = self._rule_query({"lead_status": _RE_NURTURING})
        async for batch in _paginate_leads(db.leads, query_nurture):
            for lead in batch:
                entered = coerce_datetime(lead.get("nurture_entered_at_dt")) or coerce_datetime(lead.get("updated_at_dt")) or now_dt
                if entered.tzinfo is None:
                    entered = entered.replace(tzinfo=timezone.utc)
                if (now_dt - entered) > timedelta(days=14):
                    continue

                temp = (lead.get("temperature") or "").strip().lower()
                if temp not in {"hot", "warm"}:
                    continue

                cadence = timedelta(days=2) if temp == "hot" else timedelta(days=4)
                flags = (lead.get("sla_flags") or {}).get("nurturing") or {}
                last_key = "hot_last_task_created_at_dt" if temp == "hot" else "warm_last_task_created_at_dt"
                cycle_key = "hot_cycle" if temp == "hot" else "warm_cycle"
                last = coerce_datetime(flags.get(last_key)) or entered
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (now_dt - last) < cadence:
                    continue

                cycle = int(flags.get(cycle_key) or 0) + 1
                dedupe = f"sla:nurturing:{temp}:{lead['id']}:{cycle}"
                self._queue_task(
                    lead,
                    "Hot Lead Follow-up" if temp == "hot" else "Warm Lead Follow-up",
                    dedupe,
                    f"sla_flags.nurturing.{temp}_followup_{cycle}_at_dt",
                    now_dt,
                    now_iso,
                    name_to_user_id,
                    sla_rule="nurturing",
                    sla_threshold=f"{temp}_{'2d' if temp == 'hot' else '4d'}",
                    extra_lead_set={
                        f"sla_flags.nurturing.{last_key}": now_dt,
                        f"sla_flags.nurturing.{cycle_key}": cycle,
                    },
                )

    async def _process_rule_interested(self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]) -> None:
        """7-day reminder: surface Interested leads in Today's Follow-ups via next_action_date."""
        status_q = {"lead_status": _RE_INTERESTED}
        flag_7d = "sla_flags.interested.7d_at_dt"
        cutoff_7d = now_dt - timedelta(days=7)
        today_ist = now_dt.astimezone(IST).date().isoformat()

        query_7d = self._rule_query(
            {
                **status_q,
                **_entered_at_or_updated_fallback("interested_entered_at_dt", cutoff_7d),
                **_flag_not_set(flag_7d),
            }
        )
        async for batch in _paginate_leads(db.leads, query_7d):
            for lead in batch:
                ref = coerce_datetime(lead.get("interested_entered_at_dt")) or coerce_datetime(lead.get("updated_at_dt"))
                if not ref:
                    continue
                if ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)
                if now_dt < ref + timedelta(days=7):
                    continue
                nad = (lead.get("next_action_date") or "")[:10]
                if nad and nad > today_ist:
                    continue
                self._queue_lead_mutation(
                    lead["id"],
                    {"next_action_date": today_ist},
                    flag_7d,
                    now_dt,
                    now_iso,
                    "mutation:interested:7d_followup",
                )

    async def _process_rule_visit_scheduled(
        self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]
    ) -> None:
        status_q = {"lead_status": _RE_VISIT_SCHEDULED}

        query_missing = self._rule_query(
            {
                **status_q,
                **_missing_dt("visit_date_dt"),
                **_flag_not_set("sla_flags.visit_scheduled.missing_date_at_dt"),
            }
        )
        async for batch in _paginate_leads(db.leads, query_missing):
            for lead in batch:
                dedupe = f"sla:visit_scheduled:missing_date:{lead['id']}"
                self._queue_task(
                    lead,
                    "Missing Visit Date: Update Required",
                    dedupe,
                    "sla_flags.visit_scheduled.missing_date_at_dt",
                    now_dt,
                    now_iso,
                    name_to_user_id,
                    sla_rule="visit_scheduled",
                    sla_threshold="missing_date",
                )

        pre_cutoff = now_dt + timedelta(hours=24)
        query_pre = self._rule_query(
            {
                **status_q,
                "visit_date_dt": {"$lte": pre_cutoff, "$exists": True, "$ne": None},
                **_flag_not_set("sla_flags.visit_scheduled.pre_24h_at_dt"),
            }
        )
        async for batch in _paginate_leads(db.leads, query_pre):
            for lead in batch:
                visit_dt = coerce_datetime(lead.get("visit_date_dt"))
                if not visit_dt:
                    continue
                if visit_dt.tzinfo is None:
                    visit_dt = visit_dt.replace(tzinfo=timezone.utc)
                if now_dt < visit_dt - timedelta(hours=24):
                    continue
                dedupe = f"sla:visit_scheduled:pre_24h:{lead['id']}"
                self._queue_task(
                    lead,
                    "Send WA Reminder to Client",
                    dedupe,
                    "sla_flags.visit_scheduled.pre_24h_at_dt",
                    now_dt,
                    now_iso,
                    name_to_user_id,
                    sla_rule="visit_scheduled",
                    sla_threshold="pre_24h",
                )

        query_post = self._rule_query(
            {
                **status_q,
                "visit_date_dt": {"$exists": True, "$ne": None},
                **_flag_not_set("sla_flags.visit_scheduled.post_24h_at_dt"),
            }
        )
        async for batch in _paginate_leads(db.leads, query_post):
            for lead in batch:
                visit_dt = coerce_datetime(lead.get("visit_date_dt"))
                if not visit_dt:
                    continue
                if visit_dt.tzinfo is None:
                    visit_dt = visit_dt.replace(tzinfo=timezone.utc)
                if now_dt < visit_dt + timedelta(hours=24):
                    continue
                ls = lead.get("lead_status") or ""
                if _RE_VISIT_COMPLETED_PY.search(ls):
                    continue
                existing_t0 = await db.tasks.find_one(
                    {
                        "lead_id": lead["id"],
                        "sla_rule": "visit_completed",
                        "status": {"$in": ["pending", "in_progress"]},
                    },
                    {"_id": 0, "id": 1},
                )
                if existing_t0:
                    continue
                dedupe = f"sla:visit_scheduled:post_24h:{lead['id']}"
                self._queue_task(
                    lead,
                    "Post-Visit Follow-up",
                    dedupe,
                    "sla_flags.visit_scheduled.post_24h_at_dt",
                    now_dt,
                    now_iso,
                    name_to_user_id,
                    sla_rule="visit_scheduled",
                    sla_threshold="post_24h",
                )

    async def _process_rule_visit_completed(
        self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]
    ) -> None:
        """3-day follow-up: surface lead in Today's Follow-ups via next_action_date (legacy backup)."""
        status_q = {"lead_status": _RE_VISIT_COMPLETED}
        flag_3d = "sla_flags.visit_completed.3d_at_dt"
        cutoff_3d = now_dt - timedelta(days=3)
        today_ist = now_dt.astimezone(IST).date().isoformat()

        query_3d = self._rule_query(
            {
                **status_q,
                **_flag_not_set(flag_3d),
                "$or": [
                    {"visit_completed_at_dt": {"$lt": cutoff_3d}},
                    {"visit_sla_reference_dt": {"$lt": cutoff_3d}},
                ],
            }
        )
        async for batch in _paginate_leads(db.leads, query_3d):
            for lead in batch:
                ref = (
                    coerce_datetime(lead.get("visit_sla_reference_dt"))
                    or coerce_datetime(lead.get("visit_completed_at_dt"))
                    or coerce_datetime(lead.get("updated_at_dt"))
                )
                if not ref:
                    continue
                if ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)
                if now_dt < ref + timedelta(days=3):
                    continue
                nad = (lead.get("next_action_date") or "")[:10]
                if nad and nad > today_ist:
                    continue
                self._queue_lead_mutation(
                    lead["id"],
                    {"next_action_date": today_ist},
                    flag_3d,
                    now_dt,
                    now_iso,
                    "mutation:visit_completed:3d_followup",
                )

    async def _process_rule_sv_followup_1(
        self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]
    ) -> None:
        """3-day follow-up backup for SV Follow-up 1 (primary scheduling is on status entry)."""
        status_q = {"lead_status": SV_FOLLOWUP_1_STATUS_QUERY}
        flag_3d = "sla_flags.sv_followup_1.3d_at_dt"
        cutoff_3d = now_dt - timedelta(days=3)
        today_ist = now_dt.astimezone(IST).date().isoformat()

        query_3d = self._rule_query(
            {
                **status_q,
                "sv_followup_1_entered_at_dt": {"$exists": True, "$ne": None, "$lt": cutoff_3d},
                # Backward-compat: if the old 7d flag exists, do not re-fire
                "sla_flags.sv_followup_1.7d_at_dt": {"$exists": False},
                **_flag_not_set(flag_3d),
            }
        )
        async for batch in _paginate_leads(db.leads, query_3d):
            for lead in batch:
                ref = coerce_datetime(lead.get("sv_followup_1_entered_at_dt"))
                if not ref:
                    continue
                if ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)
                if now_dt < ref + timedelta(days=3):
                    continue
                nad = (lead.get("next_action_date") or "")[:10]
                if nad and nad > today_ist:
                    continue
                self._queue_lead_mutation(
                    lead["id"],
                    {"next_action_date": today_ist},
                    flag_3d,
                    now_dt,
                    now_iso,
                    "mutation:sv_followup_1:3d_followup",
                )

    async def _process_rule_sv_followup_2(
        self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]
    ) -> None:
        """7-day SV Follow-up 2: agent follow-up due + admin in-app alert + email."""
        status_q = {"lead_status": SV_FOLLOWUP_2_STATUS_QUERY}
        flag_7d = "sla_flags.sv_followup_2.admin_7d_at_dt"
        cutoff_7d = now_dt - timedelta(days=7)
        today_ist = now_dt.astimezone(IST).date().isoformat()

        query_7d = self._rule_query(
            {
                **status_q,
                "sv_followup_2_entered_at_dt": {"$exists": True, "$ne": None, "$lt": cutoff_7d},
                # Backward-compat: if the old 20d flag exists, do not re-fire
                "sla_flags.sv_followup_2.admin_20d_at_dt": {"$exists": False},
                **_flag_not_set(flag_7d),
            }
        )
        async for batch in _paginate_leads(db.leads, query_7d):
            for lead in batch:
                ref = coerce_datetime(lead.get("sv_followup_2_entered_at_dt"))
                if not ref:
                    continue
                if ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)
                if now_dt < ref + timedelta(days=7):
                    continue
                lead_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
                self._queue_lead_mutation(
                    lead["id"],
                    {"next_action_date": today_ist},
                    flag_7d,
                    now_dt,
                    now_iso,
                    "mutation:sv_followup_2:7d_followup",
                )
                self._queue_admin_notification(
                    lead,
                    "SV Follow-up 2 — 7-day follow-up due",
                    f"{lead_name} requires admin attention — 7 days in SV Follow-up 2",
                    f"sla:sv_followup_2:7d:admin:{lead['id']}",
                    now_dt,
                    now_iso,
                )
                admin = self._escalation_targets.get("admin") or {}
                self._admin_email_ops.append(
                    {
                        "subject": f"SV Follow-up 2 alert — {lead_name or 'Lead'}",
                        "body_html": (
                            f"<p>Lead <strong>{lead_name or lead['id']}</strong> has been in "
                            f"<strong>SV Follow-up 2</strong> for 7+ days.</p>"
                            f"<p>Please review and ensure the assigned agent has followed up.</p>"
                        ),
                        "admin_user_id": admin.get("id", ""),
                        "dedupe_key": f"brevo:sv_followup_2:7d:{lead['id']}",
                    }
                )

    async def _process_rule_sv_followup(
        self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]
    ) -> None:
        """Deprecated: SV Completed – Follow Up is no longer processed.

        This method is kept only for backwards compatibility with historical deployments/tests,
        but is no longer invoked from process_all_slas().
        """
        return None

    async def _process_rule_reengaged(
        self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]
    ) -> None:
        status_q = {"lead_status": _RE_REENGAGED}
        for hours, threshold, desc, priority, target in (
            (12, "12h", "Re-engaged — follow up required", "medium", None),
            (24, "24h", "Re-engaged escalation", "high", None),
            (48, "48h", "Re-engaged — Admin alert", "high", "admin"),
        ):
            cutoff = now_dt - timedelta(hours=hours)
            flag = f"sla_flags.reengaged.{threshold}_at_dt"
            query = self._rule_query(
                {
                    **status_q,
                    "$or": [
                        {"reengaged_at_dt": {"$lt": cutoff}},
                        {"reengaged_at_dt": {"$exists": False}, "updated_at_dt": {"$lt": cutoff}},
                    ],
                    **_flag_not_set(flag),
                }
            )
            async for batch in _paginate_leads(db.leads, query):
                for lead in batch:
                    entered = coerce_datetime(lead.get("reengaged_at_dt")) or coerce_datetime(lead.get("updated_at_dt"))
                    if entered and entered.tzinfo is None:
                        entered = entered.replace(tzinfo=timezone.utc)
                    if entered and now_dt < entered + timedelta(hours=hours):
                        continue
                    dedupe = f"sla:reengaged:{threshold}:{lead['id']}"
                    self._queue_task(
                        lead,
                        desc,
                        dedupe,
                        flag,
                        now_dt,
                        now_iso,
                        name_to_user_id,
                        escalation_target=target,
                        priority=priority,
                        sla_rule="reengaged",
                        sla_threshold=threshold,
                    )
                    if threshold == "48h":
                        re_flags = (lead.get("sla_flags") or {}).get("reengaged") or {}
                        if not re_flags.get("gone_cold_48h_at_dt"):
                            self._queue_lead_mutation(
                                lead["id"],
                                {"lead_status": "Gone Cold"},
                                "sla_flags.reengaged.gone_cold_48h_at_dt",
                                now_dt,
                                now_iso,
                                "mutation:reengaged:gone_cold_48h",
                            )

    async def _process_rule_negotiation(self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]) -> None:
        status_q = {"lead_status": _RE_NEGOTIATION}

        for delta, threshold, desc, priority, target in (
            (timedelta(hours=48), "48h", "Negotiation follow-up", "medium", None),
            (timedelta(days=7), "stalled_7d", "Negotiation stalled — review deal status", "high", None),
            (timedelta(days=15), "admin_15d", "Negotiation overdue — Admin review required", "high", "admin"),
        ):
            cutoff = now_dt - delta
            flag = (
                "sla_flags.negotiation.followup_48h_at_dt"
                if threshold == "48h"
                else f"sla_flags.negotiation.{threshold}_at_dt"
            )
            query = self._rule_query(
                {
                    **status_q,
                    **_entered_at_or_updated_fallback("negotiation_entered_at_dt", cutoff),
                    **_flag_not_set(flag),
                }
            )
            async for batch in _paginate_leads(db.leads, query):
                for lead in batch:
                    ref = (
                        coerce_datetime(lead.get("negotiation_entered_at_dt"))
                        or coerce_datetime(lead.get("updated_at_dt"))
                    )
                    if ref and ref.tzinfo is None:
                        ref = ref.replace(tzinfo=timezone.utc)
                    if ref and now_dt < ref + delta:
                        continue
                    dedupe = f"sla:negotiation:{threshold}:{lead['id']}"
                    self._queue_task(
                        lead,
                        desc,
                        dedupe,
                        flag,
                        now_dt,
                        now_iso,
                        name_to_user_id,
                        escalation_target=target,
                        priority=priority,
                        sla_rule="negotiation",
                        sla_threshold=threshold,
                    )

    async def _process_rule_gone_cold(self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]) -> None:
        cutoff = now_dt - timedelta(days=30)
        flag = "sla_flags.gone_cold.reevaluate_30d_at_dt"
        query = self._rule_query(
            {
                "lead_status": _RE_GONE_COLD,
                **_entered_at_or_updated_fallback("gone_cold_entered_at_dt", cutoff),
                **_flag_not_set(flag),
            }
        )
        async for batch in _paginate_leads(db.leads, query):
            for lead in batch:
                ref = (
                    coerce_datetime(lead.get("gone_cold_entered_at_dt"))
                    or coerce_datetime(lead.get("updated_at_dt"))
                )
                if ref and ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)
                if ref and now_dt < ref + timedelta(days=30):
                    continue
                dedupe = f"sla:gone_cold:30d:{lead['id']}"
                self._queue_task(
                    lead,
                    "Re-evaluate - re-engage or close",
                    dedupe,
                    flag,
                    now_dt,
                    now_iso,
                    name_to_user_id,
                    sla_rule="gone_cold",
                    sla_threshold="30d",
                )

    async def _process_rule_future_prospect(
        self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]
    ) -> None:
        query = self._rule_query({"lead_status": _RE_FUTURE_PROSPECT})
        async for batch in _paginate_leads(db.leads, query):
            for lead in batch:
                entered = coerce_datetime(lead.get("future_prospect_entered_at_dt")) or coerce_datetime(lead.get("updated_at_dt")) or now_dt
                if entered.tzinfo is None:
                    entered = entered.replace(tzinfo=timezone.utc)
                last = coerce_datetime(lead.get("fp_last_checkin_task_created_at_dt")) or entered
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (now_dt - last) < timedelta(days=90):
                    continue

                cycle = int(lead.get("fp_cycle_count") or 0) + 1
                dedupe = f"sla:future_prospect:90d:{lead['id']}:{cycle}"
                self._queue_task(
                    lead,
                    "90-day check-in",
                    dedupe,
                    f"sla_flags.future_prospect.checkin_90d_{cycle}_at_dt",
                    now_dt,
                    now_iso,
                    name_to_user_id,
                    sla_rule="future_prospect",
                    sla_threshold="90d",
                    extra_lead_set={
                        "fp_cycle_count": cycle,
                        "fp_last_checkin_task_created_at_dt": now_dt,
                    },
                )

                if cycle >= 3:
                    dedupe2 = f"sla:future_prospect:manager_review:{lead['id']}:{cycle}"
                    self._queue_task(
                        lead,
                        "Manager review (3 cycles reached)",
                        dedupe2,
                        f"sla_flags.future_prospect.manager_review_{cycle}_at_dt",
                        now_dt,
                        now_iso,
                        name_to_user_id,
                        escalation_target="admin",
                        priority="high",
                        sla_rule="future_prospect",
                        sla_threshold="manager_review",
                    )

    async def _flush_bulk_writes(self) -> Tuple[int, int, int, int]:
        tasks_written = 0
        notifs_written = 0
        events_written = 0
        leads_written = 0
        if self._task_ops:
            try:
                result = await db.tasks.bulk_write(self._task_ops, ordered=False)
                tasks_written = result.inserted_count
            except BulkWriteError as e:
                tasks_written = int((e.details or {}).get("nInserted", 0) or 0)
                logger.warning("SLA task bulk_write had errors (continuing): %s", (e.details or {}).get("writeErrors"))
                self._bump("warnings:tasks_bulk")
            except Exception as e:
                logger.error("SLA task bulk_write failed: %s", e)
                self._bump("errors:tasks_bulk")
        if self._notif_ops:
            try:
                result = await db.notifications.bulk_write(self._notif_ops, ordered=False)
                notifs_written = result.inserted_count
            except BulkWriteError as e:
                notifs_written = int((e.details or {}).get("nInserted", 0) or 0)
                logger.warning("SLA notification bulk_write had errors (continuing): %s", (e.details or {}).get("writeErrors"))
                self._bump("warnings:notifs_bulk")
            except Exception as e:
                logger.error("SLA notification bulk_write failed: %s", e)
                self._bump("errors:notifs_bulk")
        if self._event_ops:
            try:
                result = await db.lead_events.bulk_write(self._event_ops, ordered=False)
                events_written = result.inserted_count
            except BulkWriteError as e:
                events_written = int((e.details or {}).get("nInserted", 0) or 0)
                logger.warning("SLA lead_events bulk_write had errors (continuing): %s", (e.details or {}).get("writeErrors"))
                self._bump("warnings:events_bulk")
            except Exception as e:
                logger.error("SLA lead_events bulk_write failed: %s", e)
                self._bump("errors:events_bulk")
        if self._lead_ops:
            try:
                result = await db.leads.bulk_write(self._lead_ops, ordered=False)
                leads_written = result.modified_count
            except BulkWriteError as e:
                leads_written = int((e.details or {}).get("nModified", 0) or 0)
                logger.warning("SLA lead bulk_write had errors (continuing): %s", (e.details or {}).get("writeErrors"))
                self._bump("warnings:leads_bulk")
            except Exception as e:
                logger.error("SLA lead bulk_write failed: %s", e)
                self._bump("errors:leads_bulk")

        for user_id, payload in self._notif_publish:
            try:
                await notifications_stream.publish(user_id, payload)
            except Exception:
                pass
        return tasks_written, notifs_written, events_written, leads_written

    async def process_all_slas(self) -> dict:
        now_dt = utc_now()
        now_iso = iso_utc_now()
        lock_acquired = False
        try:
            if not await self._acquire_cron_lock(now_dt):
                logger.info("SLA cron skipped — lock held by another instance")
                return {"skipped": True, "reason": "lock_held"}

            lock_acquired = True
            name_to_user_id = await self._load_name_to_user_id()
            self._escalation_targets = await self._load_escalation_targets()

            await self._process_rule_new(now_dt, now_iso, name_to_user_id)
            await self._process_rule_rnr(now_dt, now_iso, name_to_user_id)
            await self._process_rule_contacted(now_dt, now_iso, name_to_user_id)
            await self._process_rule_nurturing(now_dt, now_iso, name_to_user_id)
            await self._process_rule_interested(now_dt, now_iso, name_to_user_id)
            await self._process_rule_visit_scheduled(now_dt, now_iso, name_to_user_id)
            await self._process_rule_visit_completed(now_dt, now_iso, name_to_user_id)
            await self._process_rule_sv_followup_1(now_dt, now_iso, name_to_user_id)
            await self._process_rule_sv_followup_2(now_dt, now_iso, name_to_user_id)
            await self._process_rule_negotiation(now_dt, now_iso, name_to_user_id)
            await self._process_rule_gone_cold(now_dt, now_iso, name_to_user_id)
            await self._process_rule_future_prospect(now_dt, now_iso, name_to_user_id)
            await self._process_rule_reengaged(now_dt, now_iso, name_to_user_id)

            tasks_written, notifs_written, events_written, leads_written = await self._flush_bulk_writes()

            emails_sent = 0
            if self._admin_email_ops:
                from crm.services.brevo_service import send_sla_alert_email

                for item in self._admin_email_ops:
                    if not item.get("admin_user_id"):
                        continue
                    try:
                        if await send_sla_alert_email(**item):
                            emails_sent += 1
                    except Exception as e:
                        logger.warning("SLA admin email failed: %s", e)

            out = {
                "ok": True,
                "processed_at": now_iso,
                "tasks_inserted": tasks_written,
                "notifications_inserted": notifs_written,
                "events_inserted": events_written,
                "leads_modified": leads_written,
                "admin_emails_sent": emails_sent,
                "task_ops_queued": len(self._task_ops),
                "lead_ops_queued": len(self._lead_ops),
                "skipped_no_assignee": self._skipped_no_assignee,
                "rules": self._summary,
            }
            logger.info("SLA engine completed: %s", out)
            return out
        finally:
            if lock_acquired:
                await db.cron_locks.delete_one({"job": _CRON_LOCK_JOB})
