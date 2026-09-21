"""Portal invite + password set (no public self-registration)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import PortalInvite, Role
from apps.comms.models import NotificationChannel, NotificationDispatch

User = get_user_model()

INVITE_TTL_DAYS = 7


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_portal_invite(*, user: User, invited_by: User | None = None, ttl_days: int = INVITE_TTL_DAYS) -> str:
    """Invalidate prior open invites, create a new one, return raw token."""
    raw = secrets.token_urlsafe(32)
    now = timezone.now()
    with transaction.atomic():
        PortalInvite.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
        PortalInvite.objects.create(
            user=user,
            token_hash=_hash_token(raw),
            expires_at=now + timedelta(days=ttl_days),
            invited_by=invited_by,
        )
        user.must_set_password = True
        user.set_unusable_password()
        user.save(update_fields=["must_set_password", "password"])
    return raw


def get_valid_invite(raw_token: str) -> PortalInvite | None:
    if not raw_token:
        return None
    invite = (
        PortalInvite.objects.select_related("user", "user__resident_company")
        .filter(token_hash=_hash_token(raw_token), used_at__isnull=True)
        .first()
    )
    if not invite or not invite.is_valid:
        return None
    return invite


@transaction.atomic
def consume_invite(raw_token: str, password: str) -> User:
    invite = get_valid_invite(raw_token)
    if not invite:
        raise ValueError("invalid_or_expired")
    user = invite.user
    user.set_password(password)
    user.must_set_password = False
    user.is_active = True
    user.save(update_fields=["password", "must_set_password", "is_active"])
    invite.used_at = timezone.now()
    invite.save(update_fields=["used_at"])
    return user


def invite_url(request, raw_token: str) -> str:
    path = reverse("accounts:invite_accept", kwargs={"token": raw_token})
    return request.build_absolute_uri(path)


def send_invite_email(*, user: User, absolute_url: str) -> NotificationDispatch:
    """Send invite mail and record delivery outcome on NotificationDispatch."""
    company = ""
    if user.resident_company_id:
        company = f" ({user.resident_company.name})"
    subject = "City Point Portal — şifrə təyin edin"
    body = (
        f"Salam {user.get_full_name() or user.email},\n\n"
        f"City Point Resident Portal hesabınız yaradıldı{company}.\n"
        f"Şifrənizi bu linklə təyin edin (7 gün etibarlıdır):\n\n"
        f"{absolute_url}\n\n"
        f"Əgər bu dəvəti gözləmirdinizsə, bu məktubu nəzərə almayın.\n"
    )
    payload = {"subject": subject, "url": absolute_url, "user_id": user.pk}
    dispatch = NotificationDispatch.objects.create(
        channel=NotificationChannel.EMAIL,
        status="pending",
        recipient=user.email,
        template_code="portal.invite",
        payload=payload,
    )
    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 — log delivery failure, re-raise for caller
        dispatch.status = "failed"
        dispatch.error_message = str(exc)[:2000]
        dispatch.save(update_fields=["status", "error_message"])
        raise
    dispatch.status = "sent"
    dispatch.sent_at = timezone.now()
    dispatch.save(update_fields=["status", "sent_at"])
    return dispatch


def retry_failed_invite_dispatches(*, limit: int = 20) -> dict:
    """Re-send failed portal.invite emails (ops / management command)."""
    stats = {"attempted": 0, "sent": 0, "failed": 0}
    qs = NotificationDispatch.objects.filter(
        channel=NotificationChannel.EMAIL,
        template_code="portal.invite",
        status="failed",
    ).order_by("created_at")[:limit]
    for row in qs:
        stats["attempted"] += 1
        url = (row.payload or {}).get("url") or ""
        subject = (row.payload or {}).get("subject") or "City Point Portal — şifrə təyin edin"
        body = (
            f"City Point Resident Portal — şifrə linki:\n\n{url}\n\n"
            if url
            else "Dəvət linki tapılmadı; yenidən invite_portal_user işlədin.\n"
        )
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [row.recipient], fail_silently=False)
            row.status = "sent"
            row.sent_at = timezone.now()
            row.error_message = ""
            row.save(update_fields=["status", "sent_at", "error_message"])
            stats["sent"] += 1
        except Exception as exc:  # noqa: BLE001
            row.error_message = str(exc)[:2000]
            row.save(update_fields=["error_message"])
            stats["failed"] += 1
    return stats


def provision_portal_user(
    *,
    email: str,
    company,
    first_name: str = "",
    last_name: str = "",
    invited_by: User | None = None,
) -> tuple[User, str]:
    """Create or update a resident portal user and issue an invite token."""
    email = email.strip().lower()
    username_base = email.split("@")[0][:140] or "user"
    user = User.objects.filter(email=email).first()
    if user is None:
        username = username_base
        n = 0
        while User.objects.filter(username=username).exists():
            n += 1
            username = f"{username_base}{n}"[:150]
        user = User(
            email=email,
            username=username,
            first_name=(first_name or "")[:150],
            last_name=(last_name or "")[:150],
            role=Role.RESIDENT_USER,
            resident_company=company,
            is_active=True,
            must_set_password=True,
        )
        user.set_unusable_password()
        user.save()
    else:
        user.role = Role.RESIDENT_USER
        user.resident_company = company
        if first_name:
            user.first_name = first_name[:150]
        if last_name:
            user.last_name = last_name[:150]
        user.is_active = True
        user.save()

    raw = create_portal_invite(user=user, invited_by=invited_by)
    return user, raw
