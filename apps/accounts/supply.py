"""Təchizat şöbəsi portal helpers — Service Desk role + optional supply.head."""

from __future__ import annotations

from apps.accounts.models import Role
from apps.rbac.services import user_has_permission


def is_supply_head(user) -> bool:
    """Designated Head of Supply via explicit ``supply.head`` UserPermission only.

    RolePermission / ROLE_MATRIX must never confer head status (Management RO).
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    from apps.rbac.models import UserPermission

    return UserPermission.objects.filter(
        user_id=user.pk, permission__code="supply.head"
    ).exists()


def is_supply_portal_user(user) -> bool:
    """Operators who land on the unified Təchizat şöbəsi portal."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "role", None) == Role.SERVICE_DESK:
        return True
    return is_supply_head(user)


def can_issue_purchase_order(user) -> bool:
    """Authorized Supply operator may issue PO after Management commitment."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "role", None) == Role.MANAGEMENT:
        return False
    return user_has_permission(user, "procurement.edit")


def can_view_resident_directory(user) -> bool:
    """Business-contact directory — separate from legal/bank/identity/attendance."""
    return user_has_permission(user, "resident.directory.view") or user_has_permission(
        user, "resident.view"
    )
