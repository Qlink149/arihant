import os
from typing import Dict, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient

from app_state import iso_utc_now, utc_now


def _env(name: str, default: Optional[str] = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


async def _build_full_name_map(db) -> Tuple[Dict[str, str], Dict[str, int]]:
    users = await db.users.find({}, {"_id": 0, "id": 1, "full_name": 1}).to_list(10000)
    name_to_id: Dict[str, str] = {}
    dupes: Dict[str, int] = {}
    for u in users:
        name = (u.get("full_name") or "").strip()
        uid = u.get("id")
        if not name or not uid:
            continue
        if name in name_to_id:
            dupes[name] = dupes.get(name, 1) + 1
            continue
        name_to_id[name] = uid
    return name_to_id, dupes


def _resolve(name_to_id: Dict[str, str], name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return name_to_id.get(name.strip())


async def run_backfill():
    mongo_url = _env("MONGO_URL")
    db_name = _env("DB_NAME")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    name_to_id, dupes = await _build_full_name_map(db)

    now_iso = iso_utc_now()
    now_dt = utc_now()

    stats = {
        "dupe_full_names": len(dupes),
        "leads": 0,
        "tasks": 0,
        "notifications": 0,
        "lead_transfers": 0,
        "campaigns": 0,
        "unresolved_names": 0,
    }

    unresolved = set()

    # leads: assigned_to/presales_agent -> assigned_user_id
    async for lead in db.leads.find({"assigned_user_id": {"$exists": False}}, {"_id": 0, "id": 1, "assigned_to": 1, "presales_agent": 1}):
        name = lead.get("assigned_to") or lead.get("presales_agent")
        uid = _resolve(name_to_id, name)
        if not uid and name:
            unresolved.add(name)
            continue
        await db.leads.update_one(
            {"id": lead["id"]},
            {"$set": {"assigned_user_id": uid, "assigned_to_name": name or None, "updated_at": now_iso, "updated_at_dt": now_dt}},
        )
        stats["leads"] += 1

    # tasks: assigned_to -> assigned_user_id
    async for task in db.tasks.find({"assigned_user_id": {"$exists": False}}, {"_id": 0, "id": 1, "assigned_to": 1}):
        name = task.get("assigned_to")
        uid = _resolve(name_to_id, name)
        if not uid and name:
            unresolved.add(name)
            continue
        await db.tasks.update_one({"id": task["id"]}, {"$set": {"assigned_user_id": uid, "assigned_to_name": name or None, "updated_at": now_iso, "updated_at_dt": now_dt}})
        stats["tasks"] += 1

    # notifications: assigned_to or user_id -> recipient_user_id
    async for n in db.notifications.find({"recipient_user_id": {"$exists": False}}, {"_id": 0, "id": 1, "assigned_to": 1, "user_id": 1}):
        name = n.get("assigned_to") or n.get("user_id")
        uid = _resolve(name_to_id, name)
        if not uid and name:
            unresolved.add(name)
            continue
        await db.notifications.update_one(
            {"id": n["id"]},
            {"$set": {"recipient_user_id": uid, "recipient_name": name or None, "updated_at": now_iso, "updated_at_dt": now_dt}},
        )
        stats["notifications"] += 1

    # lead_transfers: from_rep/to_rep/transferred_by -> *_user_id
    async for t in db.lead_transfers.find(
        {"$or": [{"from_user_id": {"$exists": False}}, {"to_user_id": {"$exists": False}}, {"transferred_by_user_id": {"$exists": False}}]},
        {"_id": 0, "id": 1, "from_rep": 1, "to_rep": 1, "transferred_by": 1},
    ):
        from_name = t.get("from_rep")
        to_name = t.get("to_rep")
        by_name = t.get("transferred_by")
        from_uid = _resolve(name_to_id, from_name)
        to_uid = _resolve(name_to_id, to_name)
        by_uid = _resolve(name_to_id, by_name)
        for nm, uid in [(from_name, from_uid), (to_name, to_uid), (by_name, by_uid)]:
            if nm and not uid:
                unresolved.add(nm)
        await db.lead_transfers.update_one(
            {"id": t["id"]},
            {"$set": {"from_user_id": from_uid, "to_user_id": to_uid, "transferred_by_user_id": by_uid, "from_name": from_name, "to_name": to_name}},
        )
        stats["lead_transfers"] += 1

    # campaigns: created_by (user id string) -> created_by_user_id
    async for c in db.campaigns.find({"created_by_user_id": {"$exists": False}, "created_by": {"$exists": True}}, {"_id": 0, "id": 1, "created_by": 1}):
        uid = c.get("created_by")
        if not uid or not isinstance(uid, str):
            continue
        user = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1})
        if not user:
            continue
        await db.campaigns.update_one(
            {"id": c["id"]},
            {"$set": {"created_by_user_id": uid, "updated_at": now_iso, "updated_at_dt": now_dt}},
        )
        stats["campaigns"] += 1

    stats["unresolved_names"] = len(unresolved)
    print({"stats": stats, "duplicate_full_names": list(dupes.keys())[:20], "unresolved_names_sample": list(unresolved)[:30]})

    client.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_backfill())

