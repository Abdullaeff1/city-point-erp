"""City Point ticket SLA business calendar (A.1).

Work: Monday–Saturday 09:00–18:00 (Asia/Baku local).
Off: Sunday + Novruz + fixed state holidays.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.utils import timezone

# Monday=0 … Sunday=6
WORK_WEEKDAYS = {0, 1, 2, 3, 4, 5}
OPEN_TIME = time(9, 0)
CLOSE_TIME = time(18, 0)
BUSINESS_HOURS_PER_DAY = 9

# Fixed civil holidays (month, day). Novruz: 20–24 March.
FIXED_HOLIDAYS = frozenset(
    {
        (1, 1),
        (1, 2),
        (3, 8),
        (3, 20),
        (3, 21),
        (3, 22),
        (3, 23),
        (3, 24),
        (5, 9),
        (5, 28),
        (6, 15),
        (6, 26),
        (10, 18),
        (11, 8),
        (11, 9),
        (12, 31),
    }
)


def is_fixed_holiday(day: date) -> bool:
    return (day.month, day.day) in FIXED_HOLIDAYS


def is_workday(day: date) -> bool:
    return day.weekday() in WORK_WEEKDAYS and not is_fixed_holiday(day)


def _aware(dt: datetime) -> datetime:
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _local(dt: datetime) -> datetime:
    return timezone.localtime(_aware(dt))


def _at_open(day: date) -> datetime:
    return _aware(datetime.combine(day, OPEN_TIME))


def _at_close(day: date) -> datetime:
    return _aware(datetime.combine(day, CLOSE_TIME))


def next_open(after: datetime) -> datetime:
    """Next moment work time is open (may be `after` itself if already open)."""
    current = _local(after)
    day = current.date()
    for _ in range(400):
        if is_workday(day):
            open_dt = _at_open(day)
            close_dt = _at_close(day)
            if current < open_dt:
                return open_dt
            if current < close_dt:
                return current
        day = day + timedelta(days=1)
        current = _at_open(day)
    raise RuntimeError("business_calendar: could not find next open slot")


def add_business_hours(start: datetime, hours: int | float) -> datetime:
    """Add N business hours from start (skips nights, Sundays, holidays)."""
    if hours <= 0:
        return _aware(start)
    remaining = float(hours) * 3600.0
    current = next_open(start)
    for _ in range(10_000):
        day = _local(current).date()
        close_dt = _at_close(day)
        usable = (close_dt - current).total_seconds()
        if usable <= 0:
            current = next_open(close_dt + timedelta(seconds=1))
            continue
        if remaining <= usable:
            return current + timedelta(seconds=remaining)
        remaining -= usable
        current = next_open(close_dt + timedelta(seconds=1))
    raise RuntimeError("business_calendar: add_business_hours did not converge")
