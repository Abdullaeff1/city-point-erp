"""Central email send with NotificationDispatch delivery log."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage, send_mail
from django.utils import timezone

from apps.comms.models import NotificationChannel, NotificationDispatch


def send_templated_email(
    *,
    recipient: str,
    subject: str,
    body: str,
    template_code: str,
    payload: dict | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> NotificationDispatch:
    """Send email and log a NotificationDispatch row.

    ``attachments`` — optional list of ``(filename, content_bytes, mimetype)``.
    """
    dispatch = NotificationDispatch.objects.create(
        channel=NotificationChannel.EMAIL,
        status="pending",
        recipient=recipient,
        template_code=template_code,
        payload={"subject": subject, **(payload or {})},
    )
    try:
        if attachments:
            msg = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient],
            )
            for filename, content, mimetype in attachments:
                msg.attach(filename, content, mimetype)
            msg.send(fail_silently=False)
        else:
            send_mail(
                subject,
                body,
                settings.DEFAULT_FROM_EMAIL,
                [recipient],
                fail_silently=False,
            )
    except Exception as exc:  # noqa: BLE001
        dispatch.status = "failed"
        dispatch.error_message = str(exc)[:2000]
        dispatch.save(update_fields=["status", "error_message"])
        raise
    dispatch.status = "sent"
    dispatch.sent_at = timezone.now()
    dispatch.save(update_fields=["status", "sent_at"])
    return dispatch
