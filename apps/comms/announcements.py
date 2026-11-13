"""Announcement visibility helpers — portal must never see unscoped private feeds."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.accounts.models import Role
from apps.comms.models import Announcement, AnnouncementVisibility

# RBAC permission code for future designated publishers (Admin-first today).
ANNOUNCEMENT_PUBLISH_PERM = "announcement.publish"


def can_publish_announcement(user) -> bool:
    """Who may create/publish portal announcements.

    Now: Admin (or superuser) only.
    Later: explicit RolePermission for ``announcement.publish`` (not Management blanket
    bypass — spam risk). Seed the permission code; grant via RBAC when ready.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    if getattr(user, "role", None) == Role.ADMIN:
        return True
    # Future hook: designated staff (e.g. ticket_department) via RBAC grant.
    from apps.rbac.models import RolePermission

    return RolePermission.objects.filter(
        role=user.role, permission__code=ANNOUNCEMENT_PUBLISH_PERM
    ).exists()


def announcements_for_user(user, company_ids=None) -> QuerySet[Announcement]:
    """Building-wide + company (1+ via M2M / legacy FK) + targeted-to-user.

    Staff without company see building-wide only.
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
        filters |= Q(visibility=AnnouncementVisibility.COMPANY, companies__id__in=ids)
        # Legacy single FK (pre-M2M) still visible until fully migrated away
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


def sync_legacy_company_fk(announcement: Announcement) -> None:
    """Keep legacy ``company`` FK aligned with ``companies`` M2M for COMPANY scope."""
    if announcement.visibility == AnnouncementVisibility.COMPANY:
        first = announcement.companies.order_by("id").first()
        if announcement.company_id != (first.pk if first else None):
            announcement.company = first
            announcement.save(update_fields=["company"])
    elif announcement.visibility == AnnouncementVisibility.BUILDING:
        if announcement.company_id is not None:
            announcement.company = None
            announcement.save(update_fields=["company"])
