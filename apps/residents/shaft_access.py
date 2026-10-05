"""Detect shaft door/reader access (City Point F#Shaft* AxTrax readers)."""

from __future__ import annotations

import re

from django.db import IntegrityError, transaction

from apps.accounts.models import Role, User
from apps.comms.services import notify_in_app
from apps.residents.models import AccessEvent, ShaftAccessAlert

# Real AxTrax leaf names: F1ShaftCooling, F5ShaftElectric, F7ShaftIT, …
SHAFT_READER_RE = re.compile(r"F\d+SHAFT", re.IGNORECASE)


def is_shaft_reader(reader_name: str | None) -> bool:
    """True for City Point shaft readers ``F{{n}}Shaft…`` (case-insensitive).

    Examples: ``13\\Panel 1\\F1ShaftElectric``, ``F5ShaftCooling``, ``f7shaftit``.
    Does not match bare ``Shaft1`` or turnstiles like ``F1TurIN``.
    """
    name = (reader_name or "").strip()
    if not name:
        return False
    leaf = name.replace("/", "\\").rsplit("\\", 1)[-1].strip()
    return bool(SHAFT_READER_RE.search(leaf))


def _notify_security_users(alert: ShaftAccessAlert) -> None:
    message = (
        f"Şaxta açıldı: {alert.employee_name} "
        f"({alert.company_name or '—'}) · {alert.reader_name or 'Shaft'}"
    )[:255]
    users = User.objects.filter(role=Role.SECURITY, is_active=True)
    for user in users:
        notify_in_app(user=user, message=message)


@transaction.atomic
def create_shaft_alert_from_event(
    event: AccessEvent, *, notify: bool = True
) -> ShaftAccessAlert | None:
    if not is_shaft_reader(event.reader_name):
        return None
    if ShaftAccessAlert.objects.filter(access_event_id=event.pk).exists():
        return None
    employee = event.employee
    if employee is None:
        return None
    company = getattr(employee, "company", None)
    try:
        alert = ShaftAccessAlert.objects.create(
            employee=employee,
            access_event=event,
            employee_name=(event.employee_name or employee.full_name or "")[:160],
            card_number=(event.card_number or employee.card_number or "")[:32],
            company_id=company.pk if company else None,
            company_name=(company.name if company else "")[:160],
            occurred_at=event.occurred_at,
            event_type=event.event_type,
            reader_id=event.reader_id,
            reader_name=(event.reader_name or "").strip()[:255],
        )
    except IntegrityError:
        return None
    if notify:
        _notify_security_users(alert)
    return alert


def backfill_shaft_alerts_for_day(day=None, *, notify: bool = False) -> list[ShaftAccessAlert]:
    """Create missing shaft alerts for AccessEvents on a local calendar day."""
    from datetime import timedelta

    from django.utils import timezone as dj_tz

    when = dj_tz.localtime(day) if day is not None else dj_tz.localtime()
    start = when.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    events = (
        AccessEvent.objects.filter(occurred_at__gte=start, occurred_at__lt=end)
        .select_related("employee", "employee__company")
        .order_by("occurred_at")
    )
    created: list[ShaftAccessAlert] = []
    for event in events:
        if not is_shaft_reader(event.reader_name):
            continue
        alert = create_shaft_alert_from_event(event, notify=notify)
        if alert:
            created.append(alert)
    return created


def detect_shaft_access_after_sync(created_events: list[AccessEvent]) -> list[ShaftAccessAlert]:
    """Hook for event sync: one alert per new F#Shaft AccessEvent."""
    created: list[ShaftAccessAlert] = []
    # Prefetch company for notify snapshots
    event_ids = [e.pk for e in created_events if is_shaft_reader(e.reader_name)]
    if not event_ids:
        return []
    events = (
        AccessEvent.objects.filter(pk__in=event_ids)
        .select_related("employee", "employee__company")
        .order_by("occurred_at")
    )
    for event in events:
        alert = create_shaft_alert_from_event(event)
        if alert:
            created.append(alert)
    return created
