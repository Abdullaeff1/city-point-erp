"""Shared access helpers — AxTrax Attendance / Who-has-been style.

Only işə gəliş (first IN) and işdən çıxış (last OUT) per day.
Raw turnstile flaps are not shown in UI summaries.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from django.utils import timezone

from apps.residents.models import AccessEvent, AccessEventType, AccessResult

# AxTrax Events / Attendance shows both Access Granted (17) and Access Denied (18).
# Some cards (site code 0) only ever log type 18 — still real IN/OUT punches.
ATTENDANCE_RESULTS = (AccessResult.GRANTED, AccessResult.DENIED)


def parse_date(value, fallback):
    if not value:
        return fallback
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return fallback


def previous_calendar_month(today=None):
    """Return (first_day, last_day) of the calendar month before ``today``."""
    today = today or timezone.localdate()
    first_this = today.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    return last_prev.replace(day=1), last_prev


def employee_access_period_context(employee, request, *, default_preset="today") -> dict:
    """Preset + flaps/days for employee detail pages.

    If the requested window is empty but the previous calendar month has punches
    (common early in a new month / stale custom URL), fall back to last month so
    the page is not a blank "Məlumat yoxdur".
    """
    preset, date_from, date_to = access_range_bounds(request, default_preset=default_preset)
    fell_back = False
    single_day = date_from == date_to

    if single_day:
        flaps = employee_day_flaps(employee, date_from)
        days: list = []
        if not flaps:
            lm_from, lm_to = previous_calendar_month()
            lm_days = employee_attendance_days(employee, lm_from, lm_to)
            if lm_days:
                preset, date_from, date_to = "custom", lm_from, lm_to
                single_day = False
                flaps = []
                days = lm_days
                fell_back = True
    else:
        flaps = []
        days = employee_attendance_days(employee, date_from, date_to)
        if not days:
            lm_from, lm_to = previous_calendar_month()
            if (date_from, date_to) != (lm_from, lm_to):
                lm_days = employee_attendance_days(employee, lm_from, lm_to)
                if lm_days:
                    preset, date_from, date_to = "custom", lm_from, lm_to
                    days = lm_days
                    fell_back = True

    if single_day:
        in_count = sum(1 for e in flaps if e.event_type == AccessEventType.IN)
        out_count = len(flaps) - in_count
        present_days = 1 if flaps else 0
    else:
        in_count = out_count = 0
        present_days = len(days)

    return {
        "preset": preset,
        "date_from": date_from,
        "date_to": date_to,
        "single_day": single_day,
        "flaps": flaps,
        "days": days,
        "in_count": in_count,
        "out_count": out_count,
        "present_days": present_days,
        "today": timezone.localdate(),
        "fell_back_to_last_month": fell_back,
    }


def access_range_bounds(request, *, default_preset="today"):
    today = timezone.localdate()
    preset = (request.GET.get("range") or default_preset).strip().lower()
    if preset not in {"today", "week", "month", "last_month", "year", "custom"}:
        preset = default_preset

    if preset == "week":
        date_from = today - timedelta(days=today.weekday())
        date_to = today
    elif preset == "month":
        date_from = today.replace(day=1)
        date_to = today
    elif preset == "last_month":
        # Legacy URL; same as custom previous month (tab removed — use date range).
        date_from, date_to = previous_calendar_month(today)
        preset = "custom"
    elif preset == "year":
        try:
            year = int(request.GET.get("year") or today.year)
        except (TypeError, ValueError):
            year = today.year
        date_from = datetime(year, 1, 1).date()
        date_to = today if year == today.year else datetime(year, 12, 31).date()
    elif preset == "custom":
        # Default custom window = previous calendar month (not "today"),
        # so opening the tab after an empty "Bu ay" still shows useful history.
        default_from, default_to = previous_calendar_month(today)
        date_from = parse_date(request.GET.get("from"), default_from)
        date_to = parse_date(request.GET.get("to"), default_to)
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
            emp.access_events.filter(
                result__in=ATTENDANCE_RESULTS,
                occurred_at__gte=start_dt,
                occurred_at__lt=end_dt,
            ).order_by("occurred_at")
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


def _day_card_meta(day_events, current_card: str) -> dict:
    """Cards used that day + whether any differ from the employee's current badge."""
    cards = []
    seen = set()
    denied = 0
    for e in day_events:
        c = (e.card_number or "").strip()
        if c and c not in seen:
            seen.add(c)
            cards.append(c)
        if getattr(e, "result", None) == AccessResult.DENIED:
            denied += 1
    current = (current_card or "").strip()
    other_cards = [c for c in cards if c != current] if current else list(cards)
    return {
        "cards": cards,
        "cards_label": ", ".join(cards) if cards else "—",
        "has_other_card": bool(other_cards),
        "other_cards": other_cards,
        "has_denied": denied > 0,
        "denied_count": denied,
    }


