"""Finance portal ACL helpers (A.6 / A.7)."""

from apps.accounts.models import Role


def can_mutate_finance(user) -> bool:
    """Charge / invoice confirm / JE create+post — accountant only (A.6)."""
    if not user or not user.is_authenticated:
        return False
    return user.role == Role.ACCOUNTANT


def can_approve_payment(user) -> bool:
    """Payment approval stays with Management (A.7); does not grant GL post."""
    if not user or not user.is_authenticated:
        return False
    return user.role == Role.MANAGEMENT


def can_close_period(user) -> bool:
    """Period close — accountant (BUSINESS_DECISIONS A.6)."""
    return can_mutate_finance(user)


def can_reopen_period(user) -> bool:
    """Reopen — accountant via Finance portal (Management cannot enter /finance/)."""
    return can_mutate_finance(user)


def can_view_finance(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.role == Role.ACCOUNTANT
