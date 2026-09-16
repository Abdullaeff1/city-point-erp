"""Notification engine foundation — wraps existing in-app Notification."""

from django.utils import timezone

from apps.comms.models import Notification, NotificationChannel, NotificationDispatch


def notify_in_app(*, user, message: str, ticket=None) -> Notification:
    note = Notification.objects.create(user=user, message=message, ticket=ticket)
    NotificationDispatch.objects.create(
        channel=NotificationChannel.IN_APP,
        status="sent",
        recipient=getattr(user, "email", "") or str(user.pk),
        template_code="in_app.generic",
        payload={"message": message},
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
