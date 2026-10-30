"""Explicit service for PortalCompanyMembership ↔ User.resident_company sync.

No model signals — callers must use these helpers so FK and memberships stay aligned.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts.models import PortalCompanyMembership, User


@transaction.atomic
def set_user_memberships(
    *,
    user: User,
    company_ids: list[int],
    primary_company_id: int | None = None,
    created_by: User | None = None,
    replace: bool = True,
) -> list[PortalCompanyMembership]:
    """Assign active memberships for ``company_ids``.

    - Deactivates memberships not in ``company_ids`` when ``replace`` is True.
    - Ensures exactly one active primary among the assigned set.
    - Syncs ``user.resident_company`` to the primary company.
    """
    company_ids = [int(cid) for cid in company_ids if cid]
    if not company_ids:
        raise ValidationError(_("Ən azı bir aktiv şirkət üzvlüyü tələb olunur."))

    if primary_company_id is None:
        primary_company_id = company_ids[0]
    primary_company_id = int(primary_company_id)
    if primary_company_id not in company_ids:
        raise ValidationError(_("Primary şirkət aktiv üzvlük siyahısında olmalıdır."))

    existing = {
        m.company_id: m
        for m in PortalCompanyMembership.objects.select_for_update().filter(user=user)
    }
    result: list[PortalCompanyMembership] = []

    for cid in company_ids:
        membership = existing.get(cid)
        if membership is None:
            membership = PortalCompanyMembership(
                user=user,
                company_id=cid,
                created_by=created_by,
            )
        membership.is_active = True
        membership.is_primary = cid == primary_company_id
        if membership.pk is None and created_by is not None:
            membership.created_by = created_by
        membership.save()
        result.append(membership)

    if replace:
        PortalCompanyMembership.objects.filter(user=user).exclude(company_id__in=company_ids).update(
            is_active=False,
            is_primary=False,
        )

    # Clear primary on any other active rows (safety)
    PortalCompanyMembership.objects.filter(user=user, is_active=True).exclude(
        company_id=primary_company_id
    ).update(is_primary=False)

    user.resident_company_id = primary_company_id
    user.save(update_fields=["resident_company"])
    return result


@transaction.atomic
def add_membership(
    *,
    user: User,
    company,
    is_primary: bool = False,
    created_by: User | None = None,
) -> PortalCompanyMembership:
    company_id = company.pk if hasattr(company, "pk") else int(company)
    membership, _created = PortalCompanyMembership.objects.get_or_create(
        user=user,
        company_id=company_id,
        defaults={"created_by": created_by, "is_active": True, "is_primary": False},
    )
    membership.is_active = True
    if is_primary or not PortalCompanyMembership.objects.filter(user=user, is_active=True, is_primary=True).exists():
        PortalCompanyMembership.objects.filter(user=user, is_active=True).update(is_primary=False)
        membership.is_primary = True
        user.resident_company_id = company_id
        user.save(update_fields=["resident_company"])
    membership.save()
    return membership


@transaction.atomic
def deactivate_membership(*, user: User, company) -> PortalCompanyMembership | None:
    company_id = company.pk if hasattr(company, "pk") else int(company)
    membership = PortalCompanyMembership.objects.filter(user=user, company_id=company_id).first()
    if not membership:
        return None
    was_primary = membership.is_primary
    membership.is_active = False
    membership.is_primary = False
    membership.save(update_fields=["is_active", "is_primary", "updated_at"])

    active = list(
        PortalCompanyMembership.objects.filter(user=user, is_active=True).order_by("-is_primary", "id")
    )
    if was_primary and active:
        primary = active[0]
        primary.is_primary = True
        primary.save(update_fields=["is_primary", "updated_at"])
        user.resident_company_id = primary.company_id
        user.save(update_fields=["resident_company"])
    elif not active:
        user.resident_company = None
        user.save(update_fields=["resident_company"])
    return membership


def validate_user_memberships(user: User) -> None:
    """Raise ValidationError if active/primary rules are broken."""
    active = list(PortalCompanyMembership.objects.filter(user=user, is_active=True))
    if user.role == "resident_user" and not active and not user.resident_company_id:
        raise ValidationError(_("Rezident istifadəçinin ən azı bir aktiv şirkət üzvlüyü olmalıdır."))
    primaries = [m for m in active if m.is_primary]
    if active and len(primaries) != 1:
        raise ValidationError(_("Aktiv üzvlüklər arasında tam bir primary olmalıdır."))
    if primaries and user.resident_company_id != primaries[0].company_id:
        raise ValidationError(_("User.resident_company primary üzvlüklə uyğun gəlmir."))
