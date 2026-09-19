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


def send_invite_email(*, user: User, absolute_url: str) -> None:
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
    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )


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
