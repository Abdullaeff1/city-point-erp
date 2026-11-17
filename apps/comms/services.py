"""Notification engine foundation — wraps existing in-app Notification."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
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
    """Email not sent yet — outbox row for ``flush_pending_email_dispatches``."""
    return NotificationDispatch.objects.create(
        channel=NotificationChannel.EMAIL,
        status="pending",
        recipient=recipient,
        template_code=template_code,
        payload=payload or {},
    )


def flush_pending_email_dispatches(
    *,
    template_prefix: str = "",
    limit: int = 50,
) -> dict:
    """Send pending EMAIL NotificationDispatch rows (in-place status update).

    Used for ticket.* outbox (TD-08) and other templated queues.
    """
    stats = {"attempted": 0, "sent": 0, "failed": 0}
    qs = NotificationDispatch.objects.filter(
        channel=NotificationChannel.EMAIL,
        status="pending",
    ).order_by("created_at")
    if template_prefix:
        qs = qs.filter(template_code__startswith=template_prefix)
    for row in list(qs[: max(1, int(limit))]):
        stats["attempted"] += 1
        payload = row.payload or {}
        code = (payload.get("ticket_code") or "").strip()
        subject = (payload.get("subject") or "").strip()
        if not subject:
            subject = f"City Point — {code}" if code else f"City Point — {row.template_code}"
        body = (payload.get("message") or payload.get("body") or "").strip()
        if not body:
            body = f"Bildiriş ({row.template_code})."
        try:
            send_mail(
                subject,
                body,
                settings.DEFAULT_FROM_EMAIL,
                [row.recipient],
                fail_silently=False,
            )
            row.status = "sent"
            row.sent_at = timezone.now()
            row.error_message = ""
            row.save(update_fields=["status", "sent_at", "error_message"])
            stats["sent"] += 1
        except Exception as exc:  # noqa: BLE001
            row.status = "failed"
            row.error_message = str(exc)[:2000]
            row.save(update_fields=["status", "error_message"])
            stats["failed"] += 1
    return stats