def employee_attendance_days(employee, date_from, date_to):
    """One row per day: işə gəliş / işdən çıxış + kart(lar) həmin gün.

    History stays on the employee FK (AxTrax person). Prior owners of a reused
    badge are not merged here — their punches remain on their own employee rows.
    When this person used multiple/different cards over time, all days show and
    non-current cards are flagged for the UI.
    """
    start_dt = timezone.make_aware(datetime.combine(date_from, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    events = AccessEvent.objects.filter(
        employee=employee,
        result__in=ATTENDANCE_RESULTS,
        occurred_at__gte=start_dt,
        occurred_at__lt=end_dt,
    ).order_by("occurred_at")

    by_day = defaultdict(list)
    for e in events:
        by_day[timezone.localtime(e.occurred_at).date()].append(e)

    current_card = (employee.card_number or "").strip()
    days = []
    for day in sorted(by_day.keys(), reverse=True):
        day_events = by_day[day]
        arrive_at, leave_at, status = attendance_for_day(day_events)
        meta = _day_card_meta(day_events, current_card)
        days.append(
            {
                "date": day,
                "in_at": arrive_at,
                "out_at": leave_at,
                "status": status,
                **meta,
            }
        )
    return days


def employee_day_flaps(employee, day):
    """All IN/OUT punches for one calendar day (chronological).

    Includes Access Denied (AxTrax type 18) — same stream AxTrax Events shows.
    """
    start_dt = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(day + timedelta(days=1), datetime.min.time()))
    return list(
        AccessEvent.objects.filter(
            employee=employee,
            result__in=ATTENDANCE_RESULTS,
            occurred_at__gte=start_dt,
            occurred_at__lt=end_dt,
        ).order_by("occurred_at")
    )


def currently_inside_employee_rows(selected_date=None):
    """Building-wide: employees whose last punch today is IN (still inside).

    One DB query for all of today's events, then group by employee.
    """
    selected_date = selected_date or timezone.localdate()
    start_dt = timezone.make_aware(datetime.combine(selected_date, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(selected_date + timedelta(days=1), datetime.min.time()))
    events = (
        AccessEvent.objects.filter(
            result__in=ATTENDANCE_RESULTS,
            occurred_at__gte=start_dt,
            occurred_at__lt=end_dt,
        )
        .exclude(employee_id=None)
        .select_related("employee", "employee__company")
        .order_by("occurred_at")
    )
    by_emp: dict[int, list] = defaultdict(list)
    for e in events:
        if e.employee_id is None:
            continue
        by_emp[e.employee_id].append(e)

    rows = []
    for _emp_id, evs in by_emp.items():
        in_at, out_at, status = attendance_for_day(evs)
        if status != "İçəridə":
            continue
        emp = evs[0].employee
        if emp is None:
            continue
        rows.append(
            {
                "kind": "employee",
                "employee": emp,
                "company": getattr(emp, "company", None),
                "name": (emp.full_name or evs[0].employee_name or "—"),
                "card_number": (emp.card_number or evs[0].card_number or ""),
                "in_at": in_at,
                "out_at": out_at,
                "status": status,
                "event_count": len(evs),
            }
        )
    def _company_key(r):
        company = r.get("company")
        name = (getattr(company, "name", None) or "").strip() if company else ""
        label = name or "—"
        return (label == "—", label.casefold(), (r.get("name") or "").casefold())

    rows.sort(key=_company_key)
    return rows


# Back-compat aliases used by older imports
def day_status(events):
    return attendance_for_day(events)


def employee_events_in_range(employee, date_from, date_to):
    return employee_attendance_days(employee, date_from, date_to)
