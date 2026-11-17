"""Unified resident object scope: role × company (Party via legacy bridge).

M2: portal/ops SoT remains ResidentCompany; Party is reachable when
``legacy_resident_company_id`` is in the same company id set.
"""

from __future__ import annotations

from typing import Iterable

from django.db.models import QuerySet

from apps.accounts.models import PortalCompanyMembership, Role, User


def accessible_company_ids_for(user: User | None) -> set[int]:
    """Companies a user may touch at object level.

    - Resident: active PortalCompanyMembership + primary ``resident_company_id``.
    - Staff: empty set means *not* company-limited here (ERP uses role/dept ACL).
      If staff has ``resident_company_id``, it is included for portal-style checks.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return set()
    ids: set[int] = set()
    if getattr(user, "role", None) == Role.RESIDENT_USER:
        ids.update(
            PortalCompanyMembership.objects.filter(user=user, is_active=True).values_list(
                "company_id", flat=True
            )
        )
    if getattr(user, "resident_company_id", None):
        ids.add(int(user.resident_company_id))
    return ids


def effective_company_ids(user: User | None, *, company_ids: Iterable[int] | None = None) -> set[int]:
    """Intersect optional request/session scope with membership-based access."""
    base = accessible_company_ids_for(user)
    if company_ids is None:
        return base
    scoped = {int(i) for i in company_ids}
    if not base:
        # Staff with explicit portal session scope
        if getattr(user, "role", None) != Role.RESIDENT_USER:
            return scoped
        return set()
    return base & scoped


def company_accessible(
    user: User | None,
    company_id: int | None,
    *,
    company_ids: Iterable[int] | None = None,
) -> bool:
    if company_id is None:
        return False
    return int(company_id) in effective_company_ids(user, company_ids=company_ids)


def party_accessible(
    user: User | None,
    party,
    *,
    company_ids: Iterable[int] | None = None,
) -> bool:
    """True when Party's legacy company is in resident scope (or staff unrestricted)."""
    if not user or not getattr(user, "is_authenticated", False) or party is None:
        return False
    if getattr(user, "role", None) != Role.RESIDENT_USER:
        return True
    legacy_id = getattr(party, "legacy_resident_company_id", None)
    return company_accessible(user, legacy_id, company_ids=company_ids)


def filter_by_company_ids(qs: QuerySet, company_ids: Iterable[int], *, field: str = "company_id") -> QuerySet:
    ids = list({int(i) for i in company_ids})
    if not ids:
        return qs.none()
    return qs.filter(**{f"{field}__in": ids})
