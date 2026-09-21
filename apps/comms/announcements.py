"""Announcement visibility helpers — portal must never see unscoped private feeds."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.accounts.models import Role
from apps.comms.models import Announcement, AnnouncementVisibility


def announcements_for_user(user) -> QuerySet[Announcement]:
    """Building-wide + company + targeted-to-user. Staff without company see building-wide only."""
    qs = Announcement.objects.all()
    if not user or not user.is_authenticated:
        return qs.none()

    company_id = getattr(user, "resident_company_id", None)
    filters = Q(visibility=AnnouncementVisibility.BUILDING)
    if company_id:
        filters |= Q(visibility=AnnouncementVisibility.COMPANY, company_id=company_id)
        filters |= Q(visibility=AnnouncementVisibility.TARGETED, company_id=company_id, target_users=user)
    elif user.role == Role.RESIDENT_USER:
        return qs.none()
    else:
        # Staff browsing portal: building-wide only (no other company's private feed)
        pass
    return qs.filter(filters).distinct()
