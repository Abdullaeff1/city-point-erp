"""Detect shaft door/reader access (reader leaf name starts with Shaft)."""

from __future__ import annotations

from django.db import IntegrityError, transaction

from apps.accounts.models import Role, User
from apps.comms.services import notify_in_app
from apps.residents.models import AccessEvent, ShaftAccessAlert


def is_shaft_reader(reader_name: str | None) -> bool:
    """True when the AxTrax reader leaf name starts with Shaft (case-insensitive).

    Examples: ``Shaft1``, ``Shaft_IN``, ``20\\Panel\\ShaftA``.
    """
    name = (reader_name or "").strip()
    if not name:
        return False
    leaf = name.replace("/", "\\").rsplit("\\", 1)[-1].strip()
    return leaf.casefold().startswith("shaft")


def _notify_security_users(alert: ShaftAccessAlert) -> None:
    message = (
        f"Şaxta açıldı: {alert.employee_name} "
        f"({alert.company_name or '—'}) · {alert.reader_name or 'Shaft'}"
    )[:255]
    users = User.objects.filter(role=Role.SECURITY, is_active=True)
    for user in users:
        notify_in_app(user=user, message=message)


@transaction.atomic
def create_shaft_alert_from_event(event: AccessEvent) -> ShaftAccessAlert | None:
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
    _notify_security_users(alert)
    return alert


def detect_shaft_access_after_sync(created_events: list[AccessEvent]) -> list[ShaftAccessAlert]:
    """Hook for event sync: one alert per new Shaft* AccessEvent."""
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
