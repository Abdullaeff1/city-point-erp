"""Rəhbərlik təsdiq ACL (ERP daxilində). Dual gate: role + approval.decide."""

from apps.accounts.models import Role
from apps.rbac.services import user_has_permission


def can_decide_approvals(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.role != Role.MANAGEMENT and user.role != Role.ADMIN:
        return False
    return user_has_permission(user, "approval.decide")
