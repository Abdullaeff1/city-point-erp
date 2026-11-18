"""Notification engine foundation — wraps existing in-app Notification."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone

from apps.comms.models import Notification, NotificationChannel, NotificationDispatch

MAX_EMAIL_ATTEMPTS = 5


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
        attempt_count=1,
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


def _retry_delay_minutes(attempt: int) -> int:
    # 5, 15, 45, 120, 360 minutes
    ladder = (5, 15, 45, 120, 360)
    idx = max(0, min(attempt - 1, len(ladder) - 1))
    return ladder[idx]


def _send_dispatch_row(row: NotificationDispatch) -> bool:
    payload = row.payload or {}
    code = (payload.get("ticket_code") or "").strip()
    subject = (payload.get("subject") or "").strip()
    if not subject:
        subject = f"City Point — {code}" if code else f"City Point — {row.template_code}"
    body = (payload.get("message") or payload.get("body") or "").strip()
    if not body:
        url = (payload.get("url") or "").strip()
        body = f"{url}\n" if url else f"Bildiriş ({row.template_code})."
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
        row.next_retry_at = None
        row.attempt_count = (row.attempt_count or 0) + 1
        row.save(
            update_fields=["status", "sent_at", "error_message", "next_retry_at", "attempt_count"]
        )
        return True
    except Exception as exc:  # noqa: BLE001
        attempts = (row.attempt_count or 0) + 1
        row.attempt_count = attempts
        row.error_message = str(exc)[:2000]
        if attempts >= MAX_EMAIL_ATTEMPTS:
            row.status = "failed"
            row.next_retry_at = None
        else:
            row.status = "pending"
            row.next_retry_at = timezone.now() + timedelta(minutes=_retry_delay_minutes(attempts))
        row.save(update_fields=["status", "error_message", "attempt_count", "next_retry_at"])
        return False


def flush_pending_email_dispatches(
    *,
    template_prefix: str = "",
    limit: int = 50,
    include_due_retries: bool = True,
) -> dict:
    """Send pending EMAIL NotificationDispatch rows (in-place status update).

    Used for ticket.* outbox (TD-08) and other templated queues.
    Failed rows with ``next_retry_at`` due are re-queued as pending automatically.
    """
    stats = {"attempted": 0, "sent": 0, "failed": 0, "retried": 0}
    now = timezone.now()
    if include_due_retries:
        due = NotificationDispatch.objects.filter(
            channel=NotificationChannel.EMAIL,
            status="pending",
            next_retry_at__isnull=False,
            next_retry_at__lte=now,
        )
        stats["retried"] = due.count()

    qs = NotificationDispatch.objects.filter(
        channel=NotificationChannel.EMAIL,
        status="pending",
    ).filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now)).order_by("created_at")
    if template_prefix:
        qs = qs.filter(template_code__startswith=template_prefix)
    for row in list(qs[: max(1, int(limit))]):
        stats["attempted"] += 1
        if _send_dispatch_row(row):
            stats["sent"] += 1
        else:
            stats["failed"] += 1
    return stats


def requeue_failed_email_dispatches(*, template_prefix: str = "", limit: int = 50) -> int:
    """Ops: move failed rows back to pending for another flush cycle."""
    qs = NotificationDispatch.objects.filter(
        channel=NotificationChannel.EMAIL,
        status="failed",
    ).order_by("created_at")
    if template_prefix:
        qs = qs.filter(template_code__startswith=template_prefix)
    n = 0
    for row in list(qs[: max(1, int(limit))]):
        row.status = "pending"
        row.next_retry_at = timezone.now()
        row.save(update_fields=["status", "next_retry_at"])
        n += 1
    return n
