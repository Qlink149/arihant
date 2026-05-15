"""Script to import test leads CSV and replace existing mock data."""
import asyncio
import csv
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_ROOT = Path(__file__).resolve().parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

load_dotenv(Path(__file__).parent / ".env")

from app.core.state import (
    client,
    db,
    iso_utc_now,
    normalize_phone,
    resolve_project_id,
    resolve_user_id_by_full_name,
    utc_now,
)

CSV_PATH = "/tmp/test_leads.csv"


def determine_temperature(status: str) -> str:
    status_lower = status.lower().strip()
    if status_lower in ["interested", "site visit completed", "advance paid", "negotiation"]:
        return "Hot"
    elif status_lower in ["follow up 1", "follow up 2", "site visit scheduled", "contacted", "new"]:
        return "Warm"
    else:
        return "Cold"


def determine_intent(note: str) -> str:
    note_lower = (note or "").lower()
    if "invest" in note_lower or "rental" in note_lower:
        return "Investor"
    elif "self" in note_lower or "own" in note_lower or "live" in note_lower or "family" in note_lower:
        return "End User"
    return "Unknown"


def is_vip(note: str, status: str) -> bool:
    if status.lower() in ["advance paid", "negotiation"]:
        return True
    note_lower = (note or "").lower()
    if "5 cr" in note_lower or "5cr" in note_lower or "crore" in note_lower:
        return True
    return False


def parse_created(date_str: str) -> tuple[str, datetime]:
    """Parse '01-01-2026 07:27' format; return (iso, dt)."""
    try:
        dt = datetime.strptime(date_str.strip(), "%d-%m-%Y %H:%M").replace(tzinfo=timezone.utc)
        return dt.isoformat(), dt
    except Exception:
        n = utc_now()
        return n.isoformat(), n


def generate_persona(lead: dict) -> str:
    name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
    project = lead.get("project", "Not specified")
    status = lead.get("lead_status", "Unknown")
    source = lead.get("lead_source", "Unknown")
    agent = lead.get("presales_agent", "Unassigned")
    note = lead.get("presales_description", "")

    parts = [f"{name} is a lead"]
    if project:
        parts.append(f"interested in {project}")
    parts.append(f"with current status: {status}")
    if source:
        parts.append(f"sourced from {source}")
    if agent:
        parts.append(f"managed by {agent}")
    if note:
        parts.append(f". Latest note: {note}")

    return ". ".join(parts[:4]) + (f". Latest note: {note}" if note else "")


async def import_leads():
    old_count = await db.leads.count_documents({})
    print(f"Clearing {old_count} existing leads...")
    await db.leads.delete_many({})

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Importing {len(rows)} leads from CSV...")

    imported = 0
    skipped = 0

    for row in rows:
        first_name = (row.get("First name") or "").strip()
        last_name = (row.get("Last name") or "").strip()

        if not first_name and not last_name:
            skipped += 1
            continue

        now_iso = iso_utc_now()
        now_dt = utc_now()
        phone = (row.get("Mobile") or "").strip()
        email_raw = (row.get("Email IDs") or "").strip()
        email = email_raw.split(",")[0].strip() if email_raw else None

        project = (row.get("Project") or "").strip()
        status = (row.get("Status") or "New").strip()
        source = (row.get("Source") or "").strip()
        sales_owner = (row.get("Sales owner") or "").strip()
        recent_note = (row.get("Recent note") or "").strip()
        created_at, created_at_dt = parse_created(row.get("Created at", ""))
        external_id = (row.get("ID") or "").strip()

        normalized = normalize_phone(phone)
        temperature = determine_temperature(status)
        intent = determine_intent(recent_note)
        vip = is_vip(recent_note, status)
        assigned_user_id = await resolve_user_id_by_full_name(sales_owner)

        lead_id = str(uuid.uuid4())
        lead_dict = {
            "id": lead_id,
            "external_id": external_id,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "normalized_phone": normalized,
            "email": email,
            "project": project,
            "project_id": resolve_project_id(project),
            "lead_status": status,
            "lead_source": source,
            "budget": None,
            "configuration": None,
            "location": None,
            "ethnicity": None,
            "designation": None,
            "reason_for_purchase": None,
            "possession_requirement": None,
            "current_residence_type": None,
            "campaign_name": None,
            "presales_agent": sales_owner,
            "presales_description": recent_note,
            "next_action_date": None,
            "temperature": temperature,
            "intent": intent,
            "vip": vip,
            "assigned_to": sales_owner,
            "assigned_user_id": assigned_user_id,
            "assigned_to_name": sales_owner or None,
            "context_updates": [
                {
                    "type": "imported",
                    "timestamp": created_at,
                    "timestamp_dt": created_at_dt,
                    "description": f"Lead imported from {source}" if source else "Lead imported",
                    "agent": "System",
                }
            ],
            "created_at": created_at,
            "created_at_dt": created_at_dt,
            "updated_at": now_iso,
            "updated_at_dt": now_dt,
        }

        if recent_note:
            lead_dict["context_updates"].append(
                {
                    "type": "call",
                    "timestamp": now_iso,
                    "timestamp_dt": now_dt,
                    "description": recent_note,
                    "agent": sales_owner or "Agent",
                    "actor_user_id": assigned_user_id,
                }
            )

        lead_dict["ai_persona_summary"] = generate_persona(lead_dict)

        await db.leads.insert_one(lead_dict)
        imported += 1

    final_count = await db.leads.count_documents({})
    print("\nImport complete!")
    print(f"  Imported: {imported}")
    print(f"  Skipped: {skipped}")
    print(f"  Total leads in DB: {final_count}")

    pipeline = [{"$group": {"_id": "$project", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]
    projects = await db.leads.aggregate(pipeline).to_list(20)
    print("\nLeads by Project:")
    for p in projects:
        print(f"  {p['_id'] or 'Unknown'}: {p['count']}")

    pipeline = [{"$group": {"_id": "$temperature", "count": {"$sum": 1}}}]
    temps = await db.leads.aggregate(pipeline).to_list(10)
    print("\nLeads by Temperature:")
    for t in temps:
        print(f"  {t['_id']}: {t['count']}")


if __name__ == "__main__":
    asyncio.run(import_leads())
    client.close()
