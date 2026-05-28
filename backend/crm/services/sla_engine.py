"""
Event-driven SLA engine: bulk Mongo writes, BSON datetime queries, idempotent flags + task dedupe.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from pymongo import InsertOne, UpdateOne
from pymongo.errors import BulkWriteError

from crm.constants.lead_kpi import RNR_STATUS_REGEX
from crm.core.state import db, logger
from crm.utils.helpers import coerce_datetime, iso_utc_now, utc_now

IST = ZoneInfo("Asia/Kolkata")

# Status matchers (case-insensitive)
_RE_CONTACTED = {"$regex": r"^\s*contacted\s*$", "$options": "i"}
_RE_NURTURING = {"$regex": r"nurtur", "$options": "i"}
_RE_VISIT_SCHEDULED = {"$regex": r"site\s*visit\s*scheduled", "$options": "i"}
_RE_VISIT_COMPLETED = {"$regex": r"site\s*visit\s*completed", "$options": "i"}
_RE_NEGOTIATION = {"$regex": r"negotiat", "$options": "i"}
_RE_GONE_COLD = {"$regex": r"gone\s*cold", "$options": "i"}
_RE_FUTURE_PROSPECT = {"$regex": r"future\s*prospect", "$options": "i"}


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


def is_business_hours_ist(now_dt: datetime) -> bool:
    ist = now_dt.astimezone(IST)
    minutes = ist.hour * 60 + ist.minute
    start = 10 * 60
    end = 17 * 60 + 30
    return start <= minutes <= end


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

    # Escalation routing override (admin/manager). Falls back to normal assignee if missing.
    if escalation_user and escalation_user.get("id"):
        assigned_user_id = escalation_user["id"]
        if escalation_user.get("full_name"):
            assigned = escalation_user["full_name"]
    if not assigned_user_id:
        return None

    due_date = due_date or now_dt.strftime("%Y-%m-%d")
    due_at_dt = datetime.fromisoformat(f"{due_date}T{due_time}:00").replace(tzinfo=timezone.utc)

    doc = {
        "id": str(uuid.uuid4()),
        "lead_id": lead["id"],
        "description": description,
        "due_date": due_date,
        "due_time": due_time,
        "due_at_dt": due_at_dt,
        "priority": priority,
        "reminder_method": "email",
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
        self._lead_ops: List[UpdateOne] = []
        self._summary: Dict[str, int] = {}
        self._skipped_no_assignee = 0
        self._escalation_targets: Dict[str, dict] = {}

    def _bump(self, key: str, n: int = 1) -> None:
        self._summary[key] = self._summary.get(key, 0) + n

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
            sla_rule=sla_rule,
            sla_threshold=sla_threshold,
        )
        if not task:
            self._skipped_no_assignee += 1
            return
        self._task_ops.append(InsertOne(task))
        self._lead_ops.append(
            UpdateOne(
                {"id": lead["id"]},
                {"$set": {flag_path: now_dt, "updated_at": now_iso, "updated_at_dt": now_dt}},
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
        self._bump(summary_key)

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
        if not is_business_hours_ist(now_dt):
            return

        base = _new_lead_filter()
        cutoff_30m = now_dt - timedelta(minutes=30)
        cutoff_2h = now_dt - timedelta(hours=2)

        for threshold, cutoff, desc, flag, priority, target in (
            ("30m", cutoff_30m, "Reassign Lead", "sla_flags.new.reassign_30m_at_dt", "medium", None),
            ("2h", cutoff_2h, "Alert Admin", "sla_flags.new.alert_admin_2h_at_dt", "high", "admin"),
        ):
            query = {
                **base,
                "created_at_dt": {"$lt": cutoff},
                **_flag_not_set(flag),
            }
            leads = await db.leads.find(query, {"_id": 0}).to_list(500)
            for lead in leads:
                dedupe = f"sla:new:{threshold}:{lead['id']}"
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
                    sla_rule="new",
                    sla_threshold=threshold,
                )

    async def _process_rule_rnr(self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]) -> None:
        if not is_business_hours_ist(now_dt):
            return

        status_base = _rnr_status_filter()

        # 4-hour loop reminders (one task per 4h period since last update)
        cutoff_4h = now_dt - timedelta(hours=4)
        query_reminder = {**status_base, "updated_at_dt": {"$lt": cutoff_4h}}
        leads = await db.leads.find(query_reminder, {"_id": 0}).to_list(500)
        for lead in leads:
            updated = coerce_datetime(lead.get("updated_at_dt")) or now_dt
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            periods = int((now_dt - updated).total_seconds() // (4 * 3600))
            if periods < 1:
                continue
            bucket = str(periods)
            flag = f"sla_flags.rnr.reminder_{bucket}_at_dt"
            rnr_flags = (lead.get("sla_flags") or {}).get("rnr") or {}
            if rnr_flags.get(f"reminder_{bucket}_at_dt"):
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
                sla_rule="rnr",
                sla_threshold=f"reminder_{bucket}",
            )

        for hours, threshold, desc, target in (
            (24, "24h", "Escalate to Sales Manager", "manager"),
            (48, "48h", "Escalate to Sales Manager", "manager"),
            (15 * 24, "15d", "Escalate to Admin", "admin"),
        ):
            cutoff = now_dt - timedelta(hours=hours)
            flag = f"sla_flags.rnr.escalate_{threshold}_at_dt"
            query = {
                **status_base,
                "updated_at_dt": {"$lt": cutoff},
                **_flag_not_set(flag),
            }
            leads = await db.leads.find(query, {"_id": 0}).to_list(500)
            for lead in leads:
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
                    sla_rule="rnr",
                    sla_threshold=threshold,
                )

    async def _process_rule_contacted(self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]) -> None:
        for hours, threshold, desc, priority, target in (
            (48, "48h", "Agent Reminder + Manager Flag", "medium", "manager"),
            (72, "72h", "Admin Alert", "high", "admin"),
        ):
            cutoff = now_dt - timedelta(hours=hours)
            flag = f"sla_flags.contacted.{threshold}_at_dt"
            query = {
                "lead_status": _RE_CONTACTED,
                "updated_at_dt": {"$lt": cutoff},
                **_flag_not_set(flag),
            }
            leads = await db.leads.find(query, {"_id": 0}).to_list(500)
            for lead in leads:
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

        # Fallback: empty temperature > 24h -> Warm
        query_warm = {
            "lead_status": _RE_NURTURING,
            "updated_at_dt": {"$lt": cutoff_24h},
            "$or": [
                {"temperature": {"$exists": False}},
                {"temperature": None},
                {"temperature": ""},
            ],
            **_flag_not_set("sla_flags.nurturing.temperature_warm_at_dt"),
        }
        leads = await db.leads.find(query_warm, {"_id": 0, "id": 1}).to_list(500)
        for lead in leads:
            self._queue_lead_mutation(
                lead["id"],
                {"temperature": "Warm"},
                "sla_flags.nurturing.temperature_warm_at_dt",
                now_dt,
                now_iso,
                "mutation:nurturing:warm",
            )

        # Hot > 2 days
        cutoff_2d = now_dt - timedelta(days=2)
        query_hot = {
            "lead_status": _RE_NURTURING,
            "temperature": {"$regex": r"^\s*hot\s*$", "$options": "i"},
            "updated_at_dt": {"$lt": cutoff_2d},
            **_flag_not_set("sla_flags.nurturing.hot_followup_at_dt"),
        }
        for lead in await db.leads.find(query_hot, {"_id": 0}).to_list(500):
            dedupe = f"sla:nurturing:hot:{lead['id']}"
            self._queue_task(
                lead,
                "Hot Lead Follow-up",
                dedupe,
                "sla_flags.nurturing.hot_followup_at_dt",
                now_dt,
                now_iso,
                name_to_user_id,
                sla_rule="nurturing",
                sla_threshold="hot_2d",
            )

        # Warm > 4 days
        cutoff_4d = now_dt - timedelta(days=4)
        query_warm_fu = {
            "lead_status": _RE_NURTURING,
            "temperature": {"$regex": r"^\s*warm\s*$", "$options": "i"},
            "updated_at_dt": {"$lt": cutoff_4d},
            **_flag_not_set("sla_flags.nurturing.warm_followup_at_dt"),
        }
        for lead in await db.leads.find(query_warm_fu, {"_id": 0}).to_list(500):
            dedupe = f"sla:nurturing:warm:{lead['id']}"
            self._queue_task(
                lead,
                "Warm Lead Follow-up",
                dedupe,
                "sla_flags.nurturing.warm_followup_at_dt",
                now_dt,
                now_iso,
                name_to_user_id,
                sla_rule="nurturing",
                sla_threshold="warm_4d",
            )

    async def _process_rule_visit_scheduled(
        self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]
    ) -> None:
        status_q = {"lead_status": _RE_VISIT_SCHEDULED}

        # Missing visit_date_dt
        query_missing = {
            **status_q,
            **_missing_dt("visit_date_dt"),
            **_flag_not_set("sla_flags.visit_scheduled.missing_date_at_dt"),
        }
        for lead in await db.leads.find(query_missing, {"_id": 0}).to_list(500):
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
        query_pre = {
            **status_q,
            "visit_date_dt": {"$lte": pre_cutoff, "$exists": True, "$ne": None},
            **_flag_not_set("sla_flags.visit_scheduled.pre_24h_at_dt"),
        }
        for lead in await db.leads.find(query_pre, {"_id": 0}).to_list(500):
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

        query_post = {
            **status_q,
            "visit_date_dt": {"$exists": True, "$ne": None},
            **_flag_not_set("sla_flags.visit_scheduled.post_24h_at_dt"),
        }
        for lead in await db.leads.find(query_post, {"_id": 0}).to_list(500):
            visit_dt = coerce_datetime(lead.get("visit_date_dt"))
            if not visit_dt:
                continue
            if visit_dt.tzinfo is None:
                visit_dt = visit_dt.replace(tzinfo=timezone.utc)
            if now_dt < visit_dt + timedelta(hours=24):
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
        status_q = {"lead_status": _RE_VISIT_COMPLETED}

        for hours, threshold, desc, priority, target in (
            (48, "48h", "Push for booking", "medium", None),
            (72, "72h", "Manager Flag", "high", "manager"),
        ):
            cutoff = now_dt - timedelta(hours=hours)
            flag = f"sla_flags.visit_completed.{threshold}_at_dt"
            query = {**status_q, "updated_at_dt": {"$lt": cutoff}, **_flag_not_set(flag)}
            for lead in await db.leads.find(query, {"_id": 0}).to_list(500):
                dedupe = f"sla:visit_completed:{threshold}:{lead['id']}"
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
                    sla_rule="visit_completed",
                    sla_threshold=threshold,
                )

        cutoff_7d = now_dt - timedelta(days=7)
        flag_7d = "sla_flags.visit_completed.nurture_7d_at_dt"
        query_7d = {**status_q, "updated_at_dt": {"$lt": cutoff_7d}, **_flag_not_set(flag_7d)}
        for lead in await db.leads.find(query_7d, {"_id": 0, "id": 1}).to_list(500):
            self._queue_lead_mutation(
                lead["id"],
                {"lead_status": "Nurturing", "temperature": "Warm"},
                flag_7d,
                now_dt,
                now_iso,
                "mutation:visit_completed:nurturing",
            )

    async def _process_rule_negotiation(self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]) -> None:
        cutoff = now_dt - timedelta(hours=48)
        flag = "sla_flags.negotiation.followup_48h_at_dt"
        query = {
            "lead_status": _RE_NEGOTIATION,
            "updated_at_dt": {"$lt": cutoff},
            **_flag_not_set(flag),
        }
        for lead in await db.leads.find(query, {"_id": 0}).to_list(500):
            dedupe = f"sla:negotiation:48h:{lead['id']}"
            self._queue_task(
                lead,
                "Negotiation Follow-up",
                dedupe,
                flag,
                now_dt,
                now_iso,
                name_to_user_id,
                sla_rule="negotiation",
                sla_threshold="48h",
            )

    async def _process_rule_gone_cold(self, now_dt: datetime, now_iso: str, name_to_user_id: Dict[str, str]) -> None:
        cutoff = now_dt - timedelta(days=30)
        flag = "sla_flags.gone_cold.reevaluate_30d_at_dt"
        query = {
            "lead_status": _RE_GONE_COLD,
            "updated_at_dt": {"$lt": cutoff},
            **_flag_not_set(flag),
        }
        for lead in await db.leads.find(query, {"_id": 0}).to_list(500):
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
        cutoff = now_dt - timedelta(days=90)
        flag = "sla_flags.future_prospect.checkin_90d_at_dt"
        query = {
            "lead_status": _RE_FUTURE_PROSPECT,
            "updated_at_dt": {"$lt": cutoff},
            **_flag_not_set(flag),
        }
        for lead in await db.leads.find(query, {"_id": 0}).to_list(500):
            dedupe = f"sla:future_prospect:90d:{lead['id']}"
            self._queue_task(
                lead,
                "90-day check-in",
                dedupe,
                flag,
                now_dt,
                now_iso,
                name_to_user_id,
                sla_rule="future_prospect",
                sla_threshold="90d",
            )

    async def _flush_bulk_writes(self) -> Tuple[int, int]:
        tasks_written = 0
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
        return tasks_written, leads_written

    async def process_all_slas(self) -> dict:
        now_dt = utc_now()
        now_iso = iso_utc_now()
        name_to_user_id = await self._load_name_to_user_id()
        self._escalation_targets = await self._load_escalation_targets()

        await self._process_rule_new(now_dt, now_iso, name_to_user_id)
        await self._process_rule_rnr(now_dt, now_iso, name_to_user_id)
        await self._process_rule_contacted(now_dt, now_iso, name_to_user_id)
        await self._process_rule_nurturing(now_dt, now_iso, name_to_user_id)
        await self._process_rule_visit_scheduled(now_dt, now_iso, name_to_user_id)
        await self._process_rule_visit_completed(now_dt, now_iso, name_to_user_id)
        await self._process_rule_negotiation(now_dt, now_iso, name_to_user_id)
        await self._process_rule_gone_cold(now_dt, now_iso, name_to_user_id)
        await self._process_rule_future_prospect(now_dt, now_iso, name_to_user_id)

        tasks_written, leads_written = await self._flush_bulk_writes()

        out = {
            "ok": True,
            "processed_at": now_iso,
            "tasks_inserted": tasks_written,
            "leads_modified": leads_written,
            "task_ops_queued": len(self._task_ops),
            "lead_ops_queued": len(self._lead_ops),
            "skipped_no_assignee": self._skipped_no_assignee,
            "rules": self._summary,
        }
        logger.info("SLA engine completed: %s", out)
        return out
