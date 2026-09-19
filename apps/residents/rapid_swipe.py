"""Detect rapid card swipes (3+ AccessEvents within a short window).

Only 1st-floor (F1) turnstile readers are counted — e.g. F1TurIN / F1TurBack_OUT.
"""

from __future__ import annotations

import re
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.comms.services import notify_in_app
from apps.residents.models import AccessEvent, RapidCardSwipeAlert, ResidentEmployee

WINDOW_SECONDS = 60
MIN_SWIPES = 3
# Look back a bit past the window so bursts spanning sync polls are caught.
LOOKBACK_SECONDS = WINDOW_SECONDS * 3

# City Point AxTrax names: ...\F1TurIN, F1TurBack_OUT, F1TurMXD_IN — not F2/F10.
F1_READER_RE = re.compile(r"F1(?!\d)", re.IGNORECASE)


def is_f1_reader(reader_name: str | None) -> bool:
    return bool(F1_READER_RE.search(reader_name or ""))


def _iso(dt) -> str:
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt.isoformat()


def find_rapid_windows(events: list[AccessEvent], *, window_seconds: int = WINDOW_SECONDS, min_swipes: int = MIN_SWIPES):
    """Yield (window_start, window_end, slice) for each maximal burst of min_swipes within window.

    ``events`` must be ordered by occurred_at ascending.
    Overlapping candidate windows are collapsed: we keep the first hit and skip
    windows whose start falls inside a previously reported burst.
    """
    if len(events) < min_swipes:
        return
    n = len(events)
    reported_until = None
    window = timedelta(seconds=window_seconds)
    i = 0
    while i <= n - min_swipes:
        if reported_until is not None and events[i].occurred_at <= reported_until:
            i += 1
            continue
        j = i + min_swipes - 1
        while j < n and events[j].occurred_at - events[i].occurred_at <= window:
            j += 1
        end_idx = j - 1
        if end_idx - i + 1 >= min_swipes:
            burst = events[i : end_idx + 1]
            yield burst[0].occurred_at, burst[-1].occurred_at, burst
            reported_until = burst[-1].occurred_at
            i = end_idx + 1
        else:
            i += 1


def _open_alert_overlaps(employee_id: int, window_start, window_end) -> bool:
    return RapidCardSwipeAlert.objects.filter(
        employee_id=employee_id,
        acknowledged_at__isnull=True,
        window_start__lte=window_end,
        window_end__gte=window_start,
    ).exists()


def _build_swipes_payload(burst: list[AccessEvent]) -> list[dict]:
    rows = []
    for e in burst:
        rows.append(
            {
                "at": _iso(e.occurred_at),
                "event_type": e.event_type,
                "access_event_id": e.pk,
                "reader_id": e.reader_id,
                "reader_name": (e.reader_name or "").strip(),
            }
        )
    return rows


def _notify_security_users(alert: RapidCardSwipeAlert) -> None:
    message = (
        f"Kart çoxvurma (F1): {alert.employee_name} "
        f"({alert.company_name or '—'}) ×{alert.swipe_count} / {WINDOW_SECONDS}s"
    )[:255]
    users = User.objects.filter(role=Role.SECURITY, is_active=True)
    for user in users:
        notify_in_app(user=user, message=message)


@transaction.atomic
def create_alert_from_burst(employee: ResidentEmployee, burst: list[AccessEvent]) -> RapidCardSwipeAlert | None:
    if len(burst) < MIN_SWIPES:
        return None
    window_start = burst[0].occurred_at
    window_end = burst[-1].occurred_at
    if _open_alert_overlaps(employee.pk, window_start, window_end):
        return None
    if RapidCardSwipeAlert.objects.filter(employee=employee, window_start=window_start).exists():
        return None

    company = employee.company
    card = (burst[-1].card_number or employee.card_number or "")[:32]
    name = (burst[-1].employee_name or employee.full_name or "")[:160]
    try:
        alert = RapidCardSwipeAlert.objects.create(
            employee=employee,
            employee_name=name,
            card_number=card,
            company_id=company.pk if company else None,
            company_name=(company.name if company else "")[:160],
            window_start=window_start,
            window_end=window_end,
            swipe_count=len(burst),
            swipes=_build_swipes_payload(burst),
        )
    except IntegrityError:
        return None
    _notify_security_users(alert)
    return alert


def detect_rapid_swipes_for_employees(
    employee_ids: set[int] | list[int],
    *,
    around=None,
    window_seconds: int = WINDOW_SECONDS,
    min_swipes: int = MIN_SWIPES,
) -> list[RapidCardSwipeAlert]:
    """Scan recent F1-turnstile AccessEvents for the given employees and create alerts."""
    ids = {int(i) for i in employee_ids if i}
    if not ids:
        return []
    around = around or timezone.now()
    lookback_start = around - timedelta(seconds=LOOKBACK_SECONDS)
    created: list[RapidCardSwipeAlert] = []
    employees = {
        e.pk: e
        for e in ResidentEmployee.objects.select_related("company").filter(pk__in=ids)
    }
    for emp_id, employee in employees.items():
        events = [
            e
            for e in AccessEvent.objects.filter(
                employee_id=emp_id,
                occurred_at__gte=lookback_start,
                occurred_at__lte=around + timedelta(seconds=5),
            ).order_by("occurred_at")
            if is_f1_reader(e.reader_name)
        ]
        for window_start, window_end, burst in find_rapid_windows(
            events, window_seconds=window_seconds, min_swipes=min_swipes
        ):
            alert = create_alert_from_burst(employee, burst)
            if alert:
                created.append(alert)
    return created


def detect_rapid_swipes_after_sync(created_events: list[AccessEvent]) -> list[RapidCardSwipeAlert]:
    """Hook for event sync: inspect employees that just received new F1 punches."""
    if not created_events:
        return []
    f1_events = [e for e in created_events if is_f1_reader(e.reader_name)]
    if not f1_events:
        return []
    emp_ids = {e.employee_id for e in f1_events}
    latest = max(e.occurred_at for e in f1_events)
    return detect_rapid_swipes_for_employees(emp_ids, around=latest)
