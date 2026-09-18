"""Shared access helpers — AxTrax Attendance / Who-has-been style.

Only işə gəliş (first IN) and işdən çıxış (last OUT) per day.
Raw turnstile flaps are not shown in UI summaries.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from django.utils import timezone

from apps.residents.models import AccessEvent, AccessEventType


def parse_date(value, fallback):
    if not value:
        return fallback
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return fallback


def access_range_bounds(request, *, default_preset="today"):
    today = timezone.localdate()
    preset = (request.GET.get("range") or default_preset).strip().lower()
    if preset not in {"today", "week", "month", "year", "custom"}:
        preset = default_preset

    if preset == "week":
        date_from = today - timedelta(days=today.weekday())
        date_to = today
    elif preset == "month":
        date_from = today.replace(day=1)
        date_to = today
    elif preset == "year":
        try:
            year = int(request.GET.get("year") or today.year)
        except (TypeError, ValueError):
            year = today.year
        date_from = datetime(year, 1, 1).date()
        date_to = today if year == today.year else datetime(year, 12, 31).date()
    elif preset == "custom":
        date_from = parse_date(request.GET.get("from"), today)
        date_to = parse_date(request.GET.get("to"), today)
        if date_from > date_to:
            date_from, date_to = date_to, date_from
    else:
        preset = "today"
        date_from = parse_date(request.GET.get("date"), today)
        date_to = date_from
    return preset, date_from, date_to


def employee_roster_qs(qs, roster: str | None):
    """active (default) | former | all — former = soft-deactivated archive."""
    key = (roster or "active").strip().lower()
    if key == "former":
        return qs.filter(is_active=False), "former"
    if key == "all":
        return qs, "all"
    return qs.filter(is_active=True), "active"


def attendance_for_day(events):
    """AxTrax Attendance / Who-has-been style for one day.

    işə gəliş = first IN (else first punch)
    işdən çıxış = last OUT only when the day ended with OUT (else blank / still inside)
    ``events`` must be ordered by occurred_at ascending.
    """
    if not events:
        return None, None, "—"

    first_in = next((e for e in events if e.event_type == AccessEventType.IN), None)
    last_out = next((e for e in reversed(events) if e.event_type == AccessEventType.OUT), None)
    last_punch = events[-1]

    arrive_at = first_in.occurred_at if first_in else events[0].occurred_at

    if last_punch.event_type == AccessEventType.OUT and last_out:
        return arrive_at, last_out.occurred_at, "Çıxış"
    return arrive_at, None, "İçəridə"


def build_employee_access_rows(employees, selected_date):
    """Who-has-been / daily attendance rows for one date."""
    start_dt = timezone.make_aware(datetime.combine(selected_date, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(selected_date + timedelta(days=1), datetime.min.time()))
    rows = []
    inside = 0
    left = 0
    present = 0
    for emp in employees:
        events = list(
            emp.access_events.filter(occurred_at__gte=start_dt, occurred_at__lt=end_dt).order_by("occurred_at")
        )
        in_at, out_at, status = attendance_for_day(events)
        if events:
            present += 1
            if status == "İçəridə":
                inside += 1
            elif status == "Çıxış":
                left += 1
        rows.append(
            {
                "employee": emp,
                "in_at": in_at,
                "out_at": out_at,
                "status": status,
                "present": bool(events),
            }
        )
    return rows, inside, left, present


def employee_attendance_days(employee, date_from, date_to):
    """One row per day: işə gəliş / işdən çıxış (no raw flaps)."""
    start_dt = timezone.make_aware(datetime.combine(date_from, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    events = AccessEvent.objects.filter(
        employee=employee,
        occurred_at__gte=start_dt,
        occurred_at__lt=end_dt,
    ).order_by("occurred_at")

    by_day = defaultdict(list)
    for e in events:
        by_day[timezone.localtime(e.occurred_at).date()].append(e)

    days = []
    for day in sorted(by_day.keys(), reverse=True):
        arrive_at, leave_at, status = attendance_for_day(by_day[day])
        days.append(
            {
                "date": day,
                "in_at": arrive_at,
                "out_at": leave_at,
                "status": status,
            }
        )
    return days


def employee_day_flaps(employee, day):
    """All IN/OUT punches for one calendar day (chronological)."""
    start_dt = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(day + timedelta(days=1), datetime.min.time()))
    return list(
        AccessEvent.objects.filter(
            employee=employee,
            occurred_at__gte=start_dt,
            occurred_at__lt=end_dt,
        ).order_by("occurred_at")
    )


# Back-compat aliases used by older imports
def day_status(events):
    return attendance_for_day(events)


def employee_events_in_range(employee, date_from, date_to):
    return employee_attendance_days(employee, date_from, date_to)
