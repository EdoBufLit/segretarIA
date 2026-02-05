import re
from typing import Dict, Any, List, Optional

def normalize_phone_number(phone: Optional[str]) -> Optional[str]:
    """
    Normalizes phone number to E.164 format.
    Strips spaces, dashes, parentheses. Ensures leading +.
    Returns None if input is None.
    """
    if phone is None:
        return None
    if not phone:
        return ""
    # Strip spaces, dashes, parentheses
    cleaned = re.sub(r"[\s\-\(\)]", "", phone)
    if not cleaned:
        return ""
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned

def validate_open_hours_schema(data: Any) -> bool:
    """
    Validates that the open_hours_json follows the expected structure.
    Supported formats:
    1. Compact: {"days": ["Mon", "Tue"...], "hours": ["09:00", "17:00"]}
    2. Detailed: {"Mon": ["09:00", "17:00"], "Tue": [...]}
    """
    if not isinstance(data, dict):
        return False

    valid_days = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}

    # Check Compact format
    if "days" in data:
        if not isinstance(data["days"], list):
            return False
        for day in data["days"]:
            if day not in valid_days:
                return False

        if "hours" in data:
            if not _validate_hours_pair(data["hours"]):
                return False
        # If days present but hours missing, strictly speaking compact format usually implies hours.
        # But let's assume if hours missing = closed? No, usually implies open 24h or invalid?
        # Let's enforce hours for compact format.
        else:
            return False

        return True

    # Check Detailed format
    # Any key that is a valid day must have a valid hours pair
    for key, value in data.items():
        if key in valid_days:
            if not _validate_hours_pair(value):
                return False
        # Ignore other keys? Or strict?
        # Ideally we allow extra metadata or just ignore.
        # But if NO valid keys are found, and it's not compact, is it valid?
        # A completely empty dict {} means closed 24/7, which is valid.

    return True

def _validate_hours_pair(hours: Any) -> bool:
    if not isinstance(hours, list) or len(hours) != 2:
        return False
    start, end = hours
    if not isinstance(start, str) or not isinstance(end, str):
        return False
    # Simple regex for HH:MM
    time_fmt = re.compile(r"^\d{2}:\d{2}$")
    if not time_fmt.match(start) or not time_fmt.match(end):
        return False
    return True
