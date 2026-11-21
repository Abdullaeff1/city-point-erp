"""CRM ACL — sales mutate; management approve; accountant applications; admin görmür (A.10 V2).

Dual gate: role sets AND PermissionCode (crm.view / crm.edit / crm.approve).
"""

from __future__ import annotations

from apps.accounts.models import Role
from apps.rbac.services import user_has_permission

CRM_VIEW_ROLES = {
    Role.SALES,
    Role.MANAGEMENT,
    Role.ACCOUNTANT,
}

CRM_MUTATE_ROLES = {Role.SALES}

CRM_APPROVE_ROLES = {Role.MANAGEMENT}

CRM_ACCOUNTANT_ROLES = {Role.ACCOUNTANT, Role.MANAGEMENT}


def _role(user) -> str | None:
    return getattr(user, "role", None) if user and getattr(user, "is_authenticated", False) else None


def can_view_crm(user) -> bool:
    role = _role(user)
    if role not in CRM_VIEW_ROLES:
        return False
    return user_has_permission(user, "crm.view")


def can_mutate_crm(user) -> bool:
    """Create/edit leads, activities, opportunities, offer versions, submit applications."""
    if _role(user) not in CRM_MUTATE_ROLES:
        return False
    return user_has_permission(user, "crm.edit")


def can_approve_offer(user) -> bool:
    if _role(user) not in CRM_APPROVE_ROLES:
        return False
    return user_has_permission(user, "crm.approve") or user_has_permission(user, "approval.decide")


def can_review_lease_application(user) -> bool:
    if _role(user) not in CRM_ACCOUNTANT_ROLES:
        return False
    # Accountant: finance/crm view; Management: crm.view
    return user_has_permission(user, "crm.view") or user_has_permission(user, "finance.view")


def can_export_crm(user) -> bool:
    return can_view_crm(user) and user_has_permission(user, "crm.export")


def assert_can_view_crm(user) -> None:
    from apps.core.services import DomainError

    if not can_view_crm(user):
        raise DomainError("CRM-ə baxış icazəniz yoxdur.")


def assert_can_mutate_crm(user) -> None:
    from apps.core.services import DomainError

    if not can_mutate_crm(user):
        raise DomainError("CRM dəyişiklik icazəniz yoxdur (yalnız satış).")


def assert_can_approve_offer(user) -> None:
    from apps.core.services import DomainError

    if not can_approve_offer(user):
        raise DomainError("Təklif təsdiqi yalnız rəhbərlik üçündür.")


def assert_can_review_lease_application(user) -> None:
    from apps.core.services import DomainError

    if not can_review_lease_application(user):
        raise DomainError("Müqavilə müraciətinə baxış yalnız mühasib/rəhbərlik üçündür.")
