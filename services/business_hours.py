import json
from datetime import datetime, timezone, time
import pytz
from typing import Dict, Union, List, Any, Optional

def is_open_now(open_hours_json: Union[str, Dict[str, Any]], timezone_str: str, now_utc: Optional[datetime] = None) -> bool:
    """
    Checks if business is open based on open_hours_json and timezone.

    Args:
        open_hours_json: JSON string or Dict.
                         Compact: {"days": ["Mon", "Tue"], "hours": ["09:00", "17:00"]}
                         Detailed: {"Mon": ["09:00", "17:00"], ...}
        timezone_str: Timezone identifier (e.g., "Europe/Rome")
        now_utc: Current UTC datetime (defaults to now)

    Returns:
        True if open, False otherwise.
    """
    if not open_hours_json:
        return False # Closed if no hours defined

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    try:
        if isinstance(open_hours_json, str):
            schedule = json.loads(open_hours_json)
        else:
            schedule = open_hours_json

        tz = pytz.timezone(timezone_str)
        local_time = now_utc.astimezone(tz)

        # 0=Mon, 6=Sun
        weekday = local_time.weekday()
        days_map = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        today_str = days_map[weekday]

        start_str = None
        end_str = None

        # Detect format
        if "days" in schedule and isinstance(schedule["days"], list):
            # Compact format
            if today_str not in schedule["days"]:
                return False

            if "hours" in schedule and len(schedule["hours"]) == 2:
                start_str, end_str = schedule["hours"]
            else:
                return False # Malformed

        elif today_str in schedule:
             # Detailed format: {"Mon": ["09:00", "17:00"]}
             times = schedule[today_str]
             if isinstance(times, list) and len(times) == 2:
                 start_str, end_str = times
             else:
                 return False # Malformed
        else:
            return False # Closed today

        # Parse times
        def parse_time(t_str):
            h, m = map(int, t_str.split(":"))
            return time(h, m)

        start_time = parse_time(start_str)
        end_time = parse_time(end_str)
        current_time = local_time.time()

        return start_time <= current_time <= end_time

    except Exception as e:
        print(f"Error parsing business hours: {e}")
        return False # Fail closed for safety
