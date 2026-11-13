"""Finance portal ACL helpers (A.7)."""

from apps.accounts.models import Role


def can_mutate_finance(user) -> bool:
    """Charge / invoice confirm / JE / period — accountant only."""
    if not user or not user.is_authenticated:
        return False
    return user.role == Role.ACCOUNTANT


def can_approve_payment(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.role == Role.MANAGEMENT


def can_close_period(user) -> bool:
    return can_mutate_finance(user)


def can_view_finance(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.role in (Role.ACCOUNTANT, Role.MANAGEMENT)
