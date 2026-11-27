"""Rəhbərlik davamiyyət hesabatı — gecikmə və binada olma müddəti (Asia/Baku).

City Point daxili işçilər üçün qrafik:
  Bazar ertəsi–Cümə: 09:00 · Şənbə: 10:00–15:00 · Bazar: istirahət.
Yalnız binaya giriş/çıxış oxuyucuları (Tur/Ent); şaft və daxili qapılar hesabdan kənar.
Binada olma = günün ilk girişi ilə son çıxışı arasındakı müddət.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from django.utils import timezone

from apps.residents.access import ATTENDANCE_RESULTS
from apps.residents.models import AccessEvent, AccessEventType, AccessResult
from apps.residents.shaft_access import is_shaft_reader

# City Point weekly schedule (Asia/Baku).
WEEKDAY_WORK_START = time(9, 0, 0)  # Mon–Fri
SATURDAY_WORK_START = time(10, 0, 0)
SATURDAY_WORK_END = time(15, 0, 0)
DEFAULT_WORK_START = WEEKDAY_WORK_START  # backwards-compatible alias
DEFAULT_SCHEDULE_NOTE = (
    "Bazar ertəsi–Cümə: 09:00 · Şənbə: 10:00–15:00 · Bazar: istirahət (Asia/Baku)."
)

# Building perimeter turnstiles / entrances — not shaft or office doors.
BUILDING_READER_RE = re.compile(
    r"(Tur|Turn|Ent|Entrance|Giriş|Cixis|Çıxış|Gate)",
    re.IGNORECASE,
)

AZ_WEEKDAYS = (
    "Bazar ertəsi",
    "Çərşənbə axşamı",
    "Çərşənbə",
    "Cümə axşamı",
    "Cümə",
    "Şənbə",
    "Bazar",
)

STATUS_COMPLETE = "Tam"
STATUS_OPEN_TODAY = "Çıxış yoxdur"
STATUS_INCOMPLETE_NO_EXIT = "Çıxış yoxdur"
STATUS_INCOMPLETE_ORPHAN_OUT = "Çıxış yoxdur"
STATUS_NO_PUNCH = "Keçid yoxdur"
STATUS_FUTURE = "Gələcək"
STATUS_REST = "İstirahət"


@dataclass
class PresenceInterval:
    start: datetime
    end: datetime | None  # None = still open
    closed: bool


@dataclass
class DayAttendance:
    day: date
    weekday_label: str
    expected_start: datetime
    first_in: datetime | None
    last_out: datetime | None
    late_seconds: int
    late_label: str
    is_late: bool
    presence_seconds: int
    presence_label: str
    status: str
    status_detail: str
    intervals: list[PresenceInterval] = field(default_factory=list)
    known_presence_only: bool = False  # True when open/incomplete — sum of closed intervals only
    has_punch: bool = False

    @property
    def late_minutes_floor(self) -> int:
        return max(0, self.late_seconds // 60)


@dataclass
class PeriodSummary:
    days_with_entry: int = 0
    late_days: int = 0
    total_late_seconds: int = 0
    confirmed_presence_seconds: int = 0
    incomplete_days: int = 0
    open_today_days: int = 0


def city_point_company():
    from apps.residents.models import ResidentCompany

    return ResidentCompany.objects.filter(slug="city-point").first()


def city_point_employees_qs(*, roster: str = "active"):
    from apps.residents.access import employee_roster_qs
    from apps.residents.models import ResidentEmployee

    company = city_point_company()
    if company is None:
        return ResidentEmployee.objects.none(), "active", None
    qs = company.employees.all().order_by("full_name")
    qs, roster_key = employee_roster_qs(qs, roster)
    return qs, roster_key, company


@dataclass(frozen=True)
class DaySchedule:
    is_rest: bool
    expected_start: datetime
    expected_end: datetime | None
    note: str


def schedule_for_day(*, employee, day: date) -> DaySchedule:
    """City Point weekly timetable for late/rest calculation."""
    del employee  # reserved for future per-employee WorkSchedule
    wd = day.weekday()  # Mon=0 … Sun=6
    if wd == 6:  # Bazar
        start = timezone.make_aware(datetime.combine(day, WEEKDAY_WORK_START))
        return DaySchedule(
            is_rest=True,
            expected_start=start,
            expected_end=None,
            note=DEFAULT_SCHEDULE_NOTE,
        )
    if wd == 5:  # Şənbə
        start = timezone.make_aware(datetime.combine(day, SATURDAY_WORK_START))
        end = timezone.make_aware(datetime.combine(day, SATURDAY_WORK_END))
        return DaySchedule(
            is_rest=False,
            expected_start=start,
            expected_end=end,
            note=DEFAULT_SCHEDULE_NOTE,
        )
    start = timezone.make_aware(datetime.combine(day, WEEKDAY_WORK_START))
    return DaySchedule(
        is_rest=False,
        expected_start=start,
        expected_end=None,
        note=DEFAULT_SCHEDULE_NOTE,
    )


def expected_start_for(*, employee, day: date) -> tuple[datetime, str]:
    """Return (aware expected start, schedule note). Rest days still return a clock for UI."""
    sched = schedule_for_day(employee=employee, day=day)
    return sched.expected_start, sched.note


def is_rest_day(*, employee, day: date) -> bool:
    return schedule_for_day(employee=employee, day=day).is_rest


def is_building_perimeter_reader(reader_name: str | None) -> bool:
    """True for turnstile/entrance readers used for building arrival/departure."""
    if is_shaft_reader(reader_name):
        return False
    name = (reader_name or "").strip()
    if not name:
        # Legacy rows without reader — keep for attendance (direction still known).
        return True
    return bool(BUILDING_READER_RE.search(name))


def format_duration(seconds: int | None) -> str:
    if seconds is None or seconds <= 0:
        return "0 dəq"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if hours and minutes:
        return f"{hours} saat {minutes} dəq"
    if hours:
        return f"{hours} saat"
    if minutes:
        return f"{minutes} dəq"
    return "<1 dəq"


def format_late(late_seconds: int) -> str:
    if late_seconds <= 0:
        return "—"
    if late_seconds < 60:
        return "<1 dəq"
    return format_duration(late_seconds)


def _local(dt: datetime) -> datetime:
    return timezone.localtime(dt)


def _dedupe_attendance_events(events: list) -> list:
    """Like rapid_swipe.dedupe_near_duplicate_swipes but tolerates plain event stubs."""
    if not events:
        return []
    gap = timedelta(seconds=2)
    kept = [events[0]]
    for e in events[1:]:
        prev = kept[-1]
        same_type = getattr(e, "event_type", None) == getattr(prev, "event_type", None)
        rid = getattr(e, "reader_id", None)
        prid = getattr(prev, "reader_id", None)
        same_reader = (rid and rid == prid) or (
            (getattr(e, "reader_name", None) or "").strip()
            == (getattr(prev, "reader_name", None) or "").strip()
            and bool((getattr(e, "reader_name", None) or "").strip())
        )
        delta = getattr(e, "occurred_at") - getattr(prev, "occurred_at")
        if same_type and same_reader and delta <= gap:
            continue
        kept.append(e)
    return kept


def filter_attendance_events(events: list[AccessEvent]) -> list[AccessEvent]:
    """Perimeter readers only, dedupe near-duplicate AxTrax double-fires."""
    perimeter = [e for e in events if is_building_perimeter_reader(getattr(e, "reader_name", None))]
    # If filtering removed everything but raw events exist (unusual naming), fall back
    # to non-shaft only so history is not silently empty — documented exception.
    if not perimeter and events:
        perimeter = [
            e for e in events if not is_shaft_reader(getattr(e, "reader_name", None))
        ]
    return _dedupe_attendance_events(perimeter)


def pair_presence_intervals(events: list[AccessEvent]) -> tuple[list[PresenceInterval], list[str]]:
    """Pair IN→OUT intervals. Consecutive IN ignored while inside; orphan OUT noted."""
    intervals: list[PresenceInterval] = []
    notes: list[str] = []
    open_in: AccessEvent | None = None
    for e in events:
        if e.event_type == AccessEventType.IN:
            if open_in is None:
                open_in = e
            # Consecutive IN while inside: ignore (does not change first arrival).
            continue
        if e.event_type == AccessEventType.OUT:
            if open_in is not None:
                intervals.append(
                    PresenceInterval(start=open_in.occurred_at, end=e.occurred_at, closed=True)
                )
                open_in = None
            else:
                notes.append("cütsüz çıxış")
    if open_in is not None:
        intervals.append(
            PresenceInterval(start=open_in.occurred_at, end=None, closed=False)
        )
    return intervals, notes


def compute_day_attendance(*, employee, day: date, events: list[AccessEvent] | None = None) -> DayAttendance:
    """Unified daily calculation for one City Point employee."""
    today = timezone.localdate()
    sched = schedule_for_day(employee=employee, day=day)
    expected = sched.expected_start
    weekday_label = AZ_WEEKDAYS[day.weekday()]

    if day > today:
        return DayAttendance(
            day=day,
            weekday_label=weekday_label,
            expected_start=expected,
            first_in=None,
            last_out=None,
            late_seconds=0,
            late_label="—",
            is_late=False,
            presence_seconds=0,
            presence_label="—",
            status=STATUS_REST if sched.is_rest else STATUS_FUTURE,
            status_detail="",
            has_punch=False,
        )

    if events is None:
        events = _load_day_events(employee, day)
    events = filter_attendance_events(list(events))
    intervals, orphan_notes = pair_presence_intervals(events)

    first_in = None
    for e in events:
        if e.event_type == AccessEventType.IN and first_in is None:
            first_in = e.occurred_at

    last_closed_out = None
    for iv in intervals:
        if iv.closed and iv.end is not None:
            last_closed_out = iv.end

    has_open = any(not iv.closed for iv in intervals)
    # Son çıxış: yalnız bağlanmış OUT (açıq intervalda naməlum çıxış doldurulmur).
    last_out = last_closed_out
    # Binada olma = ilk giriş − son çıxış (fasilələr çıxılmır).
    # Ekranda HH:MM göstərildiyi üçün müddət dəqiqəyə yuvarlaqlanmış saatlarla hesablanır
    # (09:10 → 18:03 = 8 saat 53 dəq; saniyə fərqi «8 saat 52» etməsin).
    presence_seconds = 0
    if first_in is not None and last_out is not None:
        in_m = _local(first_in).replace(second=0, microsecond=0)
        out_m = _local(last_out).replace(second=0, microsecond=0)
        presence_seconds = max(0, int((out_m - in_m).total_seconds()))

    # Bazar — istirahət: gecikmə hesablanmır; keçid olsa belə qeyd «İstirahət».
    if sched.is_rest:
        if first_in is not None and last_out is not None and presence_seconds:
            presence_label = format_duration(presence_seconds)
        elif events:
            presence_label = "—" if last_out is None else format_duration(presence_seconds)
        else:
            presence_label = "—"
        return DayAttendance(
            day=day,
            weekday_label=weekday_label,
            expected_start=expected,
            first_in=first_in,
            last_out=last_out,
            late_seconds=0,
            late_label="—",
            is_late=False,
            presence_seconds=presence_seconds,
            presence_label=presence_label,
            status=STATUS_REST,
            status_detail="",
            intervals=intervals,
            known_presence_only=bool(events) and last_out is None,
            has_punch=bool(events),
        )

    late_seconds = 0
    is_late = False
    if first_in is not None:
        delta = (_local(first_in) - _local(expected)).total_seconds()
        if delta > 0:
            late_seconds = int(delta)
            is_late = True

    # UI/Excel: qısa vəziyyət — «Tam», «Çıxış yoxdur», «Keçid yoxdur».
    if not events:
        status = STATUS_NO_PUNCH
        detail = ""
        presence_label = "—"
        known_only = False
    elif has_open and day == today:
        status = STATUS_OPEN_TODAY
        detail = ""
        # Son çıxış yoxdursa müddət hesab edilmir.
        presence_label = "—" if last_out is None else format_duration(presence_seconds)
        known_only = True
    elif has_open:
        status = STATUS_INCOMPLETE_NO_EXIT
        detail = ""
        presence_label = "—" if last_out is None else format_duration(presence_seconds)
        known_only = True
    elif orphan_notes and not intervals:
        status = STATUS_INCOMPLETE_ORPHAN_OUT
        detail = ""
        presence_label = "—"
        known_only = True
    else:
        status = STATUS_COMPLETE
        detail = ""
        presence_label = format_duration(presence_seconds) if presence_seconds else "—"
        known_only = False

    return DayAttendance(
        day=day,
        weekday_label=weekday_label,
        expected_start=expected,
        first_in=first_in,
        last_out=last_out,
        late_seconds=late_seconds,
        late_label=format_late(late_seconds),
        is_late=is_late,
        presence_seconds=presence_seconds,
        presence_label=presence_label,
        status=status,
        status_detail=detail,
        intervals=intervals,
        known_presence_only=known_only,
        has_punch=bool(events),
    )


def _load_day_events(employee, day: date) -> list[AccessEvent]:
    start_dt = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(day + timedelta(days=1), datetime.min.time()))
    return list(
        AccessEvent.objects.filter(
            employee=employee,
            result__in=ATTENDANCE_RESULTS,
            occurred_at__gte=start_dt,
            occurred_at__lt=end_dt,
        ).order_by("occurred_at", "id")
    )


def _load_range_events(employee_ids: list[int], date_from: date, date_to: date):
    start_dt = timezone.make_aware(datetime.combine(date_from, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    return (
        AccessEvent.objects.filter(
            employee_id__in=employee_ids,
            result__in=ATTENDANCE_RESULTS,
            occurred_at__gte=start_dt,
            occurred_at__lt=end_dt,
        )
        .order_by("occurred_at", "id")
    )


def late_employees_for_day(*, day: date | None = None, roster: str = "active", q: str = ""):
    """City Point staff late on ``day``, most late first. Same rules as period report."""
    from django.db.models import Q

    day = day or timezone.localdate()
    qs, roster_key, company = city_point_employees_qs(roster=roster)
    if company is None:
        return [], 0, DEFAULT_SCHEDULE_NOTE, roster_key
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(card_number__icontains=q))
    employees = list(qs)
    if not employees:
        return [], 0, DEFAULT_SCHEDULE_NOTE, roster_key

    emp_ids = [e.pk for e in employees]
    events = list(_load_range_events(emp_ids, day, day))
    by_emp: dict[int, list] = {}
    for e in events:
        by_emp.setdefault(e.employee_id, []).append(e)

    rows = []
    for emp in employees:
        att = compute_day_attendance(employee=emp, day=day, events=by_emp.get(emp.pk, []))
        if not att.is_late:
            continue
        rows.append(
            {
                "employee": emp,
                "department": "—",  # şöbə master-data-da yoxdur
                "expected_start": att.expected_start,
                "first_in": att.first_in,
                "late_seconds": att.late_seconds,
                "late_label": att.late_label,
                "attendance": att,
            }
        )
    rows.sort(key=lambda r: (-r["late_seconds"], (r["employee"].full_name or "").casefold()))
    return rows, len(rows), DEFAULT_SCHEDULE_NOTE, roster_key


def week_bounds(anchor: date | None = None) -> tuple[date, date]:
    """Monday–Sunday containing ``anchor`` (Asia/Baku local date)."""
    anchor = anchor or timezone.localdate()
    start = anchor - timedelta(days=anchor.weekday())
    end = start + timedelta(days=6)
    return start, end


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def period_days(date_from: date, date_to: date) -> list[date]:
    cur = date_from
    out = []
    while cur <= date_to:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def resolve_attendance_period(request, *, default_preset: str = "today") -> dict:
    """Parse range controls for the employee attendance card / Excel.

    Returns preset, date_from, date_to, error (AZ) — inclusive bounds, Asia/Baku dates.
    Week = Monday–Sunday containing the anchor date. Month/year = full calendar span.
    """
    from datetime import datetime as dt

    today = timezone.localdate()
    preset = (request.GET.get("range") or default_preset).strip().lower()
    if preset in {"day", "günlük", "gunluk"}:
        preset = "today"
    if preset in {"həftəlik", "heftelik"}:
        preset = "week"
    if preset in {"aylıq", "ayliq"}:
        preset = "month"
    if preset in {"illik"}:
        preset = "year"
    if preset not in {"today", "week", "month", "year", "custom"}:
        preset = default_preset

    error = ""
    if preset == "today":
        day = today
        raw = (request.GET.get("date") or "").strip()
        if raw:
            try:
                day = dt.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                error = "Tarix formatı yanlışdır (YYYY-MM-DD)."
        date_from = date_to = day
    elif preset == "week":
        anchor = today
        raw = (request.GET.get("week_start") or request.GET.get("date") or "").strip()
        if raw:
            try:
                anchor = dt.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                error = "Həftə tarixi formatı yanlışdır."
        date_from, date_to = week_bounds(anchor)
    elif preset == "month":
        y, m = today.year, today.month
        try:
            y = int(request.GET.get("year") or y)
            m = int(request.GET.get("month") or m)
            if m < 1 or m > 12:
                raise ValueError("month")
        except (TypeError, ValueError):
            error = "Ay və ya il yanlışdır."
            y, m = today.year, today.month
        date_from, date_to = month_bounds(y, m)
    elif preset == "year":
        try:
            y = int(request.GET.get("year") or today.year)
        except (TypeError, ValueError):
            y = today.year
            error = "İl yanlışdır."
        date_from = date(y, 1, 1)
        date_to = date(y, 12, 31)
    else:  # custom
        raw_from = (request.GET.get("from") or "").strip()
        raw_to = (request.GET.get("to") or "").strip()
        try:
            date_from = dt.strptime(raw_from, "%Y-%m-%d").date() if raw_from else today
            date_to = dt.strptime(raw_to, "%Y-%m-%d").date() if raw_to else date_from
        except ValueError:
            date_from = date_to = today
            error = "Tarix aralığı formatı yanlışdır (YYYY-MM-DD)."
        if not error and date_to < date_from:
            error = "Son tarix başlanğıc tarixdən əvvəl ola bilməz."
            date_to = date_from

    late_only = (request.GET.get("content") or request.GET.get("late_only") or "").strip().lower() in {
        "late",
        "1",
        "true",
        "yes",
        "geciken",
        "gecikən",
    }
    return {
        "preset": preset,
        "date_from": date_from,
        "date_to": date_to,
        "late_only": late_only,
        "error": error,
        "single_day": date_from == date_to,
    }


def _summarize_rows(rows: list[DayAttendance], *, today: date) -> PeriodSummary:
    summary = PeriodSummary()
    for att in rows:
        if att.day > today:
            continue
        if att.status == STATUS_REST:
            # İstirahət günü gecikmə/natamam/iş günü cəminə düşmür.
            continue
        if att.has_punch:
            summary.days_with_entry += 1
        if att.is_late:
            summary.late_days += 1
            summary.total_late_seconds += att.late_seconds
        if att.status == STATUS_COMPLETE:
            summary.confirmed_presence_seconds += att.presence_seconds
        elif att.status == STATUS_OPEN_TODAY:
            summary.open_today_days += 1
            summary.confirmed_presence_seconds += att.presence_seconds
        elif att.status in {STATUS_INCOMPLETE_NO_EXIT, STATUS_INCOMPLETE_ORPHAN_OUT}:
            summary.incomplete_days += 1
            summary.confirmed_presence_seconds += att.presence_seconds
    return summary


def employee_period_report(
    *,
    employee,
    date_from: date,
    date_to: date,
    late_only: bool = False,
) -> dict:
    """Day rows + totals for one employee. Future dates excluded from totals.

    ``late_only`` filters display rows to late days; summary matches the filter.
    """
    today = timezone.localdate()
    days = period_days(date_from, date_to)
    events = list(_load_range_events([employee.pk], date_from, date_to))
    by_day: dict[date, list] = {}
    for e in events:
        d = timezone.localtime(e.occurred_at).date()
        by_day.setdefault(d, []).append(e)

    all_rows: list[DayAttendance] = []
    for day in days:
        all_rows.append(
            compute_day_attendance(employee=employee, day=day, events=by_day.get(day, []))
        )

    full_summary = _summarize_rows(all_rows, today=today)
    if late_only:
        rows = [r for r in all_rows if r.is_late]
        summary = _summarize_rows(rows, today=today)
        presence_scope = "selected_rows"
        presence_scope_label = "Binada olma cəmi: yalnız seçilmiş (gecikilən) günlər"
    else:
        rows = all_rows
        summary = full_summary
        presence_scope = "full_period"
        presence_scope_label = "Binada olma cəmi: seçilmiş dövrün bütün günləri"

    no_late = summary.late_days == 0
    return {
        "employee": employee,
        "date_from": date_from,
        "date_to": date_to,
        "late_only": late_only,
        "all_rows": all_rows,
        "rows": rows,
        "summary": summary,
        "full_summary": full_summary,
        "schedule_note": DEFAULT_SCHEDULE_NOTE,
        "summary_late_label": format_late(summary.total_late_seconds),
        "summary_presence_label": format_duration(summary.confirmed_presence_seconds),
        "presence_scope": presence_scope,
        "presence_scope_label": presence_scope_label,
        "no_late_message": "Bu dövrdə gecikmə qeydə alınmayıb" if no_late else "",
        "filter_label": "Yalnız gecikilən günlər" if late_only else "Bütün günlər",
    }


def whatsapp_week_summary_text(*, employee, week_start: date | None = None) -> dict:
    """Personal weekly summary for one employee (preview only — no send)."""
    start, end = week_bounds(week_start)
    # Clamp end to today for "completed week" preview when current week incomplete
    today = timezone.localdate()
    report_end = min(end, today)
    report = employee_period_report(employee=employee, date_from=start, date_to=end)
    lines = [
        f"City Point — həftəlik davamiyyət",
        f"{employee.full_name}",
        f"{start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}",
        f"({DEFAULT_SCHEDULE_NOTE})",
        "",
    ]
    for row in report["rows"]:
        if row.day > today:
            continue
        if row.status == STATUS_REST:
            lines.append(f"{row.day.strftime('%d.%m')} ({row.weekday_label}): istirahət")
            continue
        in_s = _local(row.first_in).strftime("%H:%M") if row.first_in else "—"
        out_s = _local(row.last_out).strftime("%H:%M") if row.last_out else "—"
        line = (
            f"{row.day.strftime('%d.%m')} ({row.weekday_label}): "
            f"giriş {in_s}, çıxış {out_s}, binada {row.presence_label}, "
            f"gecikmə {row.late_label}"
        )
        if row.status not in {STATUS_COMPLETE, STATUS_NO_PUNCH}:
            line += f" [{row.status}]"
        lines.append(line)
    s = report["summary"]
    lines.extend(
        [
            "",
            "Yekun:",
            f"· Giriş olan günlər: {s.days_with_entry}",
            f"· Gecikilən günlər: {s.late_days}",
            f"· Ümumi gecikmə: {report['summary_late_label']}",
            f"· Təsdiqlənmiş binada olma: {report['summary_presence_label']}",
            f"· Natamam günlər: {s.incomplete_days}",
        ]
    )
    text = "\n".join(lines)
    dedupe_key = f"attendance.wa.week.{employee.pk}.{start.isoformat()}"
    return {
        "text": text,
        "week_start": start,
        "week_end": end,
        "report_end": report_end,
        "dedupe_key": dedupe_key,
        "sent": False,  # live send is a separate City Point decision
        "report": report,
    }


def attendance_xlsx_filename(*, employee, date_from: date, date_to: date, late_only: bool = False) -> str:
    raw = (employee.full_name or f"isci_{employee.pk}").strip()
    safe = re.sub(r"[^\w\-]+", "_", raw, flags=re.UNICODE).strip("_")[:40] or f"id{employee.pk}"
    content = "geciken" if late_only else "butun"
    if date_from.month == date_to.month and date_from.year == date_to.year:
        return f"CityPoint_Report_{safe}_{date_from.year}-{date_from.month:02d}_{content}.xlsx"
    return f"CityPoint_Report_{safe}_{date_from.isoformat()}_{date_to.isoformat()}_{content}.xlsx"


def _axtrax_style_duration(seconds: int) -> str:
    """AxTrax report style: H:MM."""
    if seconds <= 0:
        return "0:00"
    hours, rem = divmod(int(seconds), 3600)
    minutes = rem // 60
    return f"{hours}:{minutes:02d}"


def attendance_xlsx_bytes(
    *,
    employee,
    date_from: date,
    date_to: date,
    late_only: bool = False,
    report: dict | None = None,
) -> bytes:
    """Tək işçi Excel — CityPoint_Report (AxTrax) tərtibatı + Gecikmə / Qeyd sütunları."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    report = report or employee_period_report(
        employee=employee, date_from=date_from, date_to=date_to, late_only=late_only
    )

    # AxTrax id (ops fayllarında #IdEmpNum)
    axtrax_id = None
    try:
        from django.contrib.contenttypes.models import ContentType

        from apps.integrations.axtrax_people_sync import AXTRAX_SYSTEM
        from apps.integrations.models import ExternalIdentity
        from apps.residents.models import ResidentEmployee as RE

        ct = ContentType.objects.get_for_model(RE)
        ext = (
            ExternalIdentity.objects.filter(
                system=AXTRAX_SYSTEM,
                entity_type=ct,
                entity_id=employee.pk,
                external_id__startswith="emp:",
            )
            .values_list("external_id", flat=True)
            .first()
        )
        if ext:
            axtrax_id = int(str(ext).split(":", 1)[1])
    except Exception:  # noqa: BLE001
        axtrax_id = None

    parts = (employee.full_name or "").strip().split()
    if len(parts) >= 2:
        name_ax = f"{parts[-1]},{' '.join(parts[:-1])}"
    else:
        name_ax = employee.full_name or ""
    heading_bits = ["İşçi:", name_ax]
    if (employee.card_number or "").strip():
        heading_bits.append(employee.card_number.strip())
    if axtrax_id:
        heading_bits.append(f"#{axtrax_id}")
    emp_heading = " ".join(heading_bits)

    company_name = getattr(getattr(employee, "company", None), "name", None) or "City Point"
    filter_label = report.get("filter_label") or (
        "Yalnız gecikilən günlər" if late_only else "Bütün günlər"
    )
    period_label = f"{date_from.strftime('%d.%m.%Y')} – {date_to.strftime('%d.%m.%Y')}"

    wb = Workbook()
    ws = wb.active
    ws.title = "Hesabat"

    title_font = Font(name="Calibri", size=11, bold=True)
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    cell_font = Font(name="Calibri", size=11)
    late_font = Font(name="Calibri", size=11, bold=True, color="C00000")
    left = Alignment(horizontal="left", vertical="center")
    center = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="64748B")
    medium = Side(style="medium", color="1F497D")
    emp_fill = PatternFill("solid", fgColor="D6E3F0")
    header_fill = PatternFill("solid", fgColor="1F497D")
    alt_fill = PatternFill("solid", fgColor="F8FAFC")
    ncols = 7

    def _box(*, left_edge=False, right_edge=False, top_edge=False, bottom_edge=False):
        return Border(
            left=medium if left_edge else thin,
            right=medium if right_edge else thin,
            top=medium if top_edge else thin,
            bottom=medium if bottom_edge else thin,
        )

    for col, width in enumerate((12, 16, 10, 10, 10, 12, 14), start=1):
        ws.column_dimensions[chr(64 + col)].width = width

    row = 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    cell = ws.cell(row=row, column=1, value=f"Şöbə: {company_name}")
    cell.font = title_font
    cell.alignment = left
    for col in range(1, ncols + 1):
        c = ws.cell(row=row, column=col)
        c.fill = emp_fill
        c.border = _box(left_edge=col == 1, right_edge=col == ncols, top_edge=True)
    row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    cell = ws.cell(row=row, column=1, value=emp_heading)
    cell.font = title_font
    cell.alignment = left
    for col in range(1, ncols + 1):
        c = ws.cell(row=row, column=col)
        c.fill = emp_fill
        c.border = _box(left_edge=col == 1, right_edge=col == ncols)
    row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    cell = ws.cell(
        row=row,
        column=1,
        value=f"Dövr: {period_label} · Filtr: {filter_label}",
    )
    cell.font = cell_font
    cell.alignment = left
    for col in range(1, ncols + 1):
        c = ws.cell(row=row, column=col)
        c.fill = emp_fill
        c.border = _box(left_edge=col == 1, right_edge=col == ncols, bottom_edge=True)
    row += 1

    s = report["summary"]
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    yekun = (
        f"Yekun: gecikilən günlər {s.late_days} · cəmi gecikmə {report['summary_late_label']} · "
        f"giriş günləri {s.days_with_entry}"
    )
    if late_only and report.get("no_late_message"):
        yekun = report["no_late_message"]
    cell = ws.cell(row=row, column=1, value=yekun)
    cell.font = title_font
    cell.alignment = left
    row += 1

    headers = ("Tarix", "Gün", "Giriş", "Çıxış", "Müddət", "Gecikmə", "Qeyd")
    header_row = row
    for col, label in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
        cell.border = _box(left_edge=col == 1, right_edge=col == ncols)
    row += 1

    missing = "----------"
    rows = list(report["rows"])
    for day_i, att in enumerate(rows):
        is_rest = att.status == STATUS_REST
        if att.first_in:
            in_s = _local(att.first_in).strftime("%H:%M")
        elif is_rest:
            in_s = "—"
        else:
            in_s = missing if not late_only else ""
        if att.last_out:
            out_s = _local(att.last_out).strftime("%H:%M")
        elif att.first_in:
            out_s = ""  # çıxış yoxdur — boş; qeyd sütununda status
        elif is_rest:
            out_s = "—"
        else:
            out_s = missing if not late_only else ""
        if is_rest and not att.presence_seconds:
            dur = "—"
        else:
            dur = _axtrax_style_duration(att.presence_seconds) if att.presence_seconds else "0:00"
        late_s = _axtrax_style_duration(att.late_seconds) if att.is_late else ""
        values = [
            att.day.strftime("%d.%m.%Y"),
            att.weekday_label,
            in_s,
            out_s,
            dur,
            late_s,
            att.status,
        ]
        is_last = day_i == len(rows) - 1
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.font = late_font if col == 6 and att.is_late else cell_font
            cell.alignment = center if col != 2 else left
            if day_i % 2 == 1:
                cell.fill = alt_fill
            cell.border = _box(
                left_edge=col == 1,
                right_edge=col == ncols,
                bottom_edge=is_last,
            )
        row += 1

    if not rows:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
        msg = report.get("no_late_message") or "Seçilmiş dövr üçün məlumat yoxdur."
        cell = ws.cell(row=row, column=1, value=msg)
        cell.font = cell_font

    ws.auto_filter.ref = f"A{header_row}:G{max(header_row, row - 1)}"
    ws.freeze_panes = f"A{header_row + 1}"

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
