"""Rəhbərlik təsdiq ACL (ERP daxilində)."""

from apps.accounts.models import Role


def can_decide_approvals(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.role == Role.MANAGEMENT
