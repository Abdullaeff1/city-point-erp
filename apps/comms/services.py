"""Notification engine foundation — wraps existing in-app Notification."""

from django.db import IntegrityError
from django.utils import timezone

from apps.comms.models import Notification, NotificationChannel, NotificationDispatch


def notify_in_app(*, user, message: str, ticket=None, event_key: str = "") -> Notification | None:
    """Create in-app notification. Dedup by (user, event_key) when event_key is set."""
    key = (event_key or "").strip()
    if key:
        existing = Notification.objects.filter(user=user, event_key=key).first()
        if existing:
            return existing
    try:
        note = Notification.objects.create(
            user=user, message=message, ticket=ticket, event_key=key
        )
    except IntegrityError:
        return Notification.objects.filter(user=user, event_key=key).first()
    NotificationDispatch.objects.create(
        channel=NotificationChannel.IN_APP,
        status="sent",
        recipient=getattr(user, "email", "") or str(user.pk),
        template_code="in_app.generic",
        payload={"message": message, "event_key": key},
        notification=note,
        sent_at=timezone.now(),
    )
    return note


def enqueue_email(*, recipient: str, template_code: str, payload: dict | None = None) -> NotificationDispatch:
    """Email not sent yet — outbox row for future worker."""
    return NotificationDispatch.objects.create(
        channel=NotificationChannel.EMAIL,
        status="pending",
        recipient=recipient,
        template_code=template_code,
        payload=payload or {},
    )
