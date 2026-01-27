import pytest
from datetime import datetime, timezone, time
import pytz
from services.business_hours import is_open_now

def test_compact_schedule():
    # Mon-Fri 09:00-17:00
    schedule = {"days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "hours": ["09:00", "17:00"]}
    tz_str = "Europe/Rome"

    # Mock now: Mon 10:00 (Open)
    # In Rome (GMT+1/2), 10:00 is open.
    # UTC: 09:00 -> Rome 10:00 (+1) in winter.
    # Let's fix a date: 2026-01-26 (Monday)

    # Open: Mon 10:00 Rome
    now_open = datetime(2026, 1, 26, 10, 0, tzinfo=pytz.timezone(tz_str))
    assert is_open_now(schedule, tz_str, now_open) is True

    # Closed: Mon 18:00 Rome (After 17:00)
    now_closed = datetime(2026, 1, 26, 18, 0, tzinfo=pytz.timezone(tz_str))
    assert is_open_now(schedule, tz_str, now_closed) is False

    # Closed: Sat 10:00 Rome (Not in days)
    # 2026-01-31 (Saturday)
    now_sat = datetime(2026, 1, 31, 10, 0, tzinfo=pytz.timezone(tz_str))
    assert is_open_now(schedule, tz_str, now_sat) is False

    # Boundary: Mon 09:00 (Open)
    now_boundary_start = datetime(2026, 1, 26, 9, 0, tzinfo=pytz.timezone(tz_str))
    assert is_open_now(schedule, tz_str, now_boundary_start) is True

    # Boundary: Mon 17:00 (Open inclusive)
    now_boundary_end = datetime(2026, 1, 26, 17, 0, tzinfo=pytz.timezone(tz_str))
    assert is_open_now(schedule, tz_str, now_boundary_end) is True

    # Boundary: Mon 17:01 (Closed)
    now_boundary_after = datetime(2026, 1, 26, 17, 1, tzinfo=pytz.timezone(tz_str))
    assert is_open_now(schedule, tz_str, now_boundary_after) is False


def test_detailed_schedule():
    # Mon: 09:00-12:00, Tue: 14:00-18:00
    schedule = {
        "Mon": ["09:00", "12:00"],
        "Tue": ["14:00", "18:00"]
    }
    tz_str = "Europe/Rome"

    # Mon 10:00 (Open)
    now_mon_open = datetime(2026, 1, 26, 10, 0, tzinfo=pytz.timezone(tz_str))
    assert is_open_now(schedule, tz_str, now_mon_open) is True

    # Mon 13:00 (Closed)
    now_mon_closed = datetime(2026, 1, 26, 13, 0, tzinfo=pytz.timezone(tz_str))
    assert is_open_now(schedule, tz_str, now_mon_closed) is False

    # Tue 15:00 (Open)
    now_tue_open = datetime(2026, 1, 27, 15, 0, tzinfo=pytz.timezone(tz_str))
    assert is_open_now(schedule, tz_str, now_tue_open) is True

def test_timezone_conversion():
    # Schedule: Mon 09:00-17:00 in New_York
    schedule = {"days": ["Mon"], "hours": ["09:00", "17:00"]}
    tz_str = "America/New_York"

    # UTC: 14:00 -> NY (UTC-5): 09:00 (Open)
    # UTC: 13:00 -> NY (UTC-5): 08:00 (Closed)

    # 2026-01-26 (Mon)
    utc_open = datetime(2026, 1, 26, 14, 0, tzinfo=timezone.utc)
    utc_closed = datetime(2026, 1, 26, 13, 0, tzinfo=timezone.utc)

    assert is_open_now(schedule, tz_str, utc_open) is True
    assert is_open_now(schedule, tz_str, utc_closed) is False

def test_malformed_schedule():
    tz_str = "UTC"
    now = datetime(2026, 1, 26, 10, 0, tzinfo=timezone.utc)

    assert is_open_now(None, tz_str, now) is False
    assert is_open_now({}, tz_str, now) is False
    assert is_open_now({"days": ["Mon"]}, tz_str, now) is False # Missing hours
    assert is_open_now("invalid_json", tz_str, now) is False
