"""Announcement visibility helpers — portal must never see unscoped private feeds."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.accounts.models import Role
from apps.comms.models import Announcement, AnnouncementVisibility


def announcements_for_user(user, company_ids=None) -> QuerySet[Announcement]:
    """Building-wide + company + targeted-to-user. Staff without company see building-wide only.

    ``company_ids`` — optional explicit scope (portal session). When omitted, falls back to
    ``user.resident_company_id`` for backward compatibility with tests / non-request callers.
    """
    qs = Announcement.objects.all()
    if not user or not user.is_authenticated:
        return qs.none()

    if company_ids is None:
        cid = getattr(user, "resident_company_id", None)
        ids = [cid] if cid else []
    else:
        ids = [int(i) for i in company_ids if i]

    filters = Q(visibility=AnnouncementVisibility.BUILDING)
    if ids:
        filters |= Q(visibility=AnnouncementVisibility.COMPANY, company_id__in=ids)
        filters |= Q(
            visibility=AnnouncementVisibility.TARGETED,
            company_id__in=ids,
            target_users=user,
        )
    elif user.role == Role.RESIDENT_USER:
        return qs.none()
    else:
        # Staff browsing portal: building-wide only (no other company's private feed)
        pass
    return qs.filter(filters).distinct()
