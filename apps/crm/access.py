"""CRM ACL — sales mutate; management approve; accountant applications; admin RO; reception deny."""

from __future__ import annotations

from apps.accounts.models import Role

CRM_VIEW_ROLES = {
    Role.SALES,
    Role.MANAGEMENT,
    Role.ADMIN,
    Role.ACCOUNTANT,
}

CRM_MUTATE_ROLES = {Role.SALES}

CRM_APPROVE_ROLES = {Role.MANAGEMENT}

CRM_ACCOUNTANT_ROLES = {Role.ACCOUNTANT, Role.MANAGEMENT}


def _role(user) -> str | None:
    return getattr(user, "role", None) if user and getattr(user, "is_authenticated", False) else None


def can_view_crm(user) -> bool:
    role = _role(user)
    return role in CRM_VIEW_ROLES


def can_mutate_crm(user) -> bool:
    """Create/edit leads, activities, opportunities, offer versions, submit applications."""
    return _role(user) in CRM_MUTATE_ROLES


def can_approve_offer(user) -> bool:
    return _role(user) in CRM_APPROVE_ROLES


def can_review_lease_application(user) -> bool:
    return _role(user) in CRM_ACCOUNTANT_ROLES


def can_export_crm(user) -> bool:
    return can_view_crm(user) and _role(user) != Role.RECEPTION


def assert_can_view_crm(user) -> None:
    from apps.core.services import DomainError

    if not can_view_crm(user):
        raise DomainError("CRM-ə baxış icazəniz yoxdur.")


def assert_can_mutate_crm(user) -> None:
    from apps.core.services import DomainError

    if not can_mutate_crm(user):
        raise DomainError("CRM dəyişiklik icazəniz yoxdur (Admin yalnız oxuya bilər).")


def assert_can_approve_offer(user) -> None:
    from apps.core.services import DomainError

    if not can_approve_offer(user):
        raise DomainError("Təklif təsdiqi yalnız rəhbərlik üçündür.")


def assert_can_review_lease_application(user) -> None:
    from apps.core.services import DomainError

    if not can_review_lease_application(user):
        raise DomainError("Müqavilə müraciətinə baxış yalnız mühasib/rəhbərlik üçündür.")
