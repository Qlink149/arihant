import re
from datetime import datetime, timezone
from typing import Optional, Union
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc_now() -> str:
    # Keep legacy ISO string format for backwards compatibility in existing queries.
    return utc_now().isoformat()


def ist_wall_to_utc_dt(due_date: str, due_time: Optional[str] = None) -> datetime:
    """
    Interpret due_date (YYYY-MM-DD) + due_time (HH:MM) as Asia/Kolkata wall clock,
    return timezone-aware UTC datetime for due_at_dt storage/sorting.
    """
    date_part = (due_date or "").strip()[:10]
    time_part = (due_time or "09:00").strip()
    if len(time_part) == 5:
        time_part = f"{time_part}:00"
    elif len(time_part) == 4 and ":" not in time_part:
        time_part = f"{time_part[:2]}:{time_part[2:]}:00"
    local = datetime.fromisoformat(f"{date_part}T{time_part}").replace(tzinfo=IST)
    return local.astimezone(timezone.utc)


def coerce_datetime(value: Union[None, str, datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            s = value.strip().replace("Z", "+00:00")
            # WATI / .NET often emit 7+ digit fractional seconds; fromisoformat
            # accepts at most microseconds (6 digits) on older Python.
            s = re.sub(r"(\.\d{6})\d+", r"\1", s)
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("91") and len(digits) > 10:
        digits = digits[2:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits[-10:] if len(digits) >= 10 else digits


def format_phone_for_gupshup(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if not digits.startswith("91") and len(digits) == 10:
        digits = "91" + digits
    elif digits.startswith("0"):
        digits = "91" + digits[1:]
    return digits


def get_time_greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good Morning"
    if hour < 17:
        return "Good Afternoon"
    return "Good Evening"


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


def parse_csv_date(date_str: str) -> str:
    for fmt in ["%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"]:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except (ValueError, AttributeError):
            continue
    return datetime.now(timezone.utc).isoformat()
